"""Tests for the from-scratch technical indicators."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.indicators import atr, rsi, sma


def test_rsi_warmup_is_nan():
    close = pd.Series([10, 11, 12, 13, 14], dtype=float)
    out = rsi(close, period=2)
    # diff makes index 0 NaN; ewm(min_periods=2) needs two deltas -> index 2 onward.
    assert out.iloc[:2].isna().all()
    assert out.iloc[2:].notna().all()


def test_rsi_all_gains_is_100():
    close = pd.Series([1, 2, 3, 4, 5, 6], dtype=float)
    out = rsi(close, period=2).dropna()
    assert np.allclose(out.to_numpy(), 100.0)


def test_rsi_all_losses_is_zero():
    close = pd.Series([6, 5, 4, 3, 2, 1], dtype=float)
    out = rsi(close, period=2).dropna()
    assert np.allclose(out.to_numpy(), 0.0)


def test_rsi_flat_window_is_50():
    close = pd.Series([5, 5, 5, 5, 5], dtype=float)
    out = rsi(close, period=2).dropna()
    assert np.allclose(out.to_numpy(), 50.0)


def test_rsi_invalid_period_raises():
    with pytest.raises(ValueError):
        rsi(pd.Series([1.0, 2.0, 3.0]), period=0)


def test_rsi_is_causal():
    close = pd.Series([10, 9, 11, 8, 12, 7, 13, 6, 14], dtype=float)
    full = rsi(close, period=2)
    for i in range(2, len(close)):
        truncated = rsi(close.iloc[: i + 1], period=2)
        assert truncated.iloc[i] == pytest.approx(full.iloc[i])


def test_sma_known_values():
    series = pd.Series([1, 2, 3, 4, 5], dtype=float)
    out = sma(series, period=3)
    assert out.iloc[:2].isna().all()
    assert out.iloc[2] == pytest.approx(2.0)
    assert out.iloc[3] == pytest.approx(3.0)
    assert out.iloc[4] == pytest.approx(4.0)


def test_atr_warmup_and_positive_and_causal():
    high = pd.Series([11, 12, 13, 12, 14, 13, 15], dtype=float)
    low = pd.Series([9, 10, 11, 10, 12, 11, 13], dtype=float)
    close = pd.Series([10, 11, 12, 11, 13, 12, 14], dtype=float)
    out = atr(high, low, close, period=3)
    # True Range is defined from bar 0 (the max ignores the NaN prev-close terms),
    # so the EWM(min_periods=3) yields its first value at index period-1 = 2.
    assert out.iloc[:2].isna().all()
    assert out.iloc[2:].notna().all()
    assert (out.dropna() > 0).all()
    # Causality: ATR at bar i uses only bars <= i.
    for i in range(3, len(close)):
        trunc = atr(high.iloc[: i + 1], low.iloc[: i + 1], close.iloc[: i + 1], period=3)
        assert trunc.iloc[i] == pytest.approx(out.iloc[i])
