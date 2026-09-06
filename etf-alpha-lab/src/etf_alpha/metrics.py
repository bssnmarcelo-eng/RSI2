from __future__ import annotations

import numpy as np
import pandas as pd


def performance_metrics(equity: pd.Series, benchmark: pd.Series | None = None) -> dict[str, float]:
    returns = equity.pct_change().dropna()
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1 / 252)
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
    drawdown = equity / equity.cummax() - 1
    downside = returns.where(returns < 0, 0).std() * np.sqrt(252)
    result = {
        "total_return": float(equity.iloc[-1] / equity.iloc[0] - 1),
        "cagr": float(cagr),
        "annual_volatility": float(returns.std() * np.sqrt(252)),
        "sharpe_0rf": float(returns.mean() / returns.std() * np.sqrt(252)) if returns.std() else 0.0,
        "sortino_0rf": float(returns.mean() * 252 / downside) if downside else 0.0,
        "max_drawdown": float(drawdown.min()),
        "calmar": float(cagr / abs(drawdown.min())) if drawdown.min() else 0.0,
    }
    if benchmark is not None:
        aligned = pd.concat([returns, benchmark.pct_change()], axis=1, sort=False).dropna()
        active = aligned.iloc[:, 0] - aligned.iloc[:, 1]
        result["information_ratio"] = float(active.mean() / active.std() * np.sqrt(252)) if active.std() else 0.0
    return result


def rolling_scorecard(equity: pd.Series, benchmark: pd.Series, years: int = 3) -> pd.DataFrame:
    window = 252 * years
    strategy_return = equity.pct_change(window)
    benchmark_return = benchmark.pct_change(window)
    strategy_dd = equity / equity.rolling(window, min_periods=window).max() - 1
    benchmark_dd = benchmark / benchmark.rolling(window, min_periods=window).max() - 1
    return pd.DataFrame(
        {
            "strategy_return": strategy_return,
            "benchmark_return": benchmark_return,
            "return_win": strategy_return > benchmark_return,
            "strategy_drawdown": strategy_dd,
            "benchmark_drawdown": benchmark_dd,
            "drawdown_win": strategy_dd > benchmark_dd,
        }
    ).dropna()
