import numpy as np
import pandas as pd
import pytest

from fear_greed.engine import StrategyConfig, _next_bar_price, _order_commission, run_backtest


def ohlcv(close):
    close = np.asarray(close, dtype=float)
    idx = pd.bdate_range("2020-01-01", periods=len(close))
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": 2_000_000}, index=idx)


def test_vxx_trend_creates_round_trip():
    close = np.r_[np.linspace(100, 130, 60), np.linspace(130, 70, 80), np.linspace(70, 120, 80)]
    result = run_backtest(ohlcv(close), "VXX", StrategyConfig("vxx_trend", commission_bps=0, slippage_bps=0))
    assert len(result.trades) >= 1
    assert set(result.trades.direction) == {"short"}
    assert result.metrics["trades"] == len(result.trades)


def test_no_trade_returns_flat_equity():
    close = np.linspace(100, 120, 260)
    result = run_backtest(ohlcv(close), "SPY", StrategyConfig("rsi_powerzones"))
    assert result.trades.empty
    assert result.equity.equity.nunique() == 1


def test_costs_reduce_returns():
    close = np.r_[np.linspace(100, 130, 60), np.linspace(130, 70, 80), np.linspace(70, 120, 80)]
    free = run_backtest(ohlcv(close), "VXX", StrategyConfig("vxx_trend", commission_model="Sem comissão", slippage_bps=0))
    costly = run_backtest(ohlcv(close), "VXX", StrategyConfig("vxx_trend", commission_model="IBKR Pro Tiered", slippage_bps=10))
    assert costly.trades.net_return.sum() < free.trades.net_return.sum()


def test_ibkr_pro_order_costs_respect_rates_and_minimums():
    tiered = StrategyConfig("vxx_trend", commission_model="IBKR Pro Tiered", third_party_bps=0)
    fixed = StrategyConfig("vxx_trend", commission_model="IBKR Pro Fixed", third_party_bps=0)
    assert _order_commission(tiered, 100, 10_000) == pytest.approx(0.35)
    assert _order_commission(fixed, 100, 10_000) == pytest.approx(1.00)


def test_next_open_and_breakout_execution_are_causal():
    signal = pd.Series({"Open": 100, "High": 110, "Low": 95, "Close": 105})
    next_bar = pd.Series({"Open": 102, "High": 112, "Low": 99, "Close": 111})
    assert _next_bar_price("long", "Próxima abertura", signal, next_bar, 0) == 102
    assert _next_bar_price("long", "Rompimento da barra de sinal", signal, next_bar, 0) == 110
    no_breakout = pd.Series({"Open": 102, "High": 109, "Low": 98, "Close": 108})
    assert _next_bar_price("long", "Rompimento da barra de sinal", signal, no_breakout, 0) is None
    gap_without_retrace = pd.Series({"Open": 113, "High": 116, "Low": 112, "Close": 115})
    assert _next_bar_price("long", "Rompimento da barra de sinal", signal, gap_without_retrace, 0) is None
    touch_without_crossing = pd.Series({"Open": 113, "High": 116, "Low": 110, "Close": 115})
    assert _next_bar_price("long", "Rompimento da barra de sinal", signal, touch_without_crossing, 0) is None
    gap_with_retrace = pd.Series({"Open": 113, "High": 116, "Low": 109, "Close": 115})
    assert _next_bar_price("long", "Rompimento da barra de sinal", signal, gap_with_retrace, 0) == 110


def test_short_gap_requires_retrace_to_breakout_trigger():
    signal = pd.Series({"Open": 100, "High": 110, "Low": 95, "Close": 105})
    no_retrace = pd.Series({"Open": 90, "High": 94, "Low": 88, "Close": 91})
    touch_without_crossing = pd.Series({"Open": 90, "High": 95, "Low": 88, "Close": 91})
    retrace = pd.Series({"Open": 90, "High": 96, "Low": 88, "Close": 92})
    assert _next_bar_price("short", "Rompimento da barra de sinal", signal, no_retrace, 0) is None
    assert _next_bar_price("short", "Rompimento da barra de sinal", signal, touch_without_crossing, 0) is None
    assert _next_bar_price("short", "Rompimento da barra de sinal", signal, retrace, 0) == 95


def test_open_position_is_marked_to_market_without_forced_trade():
    close = np.r_[np.linspace(100, 150, 250), 147, 143, 139, 136]
    result = run_backtest(ohlcv(close), "SPY", StrategyConfig("rsi_powerzones", commission_model="Sem comissão", slippage_bps=0))
    assert result.trades.empty
    assert result.equity.equity.iloc[-1] != result.equity.equity.iloc[0]
    assert result.metrics["total_return"] != 0
