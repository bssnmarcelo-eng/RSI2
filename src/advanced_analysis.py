"""Statistical diagnostics for strategy and benchmark result series."""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def buy_and_hold_equity(close: pd.Series, initial_capital: float) -> pd.Series:
    """Normalized buy-and-hold benchmark aligned to a clean price series."""
    clean = close.astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    clean = clean[clean > 0]
    if clean.empty:
        return pd.Series(dtype=float, name="benchmark")
    result = initial_capital * clean / float(clean.iloc[0])
    return result.rename("benchmark")


def compare_with_benchmark(equity: pd.Series, benchmark: pd.Series) -> dict:
    """Return comparable strategy/benchmark returns and active statistics."""
    aligned = pd.concat([equity.rename("strategy"), benchmark.rename("benchmark")], axis=1).dropna()
    if len(aligned) < 2:
        return {}
    strategy_return = float(aligned["strategy"].iloc[-1] / aligned["strategy"].iloc[0] - 1.0)
    benchmark_return = float(aligned["benchmark"].iloc[-1] / aligned["benchmark"].iloc[0] - 1.0)
    sr = aligned["strategy"].pct_change().dropna()
    br = aligned["benchmark"].pct_change().dropna()
    active = sr - br
    tracking_error = float(active.std(ddof=1)) if len(active) > 1 else 0.0
    information_ratio = float(active.mean() / tracking_error) if tracking_error > 0 else 0.0
    return {
        "strategy_return": strategy_return,
        "benchmark_return": benchmark_return,
        "excess_return": strategy_return - benchmark_return,
        "tracking_error_per_bar": tracking_error,
        "information_ratio_per_bar": information_ratio,
    }


def monte_carlo_trades(
    trades: pd.DataFrame,
    initial_capital: float = 100_000.0,
    simulations: int = 2_000,
    seed: Optional[int] = 42,
) -> pd.DataFrame:
    """Bootstrap trade returns and report terminal wealth/max drawdown paths.

    Sampling with replacement estimates sequence and sampling uncertainty without
    claiming to forecast market regimes. Results are deterministic by default.
    """
    if trades.empty or "net_return" not in trades:
        return pd.DataFrame(columns=["final_equity", "total_return", "max_drawdown"])
    returns = trades["net_return"].astype(float).replace([np.inf, -np.inf], np.nan).dropna().to_numpy()
    if not len(returns) or simulations <= 0:
        return pd.DataFrame(columns=["final_equity", "total_return", "max_drawdown"])
    rng = np.random.default_rng(seed)
    draws = rng.choice(returns, size=(int(simulations), len(returns)), replace=True)
    paths = initial_capital * np.cumprod(1.0 + draws, axis=1)
    paths = np.concatenate([np.full((len(paths), 1), initial_capital), paths], axis=1)
    peaks = np.maximum.accumulate(paths, axis=1)
    drawdowns = np.divide(paths, peaks, out=np.ones_like(paths), where=peaks != 0) - 1.0
    final = paths[:, -1]
    return pd.DataFrame({
        "final_equity": final,
        "total_return": final / initial_capital - 1.0,
        "max_drawdown": drawdowns.min(axis=1),
    })


def monte_carlo_summary(simulations: pd.DataFrame) -> dict:
    """Compact percentiles and probability of loss for bootstrap simulations."""
    if simulations.empty:
        return {}
    return {
        "probability_of_loss": float((simulations["total_return"] < 0).mean()),
        "return_p05": float(simulations["total_return"].quantile(0.05)),
        "return_median": float(simulations["total_return"].median()),
        "return_p95": float(simulations["total_return"].quantile(0.95)),
        "drawdown_p05": float(simulations["max_drawdown"].quantile(0.05)),
    }
