import numpy as np
import pandas as pd

from fear_greed.analytics import analyze_portfolio, benchmark_curve


def test_analytics_uses_daily_mark_to_market_curve():
    idx = pd.bdate_range("2024-01-02", periods=260)
    values = 100_000 * np.cumprod(np.r_[1.0, np.repeat(1.001, 100), np.repeat(0.999, 159)])
    equity = pd.DataFrame({"equity": values, "costs": 10.0, "open_positions": 1, "gross_exposure_pct": 50.0}, index=idx)
    result = analyze_portfolio(equity, pd.DataFrame(), 100_000)
    assert result.metrics["annual_volatility"] > 0
    assert result.metrics["max_drawdown"] < 0
    assert result.metrics["time_in_market"] == 1
    assert result.metrics["cagr_per_time_in_market"] == result.metrics["cagr"]
    assert result.metrics["positive_days"] > 0
    assert result.metrics["longest_drawdown_bars"] > 0
    assert not result.monthly.empty
    assert not result.yearly.empty
    assert not result.drawdown_episodes.empty


def test_trade_breakdown_and_benchmark():
    idx = pd.bdate_range("2024-01-02", periods=5)
    equity = pd.DataFrame({"equity": [100, 101, 99, 103, 104], "costs": [0, 1, 1, 2, 2], "open_positions": [0, 1, 1, 1, 0], "gross_exposure_pct": [0, 50, 48, 52, 0]}, index=idx)
    trades = pd.DataFrame({"ticker": ["AAA", "BBB"], "net_return": [0.10, -0.05], "pnl": [10, -5], "commission": [1, 1], "bars_held": [2, 1], "tranche_notionals": [[50], [50]], "exit_notional": [55, 47.5]})
    result = analyze_portfolio(equity, trades, 100)
    assert result.metrics["win_rate"] == 0.5
    assert result.metrics["profit_factor"] == 2
    assert result.metrics["cagr_per_time_in_market"] == result.metrics["cagr"] / 0.6
    assert result.metrics["cagr_per_avg_exposure"] == result.metrics["cagr"] / 0.3
    assert len(result.by_ticker) == 2
    data = pd.DataFrame({"Close": [10, 11, 12, 13, 14]}, index=idx)
    assert benchmark_curve(data, idx, 100).iloc[-1] == 140
