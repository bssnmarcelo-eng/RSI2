import pandas as pd

from src.advanced_analysis import (
    buy_and_hold_equity,
    compare_with_benchmark,
    monte_carlo_summary,
    monte_carlo_trades,
)
from src.performance_metrics import compute_metrics, ulcer_index


def test_buy_and_hold_and_comparison():
    idx = pd.date_range("2020-01-01", periods=3)
    benchmark = buy_and_hold_equity(pd.Series([10.0, 11.0, 12.0], index=idx), 100.0)
    strategy = pd.Series([100.0, 105.0, 130.0], index=idx)
    comparison = compare_with_benchmark(strategy, benchmark)
    assert benchmark.iloc[-1] == 120.0
    assert abs(comparison["excess_return"] - 0.1) < 1e-12


def test_monte_carlo_is_deterministic_and_summarized():
    trades = pd.DataFrame({"net_return": [0.1, -0.05, 0.02]})
    a = monte_carlo_trades(trades, 100.0, simulations=100, seed=7)
    b = monte_carlo_trades(trades, 100.0, simulations=100, seed=7)
    pd.testing.assert_frame_equal(a, b)
    summary = monte_carlo_summary(a)
    assert 0.0 <= summary["probability_of_loss"] <= 1.0


def test_ulcer_and_calmar_are_available():
    idx = pd.date_range("2020-01-01", periods=4)
    equity = pd.Series([100.0, 120.0, 90.0, 130.0], index=idx)
    assert ulcer_index(equity) > 0
    metrics = compute_metrics(equity, pd.DataFrame(), 100.0, len(equity))
    assert "calmar" in metrics and "ulcer_index" in metrics and "volatility" in metrics
