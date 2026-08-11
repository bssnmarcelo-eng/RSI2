"""Convert underlying-strategy trades into a cash-account call simulation.

The signal engine remains responsible for deciding *when* to enter and exit.
This module replaces the financial instrument, marks each open call daily, and
rebuilds the equity curve without pretending historical option quotes existed.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from src.types import OptionConfig, OptionSizingMode, StrategyConfig

from .contracts import select_expiration, select_strike, year_fraction
from .pricing import price_call
from .volatility import synthetic_iv


@dataclass
class _Position:
    key: int
    source: dict
    ticker: str
    contracts: int
    strike: float
    expiration: pd.Timestamp
    entry_spot: float
    entry_quote: object
    entry_ask: float
    entry_iv: float
    entry_dividend_yield: float
    total_debits: float
    total_credits: float
    commissions: float
    roll_count: int = 0
    max_mark: float = 0.0


def _at_or_before(series: pd.Series, when, *, strictly_before: bool = False, fallback: float = 0.0) -> float:
    if series.empty:
        return float(fallback)
    stamp = pd.Timestamp(when)
    eligible = series.index < stamp if strictly_before else series.index <= stamp
    values = series.loc[eligible].dropna()
    return float(values.iloc[-1]) if len(values) else float(fallback)


def _dividend_series(frame: pd.DataFrame, fallback: float) -> pd.Series:
    if "dividend_yield" not in frame:
        return pd.Series(float(fallback), index=frame.index, dtype=float)
    values = pd.to_numeric(frame["dividend_yield"], errors="coerce").ffill().fillna(fallback)
    return values.clip(lower=0.0, upper=0.30)


def _half_spread(theoretical: float, cfg: OptionConfig) -> float:
    return max(theoretical * cfg.spread_pct / 2.0, cfg.minimum_half_spread)


def _ask(theoretical: float, cfg: OptionConfig) -> float:
    return theoretical + _half_spread(theoretical, cfg)


def _bid(theoretical: float, cfg: OptionConfig) -> float:
    return max(theoretical - _half_spread(theoretical, cfg), 0.0)


def _quote(spot: float, strike: float, when, expiration, iv: float, dividend_yield: float,
           rate: float, cfg: OptionConfig):
    return price_call(
        spot=spot,
        strike=strike,
        time_years=year_fraction(when, expiration),
        rate=rate,
        volatility=iv,
        dividend_yield=dividend_yield,
        model=cfg.pricing_model,
        binomial_steps=cfg.binomial_steps,
    )


def _spot_at(frame: pd.DataFrame, when, field: str = "close") -> float:
    series = frame[field].dropna()
    return _at_or_before(series, when, fallback=float(series.iloc[0]))


def _first_quote_after(frame: pd.DataFrame, when, field: str) -> tuple[pd.Timestamp, float]:
    """Return the first tradable quote strictly after ``when``."""
    series = pd.to_numeric(frame[field], errors="coerce").dropna()
    eligible = series.loc[series.index > pd.Timestamp(when)]
    if len(eligible):
        return pd.Timestamp(eligible.index[0]), float(eligible.iloc[0])
    return pd.Timestamp(series.index[-1]), float(series.iloc[-1])


def _last_quote_at_or_before(frame: pd.DataFrame, when, field: str) -> tuple[pd.Timestamp, float]:
    """Return the last tradable quote at or before ``when``."""
    series = pd.to_numeric(frame[field], errors="coerce").dropna()
    eligible = series.loc[series.index <= pd.Timestamp(when)]
    if len(eligible):
        return pd.Timestamp(eligible.index[-1]), float(eligible.iloc[-1])
    return pd.Timestamp(series.index[0]), float(series.iloc[0])


def _base_frames(base_result) -> dict[str, pd.DataFrame]:
    if hasattr(base_result, "frames"):
        return dict(base_result.frames)
    ticker = str(getattr(base_result.config, "ticker", ""))
    return {ticker: base_result.data}


def _prepare_trade_calendar(base_result, option_frames: dict[str, pd.DataFrame], config: StrategyConfig):
    """Translate bar labels into actual option transaction dates and spots.

    Weekly Norgate bars are labelled by the week ending date, even though their
    open is the first session of that week.  A NEXT_OPEN order therefore maps to
    the first daily session after the preceding signal-bar label.  The stock
    trade itself is never changed; this translated copy exists solely for the
    call valuation overlay.
    """
    tagged = copy.copy(base_result)
    trades = base_result.trades.reset_index(drop=True).copy()
    trades["_option_source_key"] = np.arange(len(trades), dtype=int)
    signal_frames = _base_frames(base_result)

    for idx, row in trades.iterrows():
        ticker = str(row.get("ticker", ""))
        option_frame = option_frames.get(ticker)
        signal_frame = signal_frames.get(ticker)
        if option_frame is None or option_frame.empty:
            continue

        signal_date = pd.Timestamp(row["signal_date"])
        if config.entry_execution.value == "signal_close":
            entry_date, entry_spot = _last_quote_at_or_before(option_frame, signal_date, "close")
        elif config.entry_execution.value == "limit_at_close":
            limit = float(row["signal_close"])
            candidates = option_frame.loc[option_frame.index > signal_date]
            fill = candidates.loc[pd.to_numeric(candidates["low"], errors="coerce") <= limit]
            if len(fill):
                entry_date = pd.Timestamp(fill.index[0])
                day_open = float(fill["open"].iloc[0])
                entry_spot = min(day_open, limit)
            else:
                entry_date, entry_spot = _first_quote_after(option_frame, signal_date, "open")
        else:
            entry_date, entry_spot = _first_quote_after(option_frame, signal_date, "open")

        stock_exit_date = pd.Timestamp(row["exit_date"])
        reason = str(row.get("exit_reason", ""))
        forced_close = reason.lower().startswith(("end of data", "final bar", "fim dos dados"))
        if config.exit_execution.value == "next_open" and not forced_close and signal_frame is not None:
            labels = pd.DatetimeIndex(signal_frame.index)
            prior = labels[labels < stock_exit_date]
            exit_signal_date = pd.Timestamp(prior[-1]) if len(prior) else stock_exit_date
            exit_date, exit_spot = _first_quote_after(option_frame, exit_signal_date, "open")
        else:
            exit_date, exit_spot = _last_quote_at_or_before(option_frame, stock_exit_date, "close")

        if exit_date < entry_date:
            exit_date, exit_spot = _last_quote_at_or_before(option_frame, stock_exit_date, "close")
        trades.at[idx, "entry_date"] = entry_date
        trades.at[idx, "entry_price"] = entry_spot
        trades.at[idx, "exit_date"] = exit_date
        trades.at[idx, "exit_price"] = exit_spot

    tagged.trades = trades
    return tagged


def _contracts_for(equity: float, cash: float, spot: float, ask: float, delta: float,
                   cfg: OptionConfig) -> int:
    unit_cost = ask * cfg.contract_multiplier + cfg.commission_per_contract
    if unit_cost <= 0 or equity <= 0 or cash <= 0:
        return 0
    budget = equity * cfg.premium_risk_pct / 100.0
    if cfg.sizing_mode == OptionSizingMode.DELTA_EQUIVALENT:
        target_shares = budget / spot if spot > 0 else 0.0
        desired = math.floor(target_shares / (max(delta, 1e-6) * cfg.contract_multiplier))
    else:
        desired = math.floor(budget / unit_cost)
    affordable = math.floor(cash / unit_cost)
    return max(min(desired, affordable), 0)


def apply_synthetic_call_overlay(
    base_result,
    data_by_ticker: dict[str, pd.DataFrame],
    config: StrategyConfig,
    *,
    initial_capital: float,
    max_positions: int = 1,
    include_scenarios: bool = True,
):
    """Return a result shaped like ``base_result`` but valued as long ATM calls."""
    cfg = config.options
    result = copy.copy(base_result)
    result.config = config
    result.warnings = list(base_result.warnings)
    result.warnings.append(
        "Opções em modo sintético mark-to-model: strikes, vencimentos, IV e bid/ask são hipóteses, não cotações históricas executáveis."
    )

    frames = {ticker: frame.sort_index() for ticker, frame in data_by_ticker.items()}
    iv_by_ticker = {ticker: synthetic_iv(frame["close"], cfg) for ticker, frame in frames.items()}
    div_by_ticker = {ticker: _dividend_series(frame, cfg.dividend_yield) for ticker, frame in frames.items()}
    rate_by_ticker = {
        ticker: (pd.to_numeric(frame["risk_free_rate"], errors="coerce").ffill()
                 if cfg.risk_free_mode == "norgate" and "risk_free_rate" in frame
                 else pd.Series(cfg.risk_free_rate, index=frame.index, dtype=float))
        for ticker, frame in frames.items()
    }
    if not frames:
        return result
    calendar_index = pd.DatetimeIndex(sorted(set().union(*[frame.index for frame in frames.values()])))
    candidates = []
    capital_event_exits = 0
    for key, row in base_result.trades.reset_index(drop=True).iterrows():
        source = row.to_dict()
        source["entry_date"] = pd.Timestamp(source["entry_date"])
        source["exit_date"] = pd.Timestamp(source["exit_date"])
        ticker = str(source.get("ticker", ""))
        frame = frames.get(ticker)
        if frame is not None and "capital_event" in frame:
            event_mask = frame["capital_event"].fillna(False).astype(bool)
            events = frame.index[event_mask & (frame.index > source["entry_date"])
                                 & (frame.index <= source["exit_date"])]
            if len(events):
                source["exit_date"] = pd.Timestamp(events[0])
                source["exit_price"] = float(frame.loc[events[0], "close"])
                source["exit_reason"] = "Capital event — synthetic contract closed"
                capital_event_exits += 1
        candidates.append((key, source))
    entries: dict[pd.Timestamp, list[tuple[int, dict]]] = {}
    exits: dict[pd.Timestamp, list[int]] = {}
    for key, source in candidates:
        entries.setdefault(pd.Timestamp(source["entry_date"]), []).append((key, source))
        exits.setdefault(pd.Timestamp(source["exit_date"]), []).append(key)
    for day in entries:
        entries[day].sort(key=lambda item: float(item[1].get("rsi_at_signal", 100.0)))

    cash = float(initial_capital)
    positions: dict[int, _Position] = {}
    completed: list[dict] = []
    closed_today: list[int] = []
    equity_values = []
    open_counts = []
    exposures = []
    skipped = 0

    def market_inputs(ticker: str, when, *, transaction: bool) -> tuple[float, float, float]:
        iv = _at_or_before(iv_by_ticker[ticker], when, strictly_before=transaction, fallback=cfg.iv_floor)
        div = _at_or_before(div_by_ticker[ticker], when, strictly_before=transaction, fallback=cfg.dividend_yield)
        rate = _at_or_before(rate_by_ticker[ticker], when, strictly_before=transaction,
                             fallback=cfg.risk_free_rate)
        return min(max(iv, cfg.iv_floor), cfg.iv_cap), max(div, 0.0), rate

    def close_position(
        key: int,
        when,
        spot: float,
        *,
        exit_reason: str | None = None,
        expiration_settlement: bool = False,
    ) -> None:
        nonlocal cash
        pos = positions.pop(key)
        iv, div, rate = market_inputs(pos.ticker, when, transaction=True)
        quote = _quote(spot, pos.strike, when, pos.expiration, iv, div, rate, cfg)
        # At expiry there is no remaining time value or bid/ask execution: the
        # synthetic long call is cash-settled at its intrinsic value.
        bid = quote.intrinsic if expiration_settlement else _bid(quote.price, cfg)
        credit = bid * cfg.contract_multiplier * pos.contracts
        commission = 0.0 if expiration_settlement else cfg.commission_per_contract * pos.contracts
        cash += credit - commission
        pos.total_credits += credit
        pos.commissions += commission
        net_pnl = pos.total_credits - pos.total_debits - pos.commissions
        gross_pnl = pos.total_credits - pos.total_debits
        basis = pos.total_debits + pos.commissions
        row = dict(pos.source)
        row.update({
            "exit_date": pd.Timestamp(when),
            "exit_reason": exit_reason or pos.source.get("exit_reason", "Underlying exit"),
            "instrument": "synthetic_atm_call",
            "synthetic": True,
            "underlying_entry_price": pos.entry_spot,
            "underlying_exit_price": spot,
            "underlying_return": spot / pos.entry_spot - 1.0 if pos.entry_spot else 0.0,
            "entry_price": pos.entry_ask,
            "exit_price": bid,
            "option_entry_theoretical": pos.entry_quote.price,
            "option_exit_theoretical": quote.price,
            "option_intrinsic_entry": pos.entry_quote.intrinsic,
            "option_time_value_entry": pos.entry_quote.time_value,
            "option_intrinsic_exit": quote.intrinsic,
            "option_time_value_exit": quote.time_value,
            "strike": pos.source.get("initial_strike", pos.strike),
            "final_strike": pos.strike,
            "expiration": pos.expiration,
            "dte_entry": int((pd.Timestamp(pos.source["initial_expiration"]) - pd.Timestamp(pos.source["entry_date"])).days),
            "dte_exit": max(int((pos.expiration - pd.Timestamp(when)).days), 0),
            "iv_entry": pos.entry_iv,
            "iv_exit": iv,
            "dividend_yield_entry": pos.entry_dividend_yield,
            "risk_free_rate_exit": rate,
            "delta_entry": pos.entry_quote.delta,
            "delta_exit": quote.delta,
            "gamma_entry": pos.entry_quote.gamma,
            "theta_entry": pos.entry_quote.theta,
            "vega_entry": pos.entry_quote.vega,
            "contracts": pos.contracts,
            "contract_multiplier": cfg.contract_multiplier,
            "roll_count": pos.roll_count,
            "option_model": pos.entry_quote.model,
            "gross_return": gross_pnl / pos.total_debits if pos.total_debits else 0.0,
            "net_return": net_pnl / basis if basis else 0.0,
            "pnl": net_pnl,
            "option_commissions": pos.commissions,
            "mfe": pos.max_mark / pos.entry_ask - 1.0 if pos.entry_ask else 0.0,
            "equity_after": float("nan"),
        })
        completed.append(row)
        closed_today.append(len(completed) - 1)

    for when in calendar_index:
        closed_today = []
        # Exit decisions come from the underlying engine; use its exact stop/open/close spot.
        for key in exits.get(when, []):
            if key in positions:
                source = positions[key].source
                close_position(key, when, float(source["exit_price"]))

        # A contract is opened only once. If the underlying trade outlives it,
        # settle the call at expiry and do not open a replacement contract.
        for key, pos in list(positions.items()):
            if when < pos.expiration:
                continue
            frame = frames[pos.ticker]
            spot = _spot_at(frame, pos.expiration)
            close_position(
                key,
                pos.expiration,
                spot,
                exit_reason="Vencimento da call",
                expiration_settlement=True,
            )

        # Mark existing positions before sizing new entries.
        mark_value = 0.0
        for pos in positions.values():
            spot = _spot_at(frames[pos.ticker], when)
            iv, div, rate = market_inputs(pos.ticker, when, transaction=False)
            mark = _quote(spot, pos.strike, when, pos.expiration, iv, div, rate, cfg).price
            pos.max_mark = max(pos.max_mark, mark)
            mark_value += mark * cfg.contract_multiplier * pos.contracts
        equity_before_entries = cash + mark_value

        for key, source in entries.get(when, []):
            if key in positions:
                continue
            if max_positions > 0 and len(positions) >= max_positions:
                skipped += 1
                continue
            ticker = str(source.get("ticker", ""))
            if ticker not in frames:
                skipped += 1
                continue
            spot = float(source["entry_price"])
            strike = select_strike(
                spot,
                cfg.strike_mode,
                cfg.strike_interval,
                cfg.otm_pct,
            )
            expiration = select_expiration(when, cfg.target_dte)
            iv, div, rate = market_inputs(ticker, when, transaction=True)
            quote = _quote(spot, strike, when, expiration, iv, div, rate, cfg)
            ask = _ask(quote.price, cfg)
            contracts = _contracts_for(equity_before_entries, cash, spot, ask, quote.delta, cfg)
            if contracts <= 0:
                skipped += 1
                continue
            debit = ask * cfg.contract_multiplier * contracts
            commission = cfg.commission_per_contract * contracts
            cash -= debit + commission
            source["initial_strike"] = strike
            source["initial_expiration"] = expiration
            source["risk_free_rate_entry"] = rate
            positions[key] = _Position(
                key=key, source=source, ticker=ticker, contracts=contracts,
                strike=strike, expiration=expiration, entry_spot=spot,
                entry_quote=quote, entry_ask=ask, entry_iv=iv,
                entry_dividend_yield=div, total_debits=debit,
                total_credits=0.0, commissions=commission, max_mark=quote.price,
            )

        mark_value = 0.0
        for pos in positions.values():
            spot = _spot_at(frames[pos.ticker], when)
            iv, div, rate = market_inputs(pos.ticker, when, transaction=False)
            mark = _quote(spot, pos.strike, when, pos.expiration, iv, div, rate, cfg).price
            pos.max_mark = max(pos.max_mark, mark)
            mark_value += mark * cfg.contract_multiplier * pos.contracts
        equity_now = cash + mark_value
        equity_values.append(equity_now)
        open_counts.append(len(positions))
        exposures.append(mark_value / equity_now if equity_now else 0.0)
        for completed_index in closed_today:
            completed[completed_index]["equity_after"] = equity_now

    if positions:
        final_date = calendar_index[-1]
        for key in list(positions):
            close_position(key, final_date, _spot_at(frames[positions[key].ticker], final_date))
        equity_values[-1] = cash
        open_counts[-1] = 0
        exposures[-1] = 0.0

    result.trades = pd.DataFrame(completed).sort_values("exit_date").reset_index(drop=True) if completed else base_result.trades.iloc[0:0].copy()
    result.equity_curve = pd.Series(equity_values, index=calendar_index, name="equity")
    if hasattr(result, "positions_open"):
        result.positions_open = pd.Series(open_counts, index=calendar_index, name="open_positions")
        result.exposure = pd.Series(exposures, index=calendar_index, name="gross_exposure")
        result.time_in_market = float((np.asarray(open_counts) > 0).mean()) if open_counts else 0.0
        result.avg_positions = float(np.mean(open_counts)) if open_counts else 0.0
        result.max_concurrent = int(max(open_counts, default=0))
    if skipped:
        result.warnings.append(f"{skipped} sinal(is) de opção foram ignorados por limite de posições ou prêmio insuficiente.")
    if capital_event_exits:
        result.warnings.append(
            f"{capital_event_exits} posição(ões) sintética(s) foram encerradas em evento de capital; contratos ajustados históricos não estão disponíveis."
        )
    result.warnings.append(
        "Sem rolagem: se o trade da ação permanecer aberto, a call encerra no "
        "vencimento pelo valor intrínseco, sem spread ou comissão de saída."
    )
    if include_scenarios:
        scenario_results = {"base": result}
        for label, factor in (("low", 0.85), ("high", 1.15)):
            scenario_cfg = replace(
                config,
                options=replace(config.options, iv_scenario=factor),
            )
            scenario_results[label] = apply_synthetic_call_overlay(
                base_result,
                data_by_ticker,
                scenario_cfg,
                initial_capital=initial_capital,
                max_positions=max_positions,
                include_scenarios=False,
            )
        result.scenario_equity = {
            label: scenario.equity_curve for label, scenario in scenario_results.items()
        }
        result.scenario_metrics = {
            label: {
                "final_equity": float(scenario.equity_curve.iloc[-1]) if len(scenario.equity_curve) else initial_capital,
                "total_return": ((float(scenario.equity_curve.iloc[-1]) / initial_capital) - 1.0
                                 if len(scenario.equity_curve) and initial_capital else 0.0),
            }
            for label, scenario in scenario_results.items()
        }
    return result


_COMPARISON_COLUMNS = {
    "instrument": "option_instrument",
    "synthetic": "option_synthetic",
    "entry_date": "option_entry_date",
    "exit_date": "option_exit_date",
    "exit_reason": "option_exit_reason",
    "underlying_entry_price": "option_underlying_entry_price",
    "underlying_exit_price": "option_underlying_exit_price",
    "underlying_return": "option_underlying_return",
    "entry_price": "option_entry_price",
    "exit_price": "option_exit_price",
    "option_entry_theoretical": "option_entry_theoretical",
    "option_exit_theoretical": "option_exit_theoretical",
    "option_intrinsic_entry": "option_intrinsic_entry",
    "option_time_value_entry": "option_time_value_entry",
    "option_intrinsic_exit": "option_intrinsic_exit",
    "option_time_value_exit": "option_time_value_exit",
    "strike": "option_strike",
    "final_strike": "option_final_strike",
    "expiration": "option_expiration",
    "dte_entry": "option_dte_entry",
    "dte_exit": "option_dte_exit",
    "iv_entry": "option_iv_entry",
    "iv_exit": "option_iv_exit",
    "dividend_yield_entry": "option_dividend_yield_entry",
    "risk_free_rate_entry": "option_risk_free_rate_entry",
    "risk_free_rate_exit": "option_risk_free_rate_exit",
    "delta_entry": "option_delta_entry",
    "delta_exit": "option_delta_exit",
    "gamma_entry": "option_gamma_entry",
    "theta_entry": "option_theta_entry",
    "vega_entry": "option_vega_entry",
    "contracts": "option_contracts",
    "contract_multiplier": "option_contract_multiplier",
    "roll_count": "option_roll_count",
    "option_model": "option_model",
    "gross_return": "option_gross_return",
    "net_return": "option_net_return",
    "pnl": "option_pnl",
    "option_commissions": "option_commissions",
    "mfe": "option_mfe",
}


def annotate_synthetic_call_comparison(
    base_result,
    option_data_by_ticker: dict[str, pd.DataFrame],
    config: StrategyConfig,
    *,
    initial_capital: float,
    max_positions: int = 1,
):
    """Keep the stock backtest intact and append a same-trade call view.

    Signals, exits, holding bars, stock P&L and the primary equity curve come
    exclusively from ``base_result``.  The option account is a parallel
    mark-to-model scenario whose fields are prefixed with ``option_``.
    """
    prepared = _prepare_trade_calendar(base_result, option_data_by_ticker, config)
    option_result = apply_synthetic_call_overlay(
        prepared,
        option_data_by_ticker,
        config,
        initial_capital=initial_capital,
        max_positions=max_positions,
    )

    result = copy.copy(base_result)
    result.config = config
    result.trades = base_result.trades.reset_index(drop=True).copy()
    result.trades["option_status"] = "not_priced"

    priced = option_result.trades
    if not priced.empty and "_option_source_key" in priced:
        indexed = priced.set_index("_option_source_key", drop=False)
        for source_key, option_row in indexed.iterrows():
            key = int(source_key)
            if key < 0 or key >= len(result.trades):
                continue
            if str(option_row.get("instrument", "")) != "synthetic_atm_call":
                continue
            result.trades.at[key, "option_status"] = "priced"
            for source, target in _COMPARISON_COLUMNS.items():
                if source in option_row:
                    result.trades.at[key, target] = option_row[source]

    result.warnings = list(dict.fromkeys([*base_result.warnings, *option_result.warnings]))
    result.warnings.append(
        "Sinais, saídas e métricas principais permanecem no ativo e na periodicidade selecionada; "
        "as colunas option_* são a equivalência mark-to-model das mesmas operações."
    )
    result.scenario_equity = getattr(option_result, "scenario_equity", {})
    result.scenario_metrics = getattr(option_result, "scenario_metrics", {})
    result.option_equity_curve = option_result.equity_curve
    return result
