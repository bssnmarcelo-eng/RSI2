"""Technical indicators implemented from scratch (no TA libraries).

Every indicator is causal: the value at bar *i* depends only on data at bars
<= i, so feeding these straight into the engine cannot introduce look-ahead bias.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period: int = 2) -> pd.Series:
    """Wilder's RSI computed manually.

    Uses Wilder's smoothing (an EWMA with alpha = 1/period and ``adjust=False``),
    which is the standard definition used by charting platforms. The first
    ``period`` values are NaN because the average gain/loss is not yet defined.

    When there are no losses in the window, RSI is defined as 100; when there are
    no gains it is 0.
    """
    if period < 1:
        raise ValueError("RSI period must be >= 1.")

    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    # Wilder smoothing == EWMA with alpha = 1/period, no debiasing.
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    # rs = inf when avg_loss == 0 -> formula naturally yields 100.
    # rs = 0   when avg_gain == 0 -> formula naturally yields 0.
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        out = 100.0 - (100.0 / (1.0 + rs))

    # The only truly undefined case is a flat window (no gains and no losses):
    # conventionally treated as the neutral midpoint, 50.
    flat = (avg_gain == 0) & (avg_loss == 0)
    out = out.mask(flat, 50.0)
    out.name = f"rsi_{period}"
    return out


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average over a trailing window of ``period`` bars."""
    if period < 1:
        raise ValueError("SMA period must be >= 1.")
    out = series.rolling(window=period, min_periods=period).mean()
    out.name = f"sma_{period}"
    return out


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range (Wilder's smoothing of the True Range).

    True Range = max(high - low, |high - prev_close|, |low - prev_close|).
    Causal: the value at bar i uses only bars <= i. NaN for the first ``period``
    bars (warmup), so an ATR-based filter simply excludes those early candles.
    """
    if period < 1:
        raise ValueError("ATR period must be >= 1.")
    prev_close = close.shift(1)
    true_range = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    out = true_range.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    out.name = f"atr_{period}"
    return out
