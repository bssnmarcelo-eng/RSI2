"""Regression tests for locale-aware loading and strict OHLC validation."""
from __future__ import annotations

import pandas as pd
import pytest

from src.data_loader import _coerce_numeric, prepare


def test_numeric_coercion_accepts_us_and_european_mixed_separators():
    values = pd.Series(["1,234.56", "1.234,56", "32,8145", "186290400"])
    actual = _coerce_numeric(values).tolist()
    assert actual == pytest.approx([1234.56, 1234.56, 32.8145, 186290400.0])


def test_prepare_removes_every_invalid_ohlc_topology():
    raw = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=4),
        "open": [10, 10, 10, 10],
        "high": [12, 9, 12, 12],       # row 1: high below open/close
        "low": [8, 8, 11, 13],         # row 2: low above open/close; row 3 high < low
        "close": [11, 10, 10, 10],
    })

    clean, warnings = prepare(raw)

    assert len(clean) == 1
    assert clean.index.tolist() == [pd.Timestamp("2024-01-01")]
    message = " ".join(warnings)
    assert "inconsistent OHLC" in message
    assert "high below open/close" in message
    assert "low above open/close" in message


def test_prepare_reports_unsorted_dates_and_unusually_large_gaps():
    raw = pd.DataFrame({
        "date": pd.to_datetime(["2024-02-01", "2024-01-02", "2024-01-01", "2024-01-03"]),
        "open": [10] * 4, "high": [11] * 4, "low": [9] * 4, "close": [10] * 4,
    })
    clean, warnings = prepare(raw)
    message = " ".join(warnings)
    assert clean.index.is_monotonic_increasing
    assert "out of chronological order" in message
    assert "unusually large date gap" in message
