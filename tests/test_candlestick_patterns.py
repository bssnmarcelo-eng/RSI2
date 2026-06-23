"""Tests for the percentile-based hammer detector."""
from __future__ import annotations

from src.candlestick_patterns import detect_all, detect_hammer
from src.types import HammerParams, PatternConfig
from tests._helpers import make_ohlc


def _params(**kw) -> HammerParams:
    base = dict(percentile=0.5, require_bullish_close=False, use_atr_filter=False)
    base.update(kw)
    return HammerParams(**base)


def test_hammer_fires_when_body_near_high():
    # range 6, threshold = high - 0.5*range = 107; open & close above it.
    df = make_ohlc([(108, 110, 104, 109)])
    assert bool(detect_hammer(df, _params()).iloc[0]) is True


def test_hammer_rejected_when_body_low_in_range():
    # open & close in the lower part of the range -> not a hammer.
    df = make_ohlc([(95, 110, 90, 96)])
    assert bool(detect_hammer(df, _params()).iloc[0]) is False


def test_zero_range_is_not_a_hammer():
    df = make_ohlc([(100, 100, 100, 100)])
    assert bool(detect_hammer(df, _params()).iloc[0]) is False


def test_require_bullish_close():
    # Body near the high but bearish (close < open).
    df = make_ohlc([(109, 110, 104, 108)])
    assert bool(detect_hammer(df, _params(require_bullish_close=False)).iloc[0]) is True
    assert bool(detect_hammer(df, _params(require_bullish_close=True)).iloc[0]) is False


def test_atr_filter_suppresses_small_range_candles():
    # A run of average-sized candles, then one body-near-high candle of the SAME
    # small range: with a high ATR multiple the range filter rejects it.
    rows = [(100, 102, 98, 100)] * 16 + [(101.5, 102, 98, 101.8)]
    df = make_ohlc(rows)
    no_filter = detect_hammer(df, _params(use_atr_filter=False)).iloc[-1]
    with_filter = detect_hammer(
        df, _params(use_atr_filter=True, atr_period=14, atr_multiple=5.0)
    ).iloc[-1]
    assert bool(no_filter) is True
    assert bool(with_filter) is False


def test_detect_all_labels_pattern_column():
    df = make_ohlc([(108, 110, 104, 109), (95, 110, 90, 96)])
    out = detect_all(df, PatternConfig(use_hammer=True, hammer=_params()))
    assert list(out["pattern"]) == ["Hammer", ""]
    assert list(out["any_pattern"]) == [True, False]


def test_detect_all_disabled_pattern_never_fires():
    df = make_ohlc([(108, 110, 104, 109)])
    out = detect_all(df, PatternConfig(use_hammer=False, hammer=_params()))
    assert bool(out["any_pattern"].iloc[0]) is False
