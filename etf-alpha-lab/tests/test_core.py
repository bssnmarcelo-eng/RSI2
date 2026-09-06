from __future__ import annotations

import numpy as np
import pandas as pd

from etf_alpha.backtest import run_backtest
from etf_alpha.candidates import CANDIDATES, STRATEGY_CATALOG
from etf_alpha.config import DEFAULT_UNIVERSE, UNIVERSE_GROUPS, CostConfig, LabConfig, RiskConfig
from etf_alpha.costs import order_cost
from etf_alpha.orders import target_orders
from etf_alpha.strategies import covel_style_trend, strategy_signals


def make_frames(periods: int = 800) -> dict[str, pd.DataFrame]:
    dates = pd.bdate_range("2010-01-04", periods=periods)
    frames = {}
    for index, symbol in enumerate(DEFAULT_UNIVERSE):
        wave = np.sin(np.arange(periods) / (17 + index)) * (0.002 + index * 0.0001)
        daily = 0.00025 + (index - 3) * 0.00002 + wave
        close = 100 * np.exp(np.cumsum(daily))
        open_ = close * (1 + np.cos(np.arange(periods) / 11) * 0.0005)
        frames[symbol] = pd.DataFrame(
            {"open": open_, "high": close * 1.01, "low": close * 0.99, "close": close, "volume": 1_000_000},
            index=dates,
        )
    return frames


def test_ibkr_tiered_cost_has_minimum_and_slippage():
    config = CostConfig(third_party_bps=0, slippage_bps=2)
    assert order_cost(1, 100, config) == 0.35 + 0.02
    assert order_cost(1_000, 100, config) == 3.5 + 20


def test_curated_universe_is_diverse_and_has_no_duplicates():
    assert len(UNIVERSE_GROUPS) >= 8
    assert len(DEFAULT_UNIVERSE) >= 70
    assert len(DEFAULT_UNIVERSE) == len(set(DEFAULT_UNIVERSE))
    assert {"SPY", "EWJ", "INDA", "TLT", "GLD", "VNQI", "UUP"} <= set(DEFAULT_UNIVERSE)


def test_candidate_catalog_is_complete_and_weights_sum_to_one():
    assert len(CANDIDATES) >= 7
    for profile in CANDIDATES.values():
        assert abs(sum(profile.weights.values()) - 1.0) < 1e-12
        assert set(profile.weights) <= set(STRATEGY_CATALOG)


def test_orders_support_long_and_short_targets():
    orders = target_orders(
        {"SPY": 10},
        pd.Series({"SPY": -0.1, "TLT": 0.2}),
        pd.Series({"SPY": 100.0, "TLT": 100.0}),
        10_000,
    ).set_index("symbol")
    assert orders.loc["SPY", "action"] == "SELL"
    assert orders.loc["SPY", "target_shares"] == -10
    assert orders.loc["TLT", "action"] == "BUY"


def test_signals_do_not_look_into_future():
    frames = make_frames(500)
    close = pd.concat({key: value["close"] for key, value in frames.items()}, axis=1)
    before, before_regime = strategy_signals(close)
    changed = close.copy()
    changed.iloc[-1] *= 10
    after, after_regime = strategy_signals(changed)
    for name in before:
        pd.testing.assert_frame_equal(before[name].iloc[:-1], after[name].iloc[:-1])
    pd.testing.assert_frame_equal(before_regime.iloc[:-1], after_regime.iloc[:-1])


def test_covel_proxy_uses_breakout_exit_and_bounded_weights():
    dates = pd.bdate_range("2020-01-01", periods=100)
    price = pd.Series(100.0, index=dates)
    price.iloc[55:75] = np.arange(101.0, 121.0)
    price.iloc[75:] = np.arange(119.0, 94.0, -1.0)
    close = pd.DataFrame({symbol: price for symbol in DEFAULT_UNIVERSE}, index=dates)

    weights = covel_style_trend(close)

    assert weights.loc[dates[60], "SPY"] > 0
    assert weights.loc[dates[-1], "SPY"] < 0
    assert (weights.abs().sum(axis=1) <= 1.0000001).all()
    assert (weights.abs().max(axis=1) <= 0.2500001).all()


def test_backtest_is_unlevered_and_delays_execution():
    config = LabConfig(
        symbols=tuple(make_frames()),
        start_date="2010-01-01",
        costs=CostConfig(slippage_bps=0, third_party_bps=0, short_borrow_rate=0),
        risk=RiskConfig(max_gross=1.0),
    )
    result = run_backtest(make_frames(), config)
    assert (result.executed_weights.abs().sum(axis=1) <= 1.0000001).all()
    pd.testing.assert_frame_equal(result.executed_weights.iloc[1:], result.target_weights.shift(1).iloc[1:])
    assert result.equity.notna().all()
    assert result.costs.sum() > 0
    assert set(result.strategy_metrics.index) == {
        "Macro Leading",
        "US Factor Rotation",
        "GICS Long/Short",
        "Country Momentum",
        "Multi-Asset Trend",
        "Covel-Style Trend (Public Proxy)",
        "Technical Breakout",
        "Credit Cycle",
    }
    assert result.strategy_metrics.loc["Macro Leading", "rebalance_days"] < 80
    assert result.strategy_metrics.loc["Multi-Asset Trend", "short_days"] > 0
    assert set(result.candidate_comparison.index) == set(CANDIDATES)
