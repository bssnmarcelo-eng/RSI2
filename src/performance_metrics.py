"""Performance and risk metrics derived from the equity curve and trade log."""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from .utils import periods_per_year, safe_div, years_between


def _max_drawdown(equity: pd.Series) -> float:
    """Maximum peak-to-trough drawdown as a negative fraction (e.g. -0.25)."""
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(drawdown.min())


def drawdown_series(equity: pd.Series) -> pd.Series:
    """Drawdown at each point as a fraction (<= 0)."""
    if equity.empty:
        return equity
    return equity / equity.cummax() - 1.0


def ulcer_index(equity: pd.Series) -> float:
    """Root-mean-square drawdown, expressed as a positive fraction."""
    if equity.empty:
        return 0.0
    dd = drawdown_series(equity).clip(upper=0.0)
    return float(np.sqrt(np.mean(np.square(dd))))


def compute_metrics(
    equity: pd.Series,
    trades: pd.DataFrame,
    initial_capital: float,
    n_bars: int,
) -> Dict[str, float]:
    """Return a dictionary of all headline performance metrics.

    Sharpe / Sortino assume a zero risk-free rate and are annualised using a
    frequency inferred from the equity index (works for daily and intraday data).
    """
    metrics: Dict[str, float] = {}
    final_equity = float(equity.iloc[-1]) if len(equity) else initial_capital

    # --- Returns / growth ---
    total_return = safe_div(final_equity - initial_capital, initial_capital)
    yrs = years_between(equity.index[0], equity.index[-1]) if len(equity) else 1.0
    cagr = (final_equity / initial_capital) ** (1.0 / yrs) - 1.0 if initial_capital > 0 and final_equity > 0 else 0.0

    metrics["final_equity"] = final_equity
    metrics["total_return"] = total_return
    metrics["cagr"] = cagr

    # --- Risk-adjusted (bar-level equity returns) ---
    bar_returns = equity.pct_change().dropna()
    ppy = periods_per_year(equity.index)
    if len(bar_returns) > 1 and bar_returns.std(ddof=1) > 0:
        sharpe = safe_div(bar_returns.mean(), bar_returns.std(ddof=1)) * np.sqrt(ppy)
    else:
        sharpe = 0.0
    downside = bar_returns[bar_returns < 0]
    if len(downside) > 1 and downside.std(ddof=1) > 0:
        sortino = safe_div(bar_returns.mean(), downside.std(ddof=1)) * np.sqrt(ppy)
    else:
        sortino = 0.0
    metrics["sharpe"] = float(sharpe)
    metrics["sortino"] = float(sortino)
    metrics["max_drawdown"] = _max_drawdown(equity)
    metrics["volatility"] = float(bar_returns.std(ddof=1) * np.sqrt(ppy)) if len(bar_returns) > 1 else 0.0
    metrics["ulcer_index"] = ulcer_index(equity)
    metrics["calmar"] = safe_div(cagr, abs(metrics["max_drawdown"]))

    # --- Trade statistics ---
    n_trades = len(trades)
    metrics["num_trades"] = n_trades
    if n_trades == 0:
        metrics.update({
            "win_rate": 0.0, "avg_gain": 0.0, "avg_loss": 0.0, "profit_factor": 0.0,
            "expectancy": 0.0, "avg_holding": 0.0, "best_trade": 0.0, "worst_trade": 0.0,
            "exposure": 0.0,
        })
        return metrics

    net_returns = trades["net_return"]
    pnl = trades["pnl"]
    wins = net_returns[net_returns > 0]
    losses = net_returns[net_returns <= 0]

    metrics["win_rate"] = safe_div(len(wins), n_trades)
    metrics["avg_gain"] = float(wins.mean()) if len(wins) else 0.0
    metrics["avg_loss"] = float(losses.mean()) if len(losses) else 0.0

    gross_profit = pnl[pnl > 0].sum()
    gross_loss = abs(pnl[pnl < 0].sum())
    metrics["profit_factor"] = safe_div(gross_profit, gross_loss, default=float("inf") if gross_profit > 0 else 0.0)

    metrics["expectancy"] = float(pnl.mean())            # average $ P&L per trade
    metrics["expectancy_return"] = float(net_returns.mean())  # average % per trade
    metrics["avg_holding"] = float(trades["bars_held"].mean())
    metrics["best_trade"] = float(net_returns.max())
    metrics["worst_trade"] = float(net_returns.min())

    # --- Exposure: fraction of bars spent holding a position ---
    bars_in_market = int(trades["bars_held"].clip(lower=0).sum())
    metrics["exposure"] = safe_div(bars_in_market, n_bars) if n_bars else 0.0

    return metrics


def monthly_returns_table(equity: pd.Series) -> pd.DataFrame:
    """Pivot of monthly returns (rows = year, cols = month) as fractions."""
    if equity.empty:
        return pd.DataFrame()
    monthly = equity.resample("ME").last().dropna()
    returns = monthly.pct_change()
    # The first observed value is the available base for the partial first
    # month; without this assignment pct_change silently discards that month.
    returns.iloc[0] = monthly.iloc[0] / float(equity.iloc[0]) - 1.0
    monthly = returns.dropna()
    if monthly.empty:
        return pd.DataFrame()
    table = pd.DataFrame({
        "year": monthly.index.year,
        "month": monthly.index.month,
        "ret": monthly.values,
    })
    return table.pivot(index="year", columns="month", values="ret")


def yearly_returns(equity: pd.Series) -> pd.Series:
    """Calendar-year returns as fractions."""
    if equity.empty:
        return pd.Series(dtype=float)
    yearly_values = equity.resample("YE").last().dropna()
    returns = yearly_values.pct_change()
    returns.iloc[0] = yearly_values.iloc[0] / float(equity.iloc[0]) - 1.0
    returns = returns.dropna()
    returns.index = returns.index.year
    return returns
