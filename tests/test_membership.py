"""Point-in-time index membership: mask construction and entry-signal gating."""
from __future__ import annotations

from src.backtest_engine import BacktestEngine, build_signal_frame
from src.norgate_loader import _mask_from_intervals
from tests._helpers import ONE_HAMMER_ROWS, make_config, make_ohlc


# --------------------------------------------------------------------------- #
# _mask_from_intervals (pure, no Norgate)
# --------------------------------------------------------------------------- #
def test_mask_from_intervals_marks_only_bars_inside_the_interval():
    idx = make_ohlc(ONE_HAMMER_ROWS).index  # 2020-01-01 .. 2020-01-08, daily
    mask = _mask_from_intervals([("2020-01-04", "2020-01-06")], idx)
    assert list(mask.values) == [False, False, False, True, True, True, False, False]


def test_mask_from_intervals_open_ended_extends_to_the_end():
    idx = make_ohlc(ONE_HAMMER_ROWS).index
    mask = _mask_from_intervals([("2020-01-04", None)], idx)
    assert list(mask.values) == [False, False, False, True, True, True, True, True]


def test_mask_from_intervals_empty_is_all_false():
    idx = make_ohlc(ONE_HAMMER_ROWS).index
    mask = _mask_from_intervals([], idx)
    assert not mask.any()


def test_mask_from_intervals_unions_multiple_intervals():
    idx = make_ohlc(ONE_HAMMER_ROWS).index
    mask = _mask_from_intervals(
        [("2020-01-01", "2020-01-02"), ("2020-01-07", None)], idx)
    assert list(mask.values) == [True, True, False, False, False, False, True, True]


# --------------------------------------------------------------------------- #
# build_signal_frame respects the _member mask
# --------------------------------------------------------------------------- #
def test_signal_frame_unaffected_when_no_member_column():
    df = make_ohlc(ONE_HAMMER_ROWS)
    frame = build_signal_frame(df, make_config())
    # The lone hammer at index 3 produces the only entry signal.
    assert bool(frame["entry_signal"].iloc[3])
    assert int(frame["entry_signal"].sum()) == 1


def test_member_false_on_signal_bar_suppresses_the_entry():
    df = make_ohlc(ONE_HAMMER_ROWS)
    df["_member"] = False  # never a constituent
    frame = build_signal_frame(df, make_config())
    assert int(frame["entry_signal"].sum()) == 0


def test_member_true_on_signal_bar_keeps_the_entry():
    df = make_ohlc(ONE_HAMMER_ROWS)
    df["_member"] = True
    frame = build_signal_frame(df, make_config())
    assert bool(frame["entry_signal"].iloc[3])
    assert int(frame["entry_signal"].sum()) == 1


# --------------------------------------------------------------------------- #
# End-to-end: gating removes the trade
# --------------------------------------------------------------------------- #
def test_engine_produces_no_trades_when_signal_bar_is_outside_membership():
    df = make_ohlc(ONE_HAMMER_ROWS)
    # Member only AFTER the hammer/entry window -> the single trade is gated out.
    df["_member"] = [False] * 5 + [True] * 3
    result = BacktestEngine(df, make_config()).run()
    assert len(result.trades) == 0


def test_engine_keeps_trade_when_signal_bar_is_inside_membership():
    df = make_ohlc(ONE_HAMMER_ROWS)
    df["_member"] = True
    result = BacktestEngine(df, make_config()).run()
    assert len(result.trades) == 1
