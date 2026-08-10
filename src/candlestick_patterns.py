"""Objective, rule-based hammer detector.

Vectorised and causal: the boolean flag at bar ``i`` depends only on bars <= i,
so feeding it into the engine cannot introduce look-ahead bias.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .indicators import atr
from .types import HammerParams, PatternConfig


def detect_hammer(df: pd.DataFrame, params: HammerParams) -> pd.Series:
    """Percentile-based hammer detector.

    With ``range = high - low`` and ``threshold = high - percentile * range``, a
    candle qualifies as a hammer when, using only that candle's OHLC:

        * total_range > 0
        * open  > threshold   (open in the top ``percentile`` of the range)
        * close > threshold   (close in the top ``percentile`` of the range)
        * (optional) close >= open when require_bullish_close is True
        * (optional) total_range > atr_multiple * ATR(atr_period) when the ATR
          filter is enabled — i.e. only above-average-range candles qualify.

    Both open and close sitting near the high implies a long lower shadow.
    """
    o, h, low, c = df["open"], df["high"], df["low"], df["close"]
    total_range = h - low
    threshold = h - params.percentile * total_range

    cond = (total_range > 0) & (o > threshold) & (c > threshold)
    if params.require_bullish_close:
        cond &= c >= o
    if params.use_atr_filter:
        atr_series = atr(h, low, c, params.atr_period)
        cond &= total_range > (params.atr_multiple * atr_series)
    return cond.fillna(False)


def detect_all(df: pd.DataFrame, config: PatternConfig) -> pd.DataFrame:
    """Return a frame with the hammer column plus:

        ``any_pattern`` : True when the hammer fired
        ``pattern``     : "Hammer" on firing bars, else ""
    """
    hammer = (
        detect_hammer(df, config.hammer) if config.use_hammer
        else pd.Series(False, index=df.index)
    )
    out = pd.DataFrame({"hammer": hammer.astype(bool)}, index=df.index)
    out["any_pattern"] = out["hammer"]
    out["pattern"] = np.where(out["hammer"], "Hammer", "")
    return out
