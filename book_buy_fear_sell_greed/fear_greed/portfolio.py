"""Backtest multiativo com capital compartilhado e marcação diária a mercado."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .catalog import STRATEGIES
from .engine import (
    StrategyConfig,
    _features,
    _metrics,
    _next_bar_price,
    _order_commission,
    _params,
    _signals,
    _weights,
)


@dataclass(slots=True)
class PortfolioConfig:
    initial_capital: float = 100_000.0
    position_size_pct: float = 10.0
    max_gross_pct: float = 100.0
    max_positions: int = 10
    leverage: float = 1.0


@dataclass(slots=True)
class PortfolioResult:
    trades: pd.DataFrame
    equity: pd.DataFrame
    decisions: pd.DataFrame
    metrics: dict[str, float]


_CLOSE_SIGNAL_STRATEGIES = {"rsi_powerzones", "vol_panics", "vxx_trend", "tps_long", "tps_short"}


def _strategy_weights(config: StrategyConfig) -> list[float]:
    weights = [1.0] if config.strategy in {"crash", "vxx_trend", "trading_new_highs", "terror_gaps"} else _weights(config.scale_scheme)
    if config.strategy == "rsi_powerzones" and len(weights) > 2:
        return [0.5, 0.5]
    return weights


def _signal_strength(strategy: str, bar: pd.Series, params: dict[str, float]) -> float:
    """Maior valor significa sinal mais extremo dentro da mesma estratégia."""
    if strategy in {"rsi_powerzones", "vol_panics"}:
        value = float(bar.RSI4)
    elif strategy in {"tps_long", "tps_short"}:
        value = float(bar.RSI2)
    elif strategy in {"crash", "trading_new_highs", "terror_gaps"}:
        value = float(bar.CRSI)
    else:
        return 0.0
    if strategy in {"rsi_powerzones", "tps_long", "trading_new_highs", "terror_gaps"}:
        return params["entry"] - value
    return value - params.get("entry", value)


def run_portfolio(
    datasets: dict[str, pd.DataFrame],
    strategy_config: StrategyConfig,
    portfolio_config: PortfolioConfig,
) -> PortfolioResult:
    """Executa uma estratégia em vários ativos disputando uma única carteira.

    O tamanho de cada posição usa o patrimônio do fechamento anterior. A posição
    inteira é reservada na primeira parcela para que o scale-in futuro não exceda
    deliberadamente o limite. Movimentos de mercado ainda podem elevar a exposição
    real acima do limite, sem liquidação artificial.
    """
    frames = {ticker: _features(frame) for ticker, frame in datasets.items() if not frame.empty}
    signals = {ticker: _signals(frame, ticker, strategy_config) for ticker, frame in frames.items()}
    if not frames:
        empty = pd.DataFrame()
        return PortfolioResult(empty, empty, empty, {})

    calendar = pd.DatetimeIndex(sorted(set().union(*(frame.index for frame in frames.values()))))
    closes = pd.DataFrame({ticker: frame.Close.reindex(calendar).ffill() for ticker, frame in frames.items()}, index=calendar)
    weights = _strategy_weights(strategy_config)
    params = _params(strategy_config)
    slip = strategy_config.slippage_bps / 10_000
    positions: dict[str, dict[str, Any]] = {}
    trades: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    realized_gross = 0.0
    costs = 0.0
    cumulative_traded_notional = 0.0
    previous_equity = portfolio_config.initial_capital

    def marked_equity(date: pd.Timestamp) -> tuple[float, float]:
        unrealized = 0.0
        gross_market_value = 0.0
        for ticker, position in positions.items():
            mark = closes.at[date, ticker]
            if pd.isna(mark):
                continue
            side = 1 if position["direction"] == "long" else -1
            for qty, entry in zip(position["quantities"], position["prices"]):
                unrealized += qty * (float(mark) - entry) * side
                gross_market_value += abs(qty * float(mark))
        return portfolio_config.initial_capital + realized_gross + unrealized - costs, gross_market_value

    for date in calendar:
        # Saídas são processadas primeiro e liberam exposição para os sinais do dia.
        for ticker in sorted(list(positions)):
            frame = frames[ticker]
            if date not in frame.index:
                continue
            i = frame.index.get_loc(date)
            if not isinstance(i, (int, np.integer)) or i == 0 or not bool(signals[ticker].iloc[i - 1].exit):
                continue
            position = positions.pop(ticker)
            direction = position["direction"]
            px = float(frame.iloc[i].Open) * (1 - slip if direction == "long" else 1 + slip)
            side = 1 if direction == "long" else -1
            gross_pnl = sum(qty * (px - entry) * side for qty, entry in zip(position["quantities"], position["prices"]))
            total_qty = sum(position["quantities"])
            exit_cost = _order_commission(strategy_config, total_qty, total_qty * px)
            cumulative_traded_notional += total_qty * px
            realized_gross += gross_pnl
            costs += exit_cost
            invested = sum(position["notionals"])
            net_pnl = gross_pnl - sum(position["commissions"]) - exit_cost
            trades.append({
                "ticker": ticker,
                "strategy": STRATEGIES[strategy_config.strategy]["name"],
                "signal_date": position["signal_date"],
                "entry_date": position["dates"][0],
                "exit_signal_date": frame.index[i - 1],
                "exit_date": date,
                "direction": direction,
                "execution_model": position["execution_model"],
                "tranches": len(position["prices"]),
                "tranche_dates": position["dates"].copy(),
                "tranche_prices": position["prices"].copy(),
                "tranche_weights": position["weights"].copy(),
                "tranche_notionals": position["notionals"].copy(),
                "exit_notional": total_qty * px,
                "invested_fraction": invested / position["target_notional"],
                "avg_entry": float(np.average(position["prices"], weights=position["quantities"])),
                "exit_price": px,
                "gross_return": gross_pnl / invested if invested else 0.0,
                "net_return": net_pnl / invested if invested else 0.0,
                "portfolio_return": net_pnl / position["equity_at_entry"],
                "commission": sum(position["commissions"]) + exit_cost,
                "bars_held": int(i - frame.index.get_loc(position["dates"][0])),
                "pnl": net_pnl,
                "forced_exit": False,
            })

        # Scale-ins têm prioridade porque a posição-alvo completa já foi reservada.
        for ticker in sorted(positions):
            frame = frames[ticker]
            if date not in frame.index:
                continue
            i = frame.index.get_loc(date)
            position = positions[ticker]
            if not isinstance(i, (int, np.integer)) or i == 0 or len(position["prices"]) >= len(weights):
                continue
            previous_signal = signals[ticker].iloc[i - 1]
            previous_bar, bar = frame.iloc[i - 1], frame.iloc[i]
            if not bool(previous_signal.add):
                continue
            favorable = previous_bar.Close < position["prices"][-1] if position["direction"] == "long" else previous_bar.Close > position["prices"][-1]
            if not favorable:
                continue
            px = _next_bar_price(position["direction"], strategy_config.execution_model, previous_bar, bar, slip)
            if px is None:
                decisions.append({"date": date, "ticker": ticker, "decision": "não executado", "reason": "parcela sem rompimento/retorno"})
                continue
            weight = weights[len(position["prices"])]
            notional = position["target_notional"] * weight
            qty = notional / px
            commission = _order_commission(strategy_config, qty, notional)
            costs += commission
            cumulative_traded_notional += notional
            position["dates"].append(date)
            position["prices"].append(px)
            position["weights"].append(weight)
            position["notionals"].append(notional)
            position["quantities"].append(qty)
            position["commissions"].append(commission)
            decisions.append({"date": date, "ticker": ticker, "decision": "executado", "reason": f"parcela {len(position['prices'])}"})

        candidates: list[dict[str, Any]] = []
        for ticker, frame in frames.items():
            if ticker in positions or date not in frame.index:
                continue
            i = frame.index.get_loc(date)
            if not isinstance(i, (int, np.integer)):
                continue
            signal, bar = signals[ticker].iloc[i], frame.iloc[i]
            direction = str(signal.direction)
            px: float | None = None
            signal_date = date
            strength_bar = bar
            execution_model = strategy_config.execution_model
            if strategy_config.strategy in _CLOSE_SIGNAL_STRATEGIES:
                if i == 0 or not bool(signals[ticker].iloc[i - 1].entry):
                    continue
                previous_bar = frame.iloc[i - 1]
                px = _next_bar_price(direction, strategy_config.execution_model, previous_bar, bar, slip)
                signal_date = frame.index[i - 1]
                strength_bar = previous_bar
            elif bool(signal.entry):
                limit = float(signal["limit"])
                filled = bar.High >= limit if direction == "short" else bar.Low <= limit
                if filled:
                    px = limit
                signal_date = frame.index[i - 1] if strategy_config.strategy in {"crash", "trading_new_highs"} and i > 0 else date
                strength_bar = frame.iloc[i - 1] if strategy_config.strategy in {"crash", "trading_new_highs"} and i > 0 else bar
                execution_model = "Limite da estratégia"
            else:
                continue
            if px is None:
                decisions.append({"date": date, "ticker": ticker, "decision": "não executado", "reason": "ordem DAY sem fill"})
                continue
            candidates.append({"ticker": ticker, "price": px, "direction": direction, "signal_date": signal_date, "strength": _signal_strength(strategy_config.strategy, strength_bar, params), "execution_model": execution_model})

        candidates.sort(key=lambda item: (-item["strength"], item["ticker"]))
        for candidate in candidates:
            equity_now, _ = marked_equity(date)
            sizing_equity = max(previous_equity, 0.0)
            target_notional = sizing_equity * portfolio_config.position_size_pct / 100 * portfolio_config.leverage
            reserved = sum(position["target_notional"] for position in positions.values())
            max_reserved = max(equity_now, 0.0) * portfolio_config.max_gross_pct / 100 * portfolio_config.leverage
            if len(positions) >= portfolio_config.max_positions:
                decisions.append({"date": date, "ticker": candidate["ticker"], "decision": "rejeitado", "reason": "máximo de posições", "strength": candidate["strength"]})
                continue
            if target_notional <= 0 or reserved + target_notional > max_reserved + 1e-9:
                decisions.append({"date": date, "ticker": candidate["ticker"], "decision": "rejeitado", "reason": "limite de exposição reservada", "strength": candidate["strength"]})
                continue
            weight = weights[0]
            notional = target_notional * weight
            qty = notional / candidate["price"]
            commission = _order_commission(strategy_config, qty, notional)
            costs += commission
            cumulative_traded_notional += notional
            ticker = candidate["ticker"]
            positions[ticker] = {
                "signal_date": candidate["signal_date"],
                "direction": candidate["direction"],
                "execution_model": candidate["execution_model"],
                "target_notional": target_notional,
                "equity_at_entry": sizing_equity,
                "dates": [date],
                "prices": [candidate["price"]],
                "weights": [weight],
                "notionals": [notional],
                "quantities": [qty],
                "commissions": [commission],
            }
            decisions.append({"date": date, "ticker": ticker, "decision": "executado", "reason": "nova posição", "strength": candidate["strength"], "rank": candidates.index(candidate) + 1})

        equity_now, gross_market_value = marked_equity(date)
        reserved = sum(position["target_notional"] for position in positions.values())
        daily.append({
            "date": date,
            "equity": equity_now,
            "gross_exposure": gross_market_value,
            "gross_exposure_pct": gross_market_value / equity_now * 100 if equity_now else np.nan,
            "reserved_exposure": reserved,
            "reserved_exposure_pct": reserved / equity_now * 100 if equity_now else np.nan,
            "open_positions": len(positions),
            "configured_leverage": portfolio_config.leverage,
            "effective_max_gross_pct": portfolio_config.max_gross_pct * portfolio_config.leverage,
            "realized_gross_pnl": realized_gross,
            "costs": costs,
            "cumulative_traded_notional": cumulative_traded_notional,
        })
        previous_equity = equity_now

    if positions and strategy_config.close_open_positions_at_end:
        final_date = calendar[-1]
        for ticker in sorted(list(positions)):
            position = positions.pop(ticker)
            frame = frames[ticker]
            last_bar_date = frame.index[frame.index <= final_date][-1]
            px = float(frame.loc[last_bar_date, "Close"]) * (1 - slip if position["direction"] == "long" else 1 + slip)
            side = 1 if position["direction"] == "long" else -1
            gross_pnl = sum(qty * (px - entry) * side for qty, entry in zip(position["quantities"], position["prices"]))
            total_qty = sum(position["quantities"])
            exit_cost = _order_commission(strategy_config, total_qty, total_qty * px)
            cumulative_traded_notional += total_qty * px
            realized_gross += gross_pnl
            costs += exit_cost
            invested = sum(position["notionals"])
            net_pnl = gross_pnl - sum(position["commissions"]) - exit_cost
            trades.append({
                "ticker": ticker,
                "strategy": STRATEGIES[strategy_config.strategy]["name"],
                "signal_date": position["signal_date"],
                "entry_date": position["dates"][0],
                "exit_signal_date": pd.NaT,
                "exit_date": last_bar_date,
                "direction": position["direction"],
                "execution_model": position["execution_model"],
                "tranches": len(position["prices"]),
                "tranche_dates": position["dates"].copy(),
                "tranche_prices": position["prices"].copy(),
                "tranche_weights": position["weights"].copy(),
                "tranche_notionals": position["notionals"].copy(),
                "exit_notional": total_qty * px,
                "invested_fraction": invested / position["target_notional"],
                "avg_entry": float(np.average(position["prices"], weights=position["quantities"])),
                "exit_price": px,
                "gross_return": gross_pnl / invested if invested else 0.0,
                "net_return": net_pnl / invested if invested else 0.0,
                "portfolio_return": net_pnl / position["equity_at_entry"],
                "commission": sum(position["commissions"]) + exit_cost,
                "bars_held": int(frame.index.get_loc(last_bar_date) - frame.index.get_loc(position["dates"][0])),
                "pnl": net_pnl,
                "forced_exit": True,
            })
        daily[-1].update({
            "equity": portfolio_config.initial_capital + realized_gross - costs,
            "gross_exposure": 0.0,
            "gross_exposure_pct": 0.0,
            "reserved_exposure": 0.0,
            "reserved_exposure_pct": 0.0,
            "open_positions": 0,
            "configured_leverage": portfolio_config.leverage,
            "effective_max_gross_pct": portfolio_config.max_gross_pct * portfolio_config.leverage,
            "realized_gross_pnl": realized_gross,
            "costs": costs,
            "cumulative_traded_notional": cumulative_traded_notional,
        })

    equity = pd.DataFrame(daily).set_index("date")
    trade_frame = pd.DataFrame(trades)
    decision_frame = pd.DataFrame(decisions)
    metrics = _metrics(trade_frame, equity[["equity"]], portfolio_config.initial_capital)
    metrics["max_gross_exposure"] = float(equity.gross_exposure_pct.max()) if not equity.empty else 0.0
    metrics["avg_gross_exposure"] = float(equity.gross_exposure_pct.mean()) if not equity.empty else 0.0
    metrics["open_positions_end"] = float(len(positions))
    return PortfolioResult(trade_frame, equity, decision_frame, metrics)
