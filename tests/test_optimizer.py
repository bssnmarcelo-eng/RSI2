"""Tests for strict train/test isolation in the optimizer."""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from src import optimizer
from tests._helpers import make_config, make_ohlc


def test_run_grid_uses_fresh_capital_and_causal_warmup_for_test(monkeypatch):
    calls = []

    class FakeEngine:
        def __init__(self, data, config):
            self.data = data
            self.config = config
            calls.append(self)

        def run(self):
            eligible = self.data.index[self.data["_member"]]
            if len(eligible):
                trades = pd.DataFrame({
                    "entry_date": [eligible[0]],
                    "net_return": [0.10],
                    "pnl": [self.config.initial_capital * 0.10],
                    "bars_held": [1],
                })
            else:
                trades = pd.DataFrame(
                    columns=["entry_date", "net_return", "pnl", "bars_held"]
                )
            return SimpleNamespace(trades=trades)

    monkeypatch.setattr(optimizer, "BacktestEngine", FakeEngine)
    data = make_ohlc([(10, 11, 9, 10)] * 10)
    result, split = optimizer.run_grid(
        {"TEST": data}, make_config(initial_capital=10_000), {}, train_frac=0.5,
        min_trades=1,
    )

    assert len(calls) == 2
    train_call, test_call = calls
    assert train_call.data.index.max() == split
    # Test retains all prior observations as causal indicator warm-up.
    assert test_call.data.index.min() == data.index.min()
    assert not test_call.data.loc[:split, "_member"].any()
    assert test_call.data.loc[test_call.data.index > split, "_member"].all()
    # Both independent runs size from the same fresh initial capital.
    assert result.loc[0, "train_total_pnl"] == pytest.approx(1_000.0)
    assert result.loc[0, "test_total_pnl"] == pytest.approx(1_000.0)


def test_walk_forward_returns_one_selected_result_per_fold(monkeypatch):
    class FakeEngine:
        def __init__(self, data, config):
            self.data, self.config = data, config

        def run(self):
            eligible = self.data.index[self.data["_member"]]
            trades = pd.DataFrame(columns=["entry_date", "net_return", "pnl", "bars_held"])
            if len(eligible):
                score = self.config.rsi_entry_threshold / 100.0
                trades.loc[0] = [eligible[0], score, score * 100.0, 1]
            return SimpleNamespace(trades=trades)

    monkeypatch.setattr(optimizer, "BacktestEngine", FakeEngine)
    data = make_ohlc([(10, 11, 9, 10)] * 12)
    result = optimizer.run_walk_forward(
        {"TEST": data}, make_config(), {"rsi_entry_threshold": [10.0, 20.0]},
        objective="expectancy", n_splits=2, initial_train_frac=0.5, min_trades=1,
    )

    assert len(result) == 2
    assert result["rsi_entry_threshold"].tolist() == [20.0, 20.0]
    assert (result["test_start"] > result["train_end"]).all()


def test_parallel_grid_matches_sequential_grid():
    data = make_ohlc([(10, 11, 9, 10)] * 20)
    ranges = {"rsi_entry_threshold": [10.0, 20.0]}
    sequential, split_a = optimizer.run_grid(
        {"TEST": data}, make_config(), ranges, train_frac=0.5, workers=1
    )
    parallel, split_b = optimizer.run_grid(
        {"TEST": data}, make_config(), ranges, train_frac=0.5, workers=2
    )
    assert split_a == split_b
    pd.testing.assert_frame_equal(sequential, parallel)
