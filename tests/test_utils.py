"""Tests for commission models and small numeric helpers."""
from __future__ import annotations

import pandas as pd
import pytest

from src.types import CommissionModel, CostConfig
from src.utils import commission_for, financing_cost, periods_per_year, safe_div


def test_generic_commission_fixed_plus_pct():
    costs = CostConfig(model=CommissionModel.GENERIC, commission_fixed=2.0,
                       commission_pct=0.01)
    # 2 fixed + 1% of 1000 notional = 12.
    assert commission_for(costs, shares=10, notional=1000.0) == pytest.approx(12.0)


def test_ibkr_per_share_with_min_floor():
    costs = CostConfig(model=CommissionModel.IBKR_FIXED, ibkr_per_share=0.005,
                       ibkr_min_per_order=1.0, ibkr_max_pct=0.01)
    # 100 shares * 0.005 = 0.50 -> below the $1 minimum -> 1.0 (cap 1% of 10000 = 100).
    assert commission_for(costs, shares=100, notional=10_000.0) == pytest.approx(1.0)


def test_ibkr_per_share_uses_raw_rate_within_bounds():
    costs = CostConfig(model=CommissionModel.IBKR_FIXED, ibkr_per_share=0.005,
                       ibkr_min_per_order=1.0, ibkr_max_pct=0.01)
    # 1000 shares * 0.005 = 5.0, above min, below cap (1% of 100000 = 1000) -> 5.0.
    assert commission_for(costs, shares=1000, notional=100_000.0) == pytest.approx(5.0)


def test_ibkr_cap_applied_last_can_fall_below_minimum():
    costs = CostConfig(model=CommissionModel.IBKR_FIXED, ibkr_per_share=0.005,
                       ibkr_min_per_order=1.0, ibkr_max_pct=0.01)
    # 200 shares * 0.005 = 1.0 -> max(1.0, min)=1.0 -> cap = 1% of 50 = 0.5 (last) -> 0.5.
    assert commission_for(costs, shares=200, notional=50.0) == pytest.approx(0.5)


def test_safe_div_handles_zero_denominator():
    assert safe_div(5.0, 0.0, default=-1.0) == -1.0
    assert safe_div(10.0, 2.0) == pytest.approx(5.0)


def test_periods_per_year_short_index_falls_back():
    idx = pd.date_range("2020-01-01", periods=2, freq="D")
    assert periods_per_year(idx) == pytest.approx(252.0)


def test_periods_per_year_daily_is_reasonable():
    idx = pd.date_range("2020-01-01", periods=365, freq="D")
    ppy = periods_per_year(idx)
    # ~365 calendar-day bars per year.
    assert 350 < ppy < 380


def test_financing_cost_combines_margin_and_short_borrow():
    costs = CostConfig(annual_margin_rate=0.10, annual_borrow_fee=0.05)
    assert financing_cost(costs, 1_000.0, 2_000.0, 365.25) == pytest.approx(200.0)
