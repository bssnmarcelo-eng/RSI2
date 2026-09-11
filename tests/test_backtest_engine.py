"""Core engine behaviour: no look-ahead, exit priority, order types, sizing, P&L."""
from __future__ import annotations

import math
from dataclasses import replace

import pandas as pd
import pytest

from src.backtest_engine import BacktestEngine, _OpenPosition, add_period_mfe, build_signal_frame
from src.types import (
    CommissionModel,
    CostConfig,
    Execution,
    ExitConfig,
    SizingConfig,
    SizingMethod,
)
from tests._helpers import ONE_HAMMER_ROWS, make_config, make_ohlc


# --------------------------------------------------------------------------- #
# No look-ahead
# --------------------------------------------------------------------------- #
def test_period_mfe_includes_twelve_week_horizon():
    dates = pd.date_range("2026-01-02", periods=14, freq="7D")
    data = pd.DataFrame({"high": [100.0] * 6 + [110.0] * 6 + [125.0, 130.0]}, index=dates)
    trades = pd.DataFrame({"entry_date": [dates[0]], "entry_price": [100.0]})

    result = add_period_mfe(trades, data)

    assert result.loc[0, "mfe_5w"] == pytest.approx(0.0)
    assert result.loc[0, "mfe_12w"] == pytest.approx(0.25)


def test_next_open_entry_fills_on_the_bar_after_the_signal():
    df = make_ohlc(ONE_HAMMER_ROWS)
    cfg = make_config()  # all exits off -> single trade force-closed at the end
    result = BacktestEngine(df, cfg).run()

    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    # Signal confirmed at the hammer's close (index 3); fill at index 4's open.
    assert trade["signal_date"] == df.index[3]
    assert trade["entry_date"] == df.index[4]
    assert trade["entry_price"] == pytest.approx(105.0)
    # The fill price is NOT taken from the signal bar.
    assert trade["entry_price"] != df["close"].iloc[3]


def test_signal_close_entry_fills_on_the_signal_bar():
    df = make_ohlc(ONE_HAMMER_ROWS)
    cfg = make_config(entry_execution=Execution.SIGNAL_CLOSE)
    result = BacktestEngine(df, cfg).run()

    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    assert trade["entry_date"] == df.index[3]
    assert trade["entry_price"] == pytest.approx(109.0)  # the signal bar's close


def test_sma_200_above_and_rising_filters_use_signal_bar_only():
    closes = [100.0 + i for i in range(205)]
    rows = [(close, close + 1.0, close - 2.0, close) for close in closes]
    cfg = make_config(sma_200_price_filter="above", sma_200_slope_filter="rising")

    frame = build_signal_frame(make_ohlc(rows), cfg)

    assert bool(frame["entry_signal"].iloc[-1])
    assert frame["sma_200"].iloc[-1] > frame["sma_200"].iloc[-2]
    assert frame["close"].iloc[-1] > frame["sma_200"].iloc[-1]


def test_sma_200_filters_reject_opposite_trend():
    closes = [300.0 - i for i in range(205)]
    rows = [(close, close + 1.0, close - 2.0, close) for close in closes]
    cfg = make_config(sma_200_price_filter="above", sma_200_slope_filter="rising")

    frame = build_signal_frame(make_ohlc(rows), cfg)

    assert not bool(frame["entry_signal"].iloc[-1])
    assert frame["sma_200"].iloc[-1] < frame["sma_200"].iloc[-2]


# --------------------------------------------------------------------------- #
# Exit priority (unit-tested directly on _exit_reason)
# --------------------------------------------------------------------------- #
def _engine_with_exits(exits: ExitConfig) -> BacktestEngine:
    return BacktestEngine(make_ohlc(ONE_HAMMER_ROWS), make_config(exits=exits))


def _open_position(entry_index: int, entry_price: float) -> _OpenPosition:
    return _OpenPosition(
        shares=1.0, entry_price=entry_price, entry_index=entry_index,
        entry_date=None, entry_commission=0.0, signal_date=None,
        signal_close=entry_price, signal_low=0.0, signal_range=0.0,
        signal_body_percentile=0.0, signal_atr_mult=0.0, rsi_at_signal=0.0,
        pattern="Hammer", entered_at_close=False,
    )


def test_time_stop_beats_profit_target():
    eng = _engine_with_exits(ExitConfig(
        use_rsi_exit=False, use_max_bars=True, max_bars=2,
        use_profit_target=True, profit_target_pct=5.0,
        use_stop_loss=False, use_sma_exit=False,
        use_signal_low_stop=False, use_rsi_cum_exit=False,
    ))
    df = pd.DataFrame({"close": [100.0, 105.0, 110.0], "rsi": [50.0, 50.0, 50.0]})
    pos = _open_position(entry_index=0, entry_price=100.0)
    # At i=2: bars_held=2 (>= max_bars) AND close 110 >= profit target 105.
    reason = eng._exit_reason(pos, 2, df)
    assert reason.startswith("Time stop")


def test_profit_target_beats_sma_exit():
    eng = _engine_with_exits(ExitConfig(
        use_rsi_exit=False, use_max_bars=False,
        use_profit_target=True, profit_target_pct=5.0,
        use_stop_loss=False, use_sma_exit=True, sma_period=3,
        use_signal_low_stop=False, use_rsi_cum_exit=False,
    ))
    df = pd.DataFrame({
        "close": [100.0, 100.0, 110.0],
        "rsi": [50.0, 50.0, 50.0],
        "sma_exit": [100.0, 100.0, 100.0],
    })
    pos = _open_position(entry_index=0, entry_price=100.0)
    # close 110 >= PT (105) AND close 110 > SMA (100) -> PT wins (higher priority).
    reason = eng._exit_reason(pos, 2, df)
    assert reason.startswith("Profit target")


# --------------------------------------------------------------------------- #
# LIMIT_AT_CLOSE order type — the three fill cases
# --------------------------------------------------------------------------- #
_LIMIT_PREFIX = [
    (100, 101, 99, 100), (100, 101, 99, 99), (99, 100, 98, 98),
    (108, 110, 104, 109),  # hammer, close 109 -> limit = 109
]


def test_limit_fills_at_open_when_bar_gaps_below_limit():
    rows = _LIMIT_PREFIX + [
        (108, 109, 107, 108),  # open 108 <= 109 -> fill at the open
        (108, 109, 107, 108),
    ]
    cfg = make_config(entry_execution=Execution.LIMIT_AT_CLOSE)
    result = BacktestEngine(make_ohlc(rows), cfg).run()
    assert len(result.trades) == 1
    assert result.trades.iloc[0]["entry_price"] == pytest.approx(108.0)


def test_limit_fills_at_limit_when_price_retraces_down():
    rows = _LIMIT_PREFIX + [
        (110, 111, 108, 108.5),  # open 110 > 109 but low 108 <= 109 -> fill at limit 109
        (108, 109, 107, 108),
    ]
    cfg = make_config(entry_execution=Execution.LIMIT_AT_CLOSE)
    result = BacktestEngine(make_ohlc(rows), cfg).run()
    assert len(result.trades) == 1
    assert result.trades.iloc[0]["entry_price"] == pytest.approx(109.0)


def test_limit_does_not_fill_when_price_never_reaches_it():
    rows = _LIMIT_PREFIX + [
        (110, 111, 109.5, 110.5),  # open & low both above the limit -> no fill
        (108, 109, 107, 108),
    ]
    cfg = make_config(entry_execution=Execution.LIMIT_AT_CLOSE)
    result = BacktestEngine(make_ohlc(rows), cfg).run()
    assert len(result.trades) == 0


# --------------------------------------------------------------------------- #
# Intrabar signal-low stop
# --------------------------------------------------------------------------- #
def test_signal_low_stop_fills_at_stop_level():
    rows = [
        (100, 101, 99, 100), (100, 101, 99, 99), (99, 100, 98, 98),
        (108, 110, 104, 109),     # hammer, signal low = 104
        (105, 106, 104.5, 105),   # entry at open 105; low 104.5 > 104 -> no stop yet
        (105, 106, 100, 103),     # low 100 <= 104, open 105 >= 104 -> fill at stop 104
        (105, 106, 104, 105),
    ]
    exits = ExitConfig(use_rsi_exit=False, use_max_bars=False, use_profit_target=False,
                       use_stop_loss=False, use_sma_exit=False,
                       use_signal_low_stop=True, use_rsi_cum_exit=False)
    result = BacktestEngine(make_ohlc(rows), make_config(exits=exits)).run()
    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    assert "Signal-low" in trade["exit_reason"]
    assert trade["exit_price"] == pytest.approx(104.0)


def test_signal_low_stop_fills_at_open_on_gap_down():
    rows = [
        (100, 101, 99, 100), (100, 101, 99, 99), (99, 100, 98, 98),
        (108, 110, 104, 109),     # hammer, signal low = 104
        (105, 106, 104.5, 105),   # entry at open 105
        (99, 108, 95, 100),       # open 99 < stop 104 -> fill at the open (gap); not a hammer
        (105, 106, 104, 105),
    ]
    exits = ExitConfig(use_rsi_exit=False, use_max_bars=False, use_profit_target=False,
                       use_stop_loss=False, use_sma_exit=False,
                       use_signal_low_stop=True, use_rsi_cum_exit=False)
    result = BacktestEngine(make_ohlc(rows), make_config(exits=exits)).run()
    assert len(result.trades) == 1
    assert result.trades.iloc[0]["exit_price"] == pytest.approx(99.0)


# --------------------------------------------------------------------------- #
# Force-close at end of data
# --------------------------------------------------------------------------- #
def test_open_position_force_closed_at_end_with_warning():
    result = BacktestEngine(make_ohlc(ONE_HAMMER_ROWS), make_config()).run()
    assert len(result.trades) == 1
    assert result.trades.iloc[-1]["exit_reason"] == "End of data"
    assert any("end of the data" in w.lower() for w in result.warnings)


# --------------------------------------------------------------------------- #
# Sizing / affordability
# --------------------------------------------------------------------------- #
def test_fit_to_cash_never_overspends_with_full_sizing_and_commission():
    cfg = make_config(
        costs=CostConfig(model=CommissionModel.GENERIC, commission_pct=0.01),
        sizing=SizingConfig(method=SizingMethod.FULL, allow_fractional=True),
    )
    eng = BacktestEngine(make_ohlc(ONE_HAMMER_ROWS), cfg)
    raw = eng._shares_for(cash=10_000.0, equity=10_000.0, price=100.0)  # 100 shares
    fitted = eng._fit_to_cash(raw, price=100.0, cash=10_000.0)
    assert fitted < raw
    notional = fitted * 100.0
    assert notional + eng._commission(fitted, notional) <= 10_000.0 + 1e-9


def test_non_fractional_sizing_floors_shares():
    cfg = make_config(sizing=SizingConfig(method=SizingMethod.FIXED,
                                          fixed_capital=1000.0, allow_fractional=False))
    eng = BacktestEngine(make_ohlc(ONE_HAMMER_ROWS), cfg)
    shares = eng._shares_for(cash=10_000.0, equity=10_000.0, price=105.0)
    assert shares == math.floor(1000.0 / 105.0)


def test_full_sizing_run_keeps_cash_non_negative():
    cfg = make_config(
        costs=CostConfig(model=CommissionModel.IBKR_FIXED, ibkr_per_share=0.005,
                         ibkr_min_per_order=1.0, ibkr_max_pct=0.01),
        sizing=SizingConfig(method=SizingMethod.FULL, allow_fractional=True),
    )
    result = BacktestEngine(make_ohlc(ONE_HAMMER_ROWS), cfg).run()
    assert (result.equity_curve >= 0).all()


# --------------------------------------------------------------------------- #
# P&L / return arithmetic on a controlled round-trip
# --------------------------------------------------------------------------- #
def test_round_trip_pnl_and_returns():
    rows = [
        (100, 101, 99, 100), (100, 101, 99, 99), (99, 100, 98, 98),
        (108, 110, 104, 109),    # hammer idx 3
        (105, 106, 104, 105),    # idx 4: entry at open 105
        (105, 106, 104, 105),    # idx 5: bars_held=1 -> time-stop signal
        (110, 111, 109, 110),    # idx 6: exit fills at open 110
        (110, 111, 109, 110),
    ]
    exits = ExitConfig(use_rsi_exit=False, use_max_bars=True, max_bars=1,
                       use_profit_target=False, use_stop_loss=False,
                       use_sma_exit=False, use_signal_low_stop=False,
                       use_rsi_cum_exit=False)
    cfg = make_config(
        exits=exits,
        costs=CostConfig(model=CommissionModel.GENERIC, commission_fixed=1.0),
        sizing=SizingConfig(method=SizingMethod.FIXED, fixed_capital=1000.0,
                            allow_fractional=True),
    )
    result = BacktestEngine(make_ohlc(rows), cfg).run()
    assert len(result.trades) == 1
    t = result.trades.iloc[0]

    shares = 1000.0 / 105.0
    entry_notional = shares * 105.0          # 1000
    proceeds = shares * 110.0
    gross_pnl = proceeds - entry_notional
    net_pnl = gross_pnl - 1.0 - 1.0          # two $1 commissions
    cost_basis = entry_notional + 1.0

    assert t["entry_price"] == pytest.approx(105.0)
    assert t["exit_price"] == pytest.approx(110.0)
    assert t["gross_return"] == pytest.approx(110.0 / 105.0 - 1.0)
    assert t["pnl"] == pytest.approx(net_pnl)
    assert t["net_return"] == pytest.approx(net_pnl / cost_basis)


def test_replace_changes_ticker_without_touching_original():
    cfg = make_config()
    cfg2 = replace(cfg, ticker="AAPL")
    assert cfg.ticker == "TEST"
    assert cfg2.ticker == "AAPL"
