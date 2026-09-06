"""Shared-capital, multi-asset portfolio backtest engine.

This runs the SAME long-only RSI(2) + bullish-candlestick strategy across many
assets at once, but with a single pooled cash account — a real portfolio rather
than a set of independent backtests.

Capital model (IBKR-style margin)
----------------------------------
* One cash pool starts at ``initial_capital``.
* ``buying_power = equity * leverage``. With leverage > 1 the account may borrow
  (cash goes negative) as long as total long exposure stays within buying power.
* Each new position is sized at ``pct_per_trade`` percent of current equity
  (notional). The number of simultaneous positions is therefore limited
  naturally by available buying power (and optionally a hard ``max_positions``).
* When several signals target the same entry date, a causal cross-sectional
  ranking admits only the configured number of candidates (one by default).

No look-ahead bias
------------------
* Per-asset signals are built with :func:`build_signal_frame` (causal).
* Signals are confirmed at the close; with the default NEXT_OPEN execution the
  fill happens at the asset's next open. Position sizing uses equity marked at
  the *previous* close, so no same-bar future information is used.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .backtest_engine import add_period_mfe, build_signal_frame
from .types import (
    Execution,
    InstrumentType,
    PortfolioConfig,
    PortfolioEntryRanking,
    PortfolioSizing,
    StrategyConfig,
    Trade,
)
from .utils import commission_for, financing_cost


@dataclass
class _Position:
    """Internal bookkeeping for one open position in the portfolio."""

    ticker: str
    shares: float
    entry_price: float
    entry_index: int
    entry_date: object
    entry_commission: float
    signal_date: object
    signal_close: float
    signal_low: float
    signal_range: float
    signal_body_percentile: float
    signal_atr_mult: float
    rsi_at_signal: float
    pattern: str
    entered_at_close: bool
    max_high_seen: float = 0.0  # running peak high for MFE calculation


@dataclass
class PortfolioResult:
    """Everything the UI needs to render portfolio results."""

    trades: pd.DataFrame
    equity_curve: pd.Series           # combined portfolio equity at each bar close
    positions_open: pd.Series         # number of open positions at each bar close
    exposure: pd.Series               # gross long exposure / equity at each bar close
    breadth: pd.Series                # eligible members above their own trailing SMA
    frames: Dict[str, pd.DataFrame]   # per-ticker OHLC + signal frames (for charts)
    config: StrategyConfig
    portfolio: PortfolioConfig
    time_in_market: float             # fraction of bars with >= 1 open position
    avg_positions: float              # mean number of open positions
    max_concurrent: int               # peak simultaneous positions
    warnings: List[str]
    financing_costs: float = 0.0
    dividend_income: float = 0.0


class PortfolioEngine:
    """Runs the strategy across multiple assets sharing one capital pool."""

    def __init__(
        self,
        data_by_ticker: Dict[str, pd.DataFrame],
        config: StrategyConfig,
        portfolio: PortfolioConfig,
        option_data_by_ticker: Optional[Dict[str, pd.DataFrame]] = None,
    ):
        self.data_by_ticker = data_by_ticker
        self.option_data_by_ticker = option_data_by_ticker
        self.config = config
        self.portfolio = portfolio
        self.warnings: List[str] = []

    # ----------------------------------------------------------------- costs
    def _commission(self, shares: float, notional: float) -> float:
        return commission_for(self.config.costs, shares, notional)

    def _buy_price(self, raw: float) -> float:
        return raw * (1.0 + self.config.costs.slippage_bps / 10_000.0)

    def _sell_price(self, raw: float) -> float:
        return raw * (1.0 - self.config.costs.slippage_bps / 10_000.0)

    # ------------------------------------------------------------------ exits
    def _exit_reason(self, pos: _Position, i: int, arr: dict) -> Optional[str]:
        """First triggered exit reason at the close of bar ``i`` for ``pos``."""
        cfg = self.config.exits
        close = arr["close"][i]
        rsi_val = arr["rsi"][i]
        local_i = int(arr["bar_number"][i])
        bars_held = local_i - pos.entry_index

        if cfg.use_rsi_exit and not np.isnan(rsi_val) and rsi_val > cfg.rsi_exit_threshold:
            return f"RSI > {cfg.rsi_exit_threshold:g}"
        if cfg.use_rsi_cum_exit:
            rsi_cum_val = arr["rsi_cum"][i]
            if not np.isnan(rsi_cum_val) and rsi_cum_val > cfg.rsi_cum_threshold:
                return f"RSI({cfg.rsi_cum_periods}) acum > {cfg.rsi_cum_threshold:g}"
        if cfg.use_max_bars and bars_held >= cfg.max_bars:
            return f"Time stop ({cfg.max_bars} bars)"
        if cfg.use_profit_target and close >= pos.entry_price * (1.0 + cfg.profit_target_pct / 100.0):
            return f"Profit target (+{cfg.profit_target_pct:g}%)"
        if cfg.use_stop_loss and close <= pos.entry_price * (1.0 - cfg.stop_loss_pct / 100.0):
            return f"Stop loss (-{cfg.stop_loss_pct:g}%)"
        if cfg.use_sma_exit:
            sma_val = arr["sma"][i]
            if not np.isnan(sma_val) and close > sma_val:
                return f"Close > SMA({cfg.sma_period})"
        return None

    # ----------------------------------------------------------------- helpers
    def _close_position(self, pos: _Position, exit_raw: float, local_i: int, date,
                        reason: str, cash: float) -> tuple:
        """Sell ``pos`` at ``exit_raw`` (pre-slippage). Returns (cash, Trade)."""
        exec_price = self._sell_price(exit_raw)
        proceeds = pos.shares * exec_price
        exit_commission = self._commission(pos.shares, proceeds)
        cash = cash + proceeds - exit_commission

        entry_notional = pos.shares * pos.entry_price
        gross_pnl = proceeds - entry_notional
        net_pnl = gross_pnl - pos.entry_commission - exit_commission
        cost_basis = entry_notional + pos.entry_commission
        gross_return = (exec_price / pos.entry_price) - 1.0 if pos.entry_price else 0.0
        net_return = net_pnl / cost_basis if cost_basis else 0.0

        mfe_raw = pos.max_high_seen - pos.entry_price
        mfe = mfe_raw / pos.entry_price if pos.entry_price else 0.0

        trade = Trade(
            ticker=pos.ticker,
            signal_date=pos.signal_date,
            signal_close=pos.signal_close,
            rsi_at_signal=pos.rsi_at_signal,
            signal_range=pos.signal_range,
            signal_body_percentile=pos.signal_body_percentile,
            signal_atr_mult=pos.signal_atr_mult,
            pattern=pos.pattern,
            entry_date=pos.entry_date,
            entry_price=pos.entry_price,
            exit_date=date,
            exit_price=exec_price,
            exit_reason=reason,
            bars_held=local_i - pos.entry_index,
            gross_return=gross_return,
            net_return=net_return,
            pnl=net_pnl,
            equity_after=float("nan"),  # filled in after each bar is marked
            mfe=mfe,
        )
        return cash, trade

    # -------------------------------------------------------------------- run
    def run(self, progress=None) -> PortfolioResult:
        cfg = self.config
        pf = self.portfolio

        if cfg.options.enabled or cfg.instrument == InstrumentType.SYNTHETIC_ATM_CALL:
            from .options.simulation import annotate_synthetic_call_comparison

            base_cfg = replace(
                cfg,
                instrument=InstrumentType.STOCK,
                options=replace(cfg.options, enabled=False),
            )
            base = PortfolioEngine(self.data_by_ticker, base_cfg, pf).run(progress=progress)
            return annotate_synthetic_call_comparison(
                base,
                self.option_data_by_ticker or self.data_by_ticker,
                cfg,
                initial_capital=pf.initial_capital,
                max_positions=pf.max_positions,
            )

        # Build causal signal frames per ticker.
        frames = {t: build_signal_frame(df, cfg) for t, df in self.data_by_ticker.items()}

        if pf.max_entries_per_date < 0:
            raise ValueError("max_entries_per_date must be zero or greater")
        if pf.ranking_lookback < 2:
            raise ValueError("ranking_lookback must be at least 2")
        if pf.quality_trend_period < 2:
            raise ValueError("quality_trend_period must be at least 2")
        if not 0.0 < pf.quality_max_range_rank_pct <= 100.0:
            raise ValueError("quality_max_range_rank_pct must be between 0 and 100")

        # Cross-sectional ranking inputs.  Every value at bar i uses only data
        # available through that bar's close, so selection remains causal.
        for frame in frames.values():
            lookback = pf.ranking_lookback
            close = frame["close"].astype(float)
            trend_sma = close.rolling(lookback, min_periods=lookback).mean()
            frame["rank_trend"] = (close / trend_sma).replace([np.inf, -np.inf], np.nan)
            quality_sma = close.rolling(
                pf.quality_trend_period,
                min_periods=pf.quality_trend_period,
            ).mean()
            frame["quality_trend"] = (close / quality_sma - 1.0).replace(
                [np.inf, -np.inf], np.nan
            )
            frame["rank_volatility"] = close.pct_change(fill_method=None).rolling(
                lookback, min_periods=lookback
            ).std()
            if "volume" in frame:
                volume = pd.to_numeric(frame["volume"], errors="coerce")
                average_volume = volume.rolling(lookback, min_periods=lookback).mean()
                frame["rank_relative_volume"] = (volume / average_volume).replace(
                    [np.inf, -np.inf], np.nan
                )
            else:
                frame["rank_relative_volume"] = np.nan

        # Common (union) calendar across all assets.
        union = pd.DatetimeIndex(sorted(set().union(*[f.index for f in frames.values()])))
        n = len(union)
        tickers = list(frames.keys())

        breadth = np.full(n, np.nan, dtype=float)
        breadth_eligible = np.ones(n, dtype=bool)
        if pf.use_breadth_filter:
            if pf.breadth_sma_period < 1:
                raise ValueError("breadth_sma_period must be at least 1")
            if not 0.0 <= pf.breadth_threshold_pct <= 100.0:
                raise ValueError("breadth_threshold_pct must be between 0 and 100")

            above_count = np.zeros(n, dtype=int)
            eligible_count = np.zeros(n, dtype=int)
            has_membership = all("_member" in frame.columns for frame in frames.values())
            for frame in frames.values():
                close = frame["close"].astype(float)
                sma = close.rolling(
                    pf.breadth_sma_period,
                    min_periods=pf.breadth_sma_period,
                ).mean()
                if "_member" in frame.columns:
                    member = frame["_member"].fillna(False).astype(bool)
                else:
                    # CSV/inline universes have no point-in-time membership
                    # series.  In that case the loaded assets define the
                    # breadth universe and this limitation is made explicit.
                    member = pd.Series(True, index=frame.index)
                eligible = member & close.notna() & sma.notna()
                above = eligible & (close > sma)
                eligible_count += eligible.reindex(union).fillna(False).to_numpy(dtype=bool)
                above_count += above.reindex(union).fillna(False).to_numpy(dtype=bool)

            valid = eligible_count > 0
            breadth[valid] = above_count[valid] / eligible_count[valid]
            breadth_eligible = valid & (breadth >= pf.breadth_threshold_pct / 100.0)
            if not has_membership:
                self.warnings.append(
                    "Breadth calculado sobre o universo de ativos carregado; "
                    "ative constituintes point-in-time para representar fielmente o índice histórico."
                )

        # Pre-align every series onto the union index as numpy arrays.
        arr: Dict[str, dict] = {}
        for t, f in frames.items():
            close = f["close"].reindex(union)
            has_bar = union.isin(f.index)
            bar_number = np.full(n, -1, dtype=int)
            bar_number[has_bar] = np.arange(len(f), dtype=int)
            arr[t] = {
                "open": f["open"].reindex(union).to_numpy(dtype=float),
                "high": f["high"].reindex(union).to_numpy(dtype=float),
                "low": f["low"].reindex(union).to_numpy(dtype=float),
                "close": close.to_numpy(dtype=float),
                "mark": close.ffill().to_numpy(dtype=float),   # for equity marking
                "rsi": f["rsi"].reindex(union).to_numpy(dtype=float),
                "rsi_cum": f["rsi_cum"].reindex(union).to_numpy(dtype=float),
                "sma": f["sma_exit"].reindex(union).to_numpy(dtype=float),
                "atr_mult": f["atr_mult"].reindex(union).to_numpy(dtype=float),
                "rank_trend": f["rank_trend"].reindex(union).to_numpy(dtype=float),
                "quality_trend": f["quality_trend"].reindex(union).to_numpy(dtype=float),
                "rank_volatility": f["rank_volatility"].reindex(union).to_numpy(dtype=float),
                "rank_relative_volume": f["rank_relative_volume"].reindex(union).to_numpy(dtype=float),
                "signal": f["entry_signal"].reindex(union).fillna(False).to_numpy(dtype=bool),
                "pattern": f["pattern"].reindex(union).fillna("").to_numpy(dtype=object),
                "dividend": (f["dividend"].reindex(union).fillna(0.0).to_numpy(dtype=float)
                             if "dividend" in f else np.zeros(n, dtype=float)),
                "split": (f["split"].reindex(union).fillna(0.0).to_numpy(dtype=float)
                          if "split" in f else np.zeros(n, dtype=float)),
                "has_bar": has_bar,
                "bar_number": bar_number,
                "last_bar": int(np.flatnonzero(has_bar)[-1]),
            }

        cash = float(pf.initial_capital)
        positions: Dict[str, _Position] = {}
        pending_entries: Dict[str, dict] = {}   # ticker -> signal meta (fill next open)
        pending_exits: Dict[str, str] = {}       # ticker -> reason (fill next open)

        trades: List[Trade] = []
        trade_bar: List[int] = []                # union index of each trade's exit
        equity = np.empty(n, dtype=float)
        n_open = np.zeros(n, dtype=int)
        gross_exposure = np.zeros(n, dtype=float)
        end_of_data_closes = 0
        total_financing = 0.0
        total_dividends = 0.0

        # marks_prev[t] = ticker's most recent close strictly before today.
        marks_prev = {t: np.nan for t in tickers}

        unlimited = pf.max_positions <= 0
        is_limit = cfg.entry_execution == Execution.LIMIT_AT_CLOSE

        def _long_value(marks: dict) -> float:
            """Total long market value of open positions using the given marks."""
            return sum(
                p.shares * (0.0 if np.isnan(marks[t]) else marks[t])
                for t, p in positions.items()
            )

        _step = max(1, n // 200)

        for i in range(n):
            if progress and i % _step == 0:
                progress(i / n)
            date = union[i]

            # Financing accrues on negative cash between portfolio calendar
            # observations. Stock-borrow fees remain zero for this long-only engine.
            if i > 0 and cash < 0:
                days = max((date - union[i - 1]).total_seconds() / 86_400.0, 0.0)
                charge = financing_cost(cfg.costs, -cash, 0.0, days)
                cash -= charge
                total_financing += charge

            # Raw-price CSVs may provide explicit cash dividends and split ratios.
            # This is opt-in to avoid double-counting adjusted/Total Return data.
            if cfg.apply_corporate_actions:
                for t, pos in list(positions.items()):
                    if not arr[t]["has_bar"][i]:
                        continue
                    ratio = float(arr[t]["split"][i])
                    if np.isfinite(ratio) and ratio > 0 and ratio != 1.0:
                        pos.shares *= ratio
                        pos.entry_price /= ratio
                        pos.signal_close /= ratio
                        pos.signal_low /= ratio
                        pos.max_high_seen /= ratio
                        if not np.isnan(marks_prev[t]):
                            marks_prev[t] /= ratio
                    dividend = float(arr[t]["dividend"][i])
                    if np.isfinite(dividend) and dividend > 0:
                        income = pos.shares * dividend
                        cash += income
                        total_dividends += income

            # --- 1. Fill scheduled EXITS at this bar's open ---------------------
            for t in list(pending_exits.keys()):
                if t in positions and arr[t]["has_bar"][i]:
                    cash, trade = self._close_position(
                        positions[t], arr[t]["open"][i], int(arr[t]["bar_number"][i]),
                        date, pending_exits[t], cash
                    )
                    trades.append(trade)
                    trade_bar.append(i)
                    del positions[t]
                    del pending_exits[t]

            # --- 2. Fill scheduled ENTRIES at this bar's open -------------------
            # Equity/buying-power computed from previous closes (no look-ahead).
            long_value = _long_value(marks_prev)
            equity_open = cash + long_value
            cash = self._fill_entries(
                candidates=[
                    (t, m) for t, m in pending_entries.items()
                    if arr[t]["has_bar"][i] and t not in positions
                ],
                price_key="open", i=i, date=date, arr=arr,
                cash=cash, equity_base=equity_open, long_value=long_value,
                positions=positions, unlimited=unlimited, limit=is_limit,
            )
            # Expire any pending entry whose fill bar has arrived (filled or skipped).
            for t in list(pending_entries.keys()):
                if arr[t]["has_bar"][i]:
                    del pending_entries[t]

            # --- 2b. Intrabar hard stops at each position's signal-candle low --
            if cfg.exits.use_signal_low_stop:
                for t, pos in list(positions.items()):
                    if not arr[t]["has_bar"][i] or t in pending_exits:
                        continue
                    if (pos.entered_at_close
                            and pos.entry_index == int(arr[t]["bar_number"][i])):
                        continue  # no post-entry low on a same-bar close entry
                    stop = pos.signal_low
                    low_i = arr[t]["low"][i]
                    if np.isnan(stop) or np.isnan(low_i) or low_i > stop:
                        continue
                    open_i = arr[t]["open"][i]
                    fill_raw = open_i if (not np.isnan(open_i) and open_i < stop) else stop
                    cash, trade = self._close_position(
                        pos, fill_raw, int(arr[t]["bar_number"][i]), date,
                        "Signal-low stop", cash
                    )
                    trades.append(trade)
                    trade_bar.append(i)
                    del positions[t]

            # --- 3. Evaluate EXITS at this bar's close --------------------------
            for t, pos in list(positions.items()):
                if not arr[t]["has_bar"][i] or t in pending_exits:
                    continue
                if (pos.entered_at_close
                        and pos.entry_index == int(arr[t]["bar_number"][i])):
                    continue  # can't exit the same close we entered on
                reason = self._exit_reason(pos, i, arr[t])
                if reason is None:
                    continue
                if cfg.exit_execution == Execution.SIGNAL_CLOSE:
                    cash, trade = self._close_position(
                        pos, arr[t]["close"][i], int(arr[t]["bar_number"][i]),
                        date, reason, cash
                    )
                    trades.append(trade)
                    trade_bar.append(i)
                    del positions[t]
                else:
                    pending_exits[t] = reason

            # --- 4. Evaluate ENTRY signals at this bar's close ------------------
            close_signals = []
            allow_new_entries = bool(breadth_eligible[i])
            for t in tickers:
                if not arr[t]["has_bar"][i] or t in positions or t in pending_entries:
                    continue
                if not arr[t]["signal"][i]:
                    continue
                if not allow_new_entries:
                    continue
                sig_range = float(arr[t]["high"][i] - arr[t]["low"][i])
                sig_body_low = min(float(arr[t]["open"][i]), float(arr[t]["close"][i]))
                sig_body_pct = ((float(arr[t]["high"][i]) - sig_body_low) / sig_range
                                if sig_range > 0 else float("nan"))
                sig_atr_mult = float(arr[t]["atr_mult"][i])
                meta = {
                    "signal_date": date,
                    "signal_close": arr[t]["close"][i],
                    "signal_low": float(arr[t]["low"][i]),
                    "signal_range": sig_range,
                    "signal_body_percentile": sig_body_pct,
                    "signal_atr_mult": sig_atr_mult,
                    "rsi_at_signal": float(arr[t]["rsi"][i]),
                    "rank_trend": float(arr[t]["rank_trend"][i]),
                    "quality_trend": float(arr[t]["quality_trend"][i]),
                    "signal_range_pct": (
                        sig_range / float(arr[t]["close"][i])
                        if float(arr[t]["close"][i]) > 0 else float("nan")
                    ),
                    "rank_volatility": float(arr[t]["rank_volatility"][i]),
                    "rank_relative_volume": float(arr[t]["rank_relative_volume"][i]),
                    "pattern": str(arr[t]["pattern"][i]),
                }
                if cfg.entry_execution == Execution.SIGNAL_CLOSE:
                    close_signals.append((t, meta))
                else:  # NEXT_OPEN (default): schedule for the next available open
                    pending_entries[t] = meta

            if close_signals:
                marks_now = {t: arr[t]["mark"][i] for t in tickers}
                long_value_c = _long_value(marks_now)
                equity_close = cash + long_value_c
                cash = self._fill_entries(
                    candidates=close_signals, price_key="close", i=i, date=date, arr=arr,
                    cash=cash, equity_base=equity_close, long_value=long_value_c,
                    positions=positions, unlimited=unlimited,
                )

            # A delisted/short-history asset must not remain marked at a stale
            # close until some other ticker's final date. Liquidate it on its own
            # final real candle, exactly as the single-asset engine does.
            for t, pos in list(positions.items()):
                if i != arr[t]["last_bar"]:
                    continue
                local_i = int(arr[t]["bar_number"][i])
                if not (pos.entered_at_close and pos.entry_index == local_i):
                    high_i = arr[t]["high"][i]
                    if not np.isnan(high_i):
                        pos.max_high_seen = max(pos.max_high_seen, float(high_i))
                cash, trade = self._close_position(
                    pos, arr[t]["close"][i], local_i,
                    date, "End of data", cash,
                )
                trades.append(trade)
                trade_bar.append(i)
                del positions[t]
                pending_exits.pop(t, None)
                end_of_data_closes += 1

            # --- 5. Mark-to-market the whole portfolio at this bar's close ------
            long_now = 0.0
            for t, p in positions.items():
                mk = arr[t]["mark"][i]
                if not np.isnan(mk):
                    long_now += p.shares * mk
                    marks_prev[t] = mk  # roll forward last known close
                # Track peak high for MFE (skip entry bar for SIGNAL_CLOSE entries).
                if arr[t]["has_bar"][i]:
                    local_i = int(arr[t]["bar_number"][i])
                    if not (p.entered_at_close and p.entry_index == local_i):
                        high_i = arr[t]["high"][i]
                        if not np.isnan(high_i):
                            p.max_high_seen = max(p.max_high_seen, float(high_i))
            equity[i] = cash + long_now
            n_open[i] = len(positions)
            gross_exposure[i] = (long_now / equity[i]) if equity[i] else 0.0

            # Backfill equity_after on trades closed during this bar.
            for k in range(len(trades) - 1, -1, -1):
                if trade_bar[k] == i:
                    trades[k].equity_after = equity[i]
                else:
                    break

        # --- Force-close anything still open at the final bar -------------------
        if positions:
            last = n - 1
            forced_count = len(positions)
            for t, pos in list(positions.items()):
                local_i = int(arr[t]["bar_number"][last])
                cash, trade = self._close_position(
                    pos, arr[t]["mark"][last], local_i, union[last], "End of data", cash
                )
                trade.equity_after = cash
                trades.append(trade)
                del positions[t]
            equity[last] = cash
            n_open[last] = 0
            gross_exposure[last] = 0.0
            end_of_data_closes += forced_count

        if end_of_data_closes:
            self.warnings.append(
                f"{end_of_data_closes} position(s) were still open at the end of the "
                "data available for their asset and were closed at that asset's final candle close for "
                "accounting purposes."
            )

        equity_series = pd.Series(equity, index=union, name="equity")
        positions_series = pd.Series(n_open, index=union, name="open_positions")
        exposure_series = pd.Series(gross_exposure, index=union, name="gross_exposure")
        breadth_series = pd.Series(breadth, index=union, name="market_breadth")
        trades_df = _trades_to_frame(trades)
        trades_df = add_period_mfe(trades_df, self.data_by_ticker)

        # Under unlimited margin a leveraged basket can wipe out the account.
        if n and float(np.nanmin(equity)) <= 0.0:
            self.warnings.append(
                "Portfolio equity reached zero or went negative — risk of ruin under "
                "unlimited-margin sizing. Returns/risk metrics beyond that point are unreliable."
            )

        return PortfolioResult(
            trades=trades_df,
            equity_curve=equity_series,
            positions_open=positions_series,
            exposure=exposure_series,
            breadth=breadth_series,
            frames=frames,
            config=cfg,
            portfolio=pf,
            time_in_market=float((n_open > 0).mean()) if n else 0.0,
            avg_positions=float(n_open.mean()) if n else 0.0,
            max_concurrent=int(n_open.max()) if n else 0,
            warnings=self.warnings,
            financing_costs=total_financing,
            dividend_income=total_dividends,
        )

    # ---------------------------------------------------------- entry filling
    def _fill_entries(self, candidates, price_key, i, date, arr, cash,
                      equity_base, long_value, positions, unlimited, limit=False) -> float:
        """Fill ranked entry candidates; return new cash.

        Candidates are ranked with signal-close information only.  At most
        ``max_entries_per_date`` are considered for this fill date.

        * PERCENT mode: each position is ``pct_per_trade`` percent of ``equity_base``
          (notional), filled only while total long exposure stays within
          ``equity_base * leverage`` and the optional ``max_positions`` cap.
        * FULL_EQUITY mode: each position is 100% of ``equity_base`` (the whole
          account), with NO buying-power cap and NO position cap — every signal is
          filled and cash may go arbitrarily negative (unlimited margin).
        """
        pf = self.portfolio
        full_equity = pf.sizing_mode == PortfolioSizing.FULL_EQUITY

        if pf.use_trade_quality_filter and candidates:
            range_pct = pd.Series(
                {ticker: meta.get("signal_range_pct", np.nan) for ticker, meta in candidates},
                dtype=float,
            )
            range_rank = range_pct.rank(method="average", pct=True)
            candidates = [
                (ticker, meta) for ticker, meta in candidates
                if np.isfinite(float(meta.get("quality_trend", np.nan)))
                and float(meta["quality_trend"]) >= pf.quality_min_trend_pct / 100.0
                and float(range_rank.get(ticker, np.nan))
                <= pf.quality_max_range_rank_pct / 100.0
            ]
        ranking = pf.entry_ranking
        if not isinstance(ranking, PortfolioEntryRanking):
            ranking = PortfolioEntryRanking(ranking)
        rank_fields = {
            PortfolioEntryRanking.LOWEST_RSI: ("rsi_at_signal", False),
            PortfolioEntryRanking.LARGEST_HAMMER_ATR: ("signal_atr_mult", True),
            PortfolioEntryRanking.HIGHEST_RELATIVE_VOLUME: ("rank_relative_volume", True),
            PortfolioEntryRanking.STRONGEST_TREND: ("rank_trend", True),
            PortfolioEntryRanking.HIGHEST_VOLATILITY: ("rank_volatility", True),
        }
        field, descending = rank_fields[ranking]

        def _rank_key(item):
            value = float(item[1].get(field, np.nan))
            missing = not np.isfinite(value)
            ordered = -value if descending and not missing else value
            return missing, ordered, item[0]

        candidates = sorted(candidates, key=_rank_key)
        if pf.max_entries_per_date > 0:
            candidates = candidates[:pf.max_entries_per_date]
        buying_power = equity_base * pf.leverage
        notional_target = equity_base if full_equity else equity_base * (pf.pct_per_trade / 100.0)

        for t, meta in candidates:
            # Determine the fill price first (a limit order may not fill at all).
            if limit:
                limit_px = meta["signal_close"]
                op = arr[t]["open"][i]
                lo = arr[t]["low"][i]
                if np.isnan(op) or op <= 0:
                    continue
                if op <= limit_px:
                    price = op            # case 1: gap below the limit
                elif (not np.isnan(lo)) and lo <= limit_px:
                    price = limit_px      # case 2: retraced to the limit
                else:
                    continue              # case 3: limit never reached -> no fill
                # limit order: fills at the limit or better, no slippage
            else:
                raw = arr[t][price_key][i]
                if np.isnan(raw) or raw <= 0:
                    continue
                price = self._buy_price(raw)

            if not full_equity and not unlimited and len(positions) >= pf.max_positions:
                break
            if notional_target <= 0:
                break  # no equity left to deploy (e.g. ruin under unlimited margin)
            shares = notional_target / price
            if not pf.allow_fractional:
                shares = float(np.floor(shares))
            # PERCENT mode: notional *plus entry commission* consumes buying
            # power. This also prevents a 1x/cash portfolio from borrowing just
            # enough to pay fees. Scale down instead of needlessly missing the
            # signal when fractional (or fewer whole) shares fit.
            if not full_equity:
                capacity = buying_power - long_value
                for _ in range(5):
                    notional = shares * price
                    total_cost = notional + self._commission(shares, notional)
                    if total_cost <= capacity + 1e-9:
                        break
                    shares *= capacity / total_cost if total_cost > 0 and capacity > 0 else 0.0
                    if not pf.allow_fractional:
                        shares = float(np.floor(shares))
            if shares <= 0:
                continue
            notional = shares * price
            commission = self._commission(shares, notional)
            if not full_equity and notional + commission > capacity + 1e-9:
                continue
            cash -= notional + commission
            long_value += notional + commission
            positions[t] = _Position(
                ticker=t,
                shares=shares,
                entry_price=price,
                entry_index=int(arr[t]["bar_number"][i]),
                entry_date=date,
                entry_commission=commission,
                signal_date=meta["signal_date"],
                signal_close=meta["signal_close"],
                signal_low=meta["signal_low"],
                signal_range=meta["signal_range"],
                signal_body_percentile=meta["signal_body_percentile"],
                signal_atr_mult=meta["signal_atr_mult"],
                rsi_at_signal=meta["rsi_at_signal"],
                pattern=meta["pattern"],
                entered_at_close=(price_key == "close"),
                max_high_seen=price,
            )
        return cash


def _trades_to_frame(trades: List[Trade]) -> pd.DataFrame:
    columns = [
        "ticker", "signal_date", "signal_close", "rsi_at_signal", "signal_range",
        "signal_body_percentile", "signal_atr_mult", "pattern",
        "entry_date", "entry_price", "exit_date", "exit_price", "exit_reason",
        "bars_held", "gross_return", "net_return", "pnl", "equity_after", "mfe",
    ]
    if not trades:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame([t.__dict__ for t in trades])[columns]
    return df.sort_values("exit_date").reset_index(drop=True)
