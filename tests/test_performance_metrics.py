"""Tests for the headline performance metrics."""
from __future__ import annotations

import pandas as pd
import pytest

from src.performance_metrics import compute_metrics

_TRADE_COLS = ["net_return", "pnl", "bars_held"]


def _equity(values, start="2020-01-01"):
    idx = pd.date_range(start=start, periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype=float)


def test_zero_trades_returns_neutral_block():
    equity = _equity([100, 110, 105])
    trades = pd.DataFrame(columns=_TRADE_COLS)
    m = compute_metrics(equity, trades, initial_capital=100.0, n_bars=3)
    assert m["num_trades"] == 0
    assert m["win_rate"] == 0.0
    assert m["profit_factor"] == 0.0
    assert m["total_return"] == pytest.approx(0.05)  # 105 / 100 - 1
    assert m["max_drawdown"] < 0  # dipped from 110 to 105


def test_profit_factor_infinite_when_no_losses():
    equity = _equity([100, 120, 150])
    trades = pd.DataFrame({
        "net_return": [0.1, 0.2],
        "pnl": [10.0, 20.0],
        "bars_held": [2, 3],
    })
    m = compute_metrics(equity, trades, initial_capital=100.0, n_bars=3)
    assert m["num_trades"] == 2
    assert m["win_rate"] == pytest.approx(1.0)
    assert m["profit_factor"] == float("inf")
    assert m["best_trade"] == pytest.approx(0.2)


def test_total_return_and_exposure():
    equity = _equity([100, 105, 110, 120, 130])
    trades = pd.DataFrame({
        "net_return": [0.1, -0.05],
        "pnl": [10.0, -5.0],
        "bars_held": [2, 1],
    })
    m = compute_metrics(equity, trades, initial_capital=100.0, n_bars=5)
    assert m["total_return"] == pytest.approx(0.30)
    assert m["win_rate"] == pytest.approx(0.5)
    # exposure = bars in market (2 + 1) / 5 bars.
    assert m["exposure"] == pytest.approx(3 / 5)
