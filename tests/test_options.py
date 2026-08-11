from __future__ import annotations

import math
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.backtest_engine import BacktestEngine
from src.options.black_scholes import price_call_bsm
from src.options.contracts import select_expiration, select_strike
from src.options.pricing import price_call
from src.options.simulation import apply_synthetic_call_overlay
from src.options.volatility import realised_volatility
from src.types import InstrumentType, OptionConfig, OptionPricingModel
from tests._helpers import ONE_HAMMER_ROWS, make_config, make_ohlc


def test_black_scholes_matches_reference_call_value_and_greeks():
    quote = price_call_bsm(100, 100, 1, 0.05, 0.20)
    assert quote.price == pytest.approx(10.4506, abs=1e-4)
    assert quote.delta == pytest.approx(0.6368, abs=1e-4)
    assert quote.intrinsic == 0
    assert quote.time_value == pytest.approx(quote.price)
    assert quote.theta < 0
    assert quote.vega > 0


def test_binomial_converges_to_bsm_for_non_dividend_call():
    bsm = price_call(100, 100, 0.5, 0.03, 0.25)
    tree = price_call(100, 100, 0.5, 0.03, 0.25,
                      model=OptionPricingModel.BINOMIAL, binomial_steps=500)
    assert tree.price == pytest.approx(bsm.price, abs=0.03)
    assert 0 < tree.delta < 1


def test_expiry_payoff_and_atm_contract_rules():
    quote = price_call_bsm(112, 100, 0, 0.05, 0.20)
    assert quote.price == 12
    assert quote.time_value == 0
    assert select_strike(101.2) == 101.2
    assert select_strike(101.2, "rounded", 5) == 100
    assert select_strike(100, "otm_pct", 1, 10) == 110
    assert select_strike(101.2, "otm_pct", 5, 10) == 110
    expiry = select_expiration(pd.Timestamp("2026-08-11"), 45)
    assert expiry.weekday() == 4
    assert (expiry - pd.Timestamp("2026-08-11")).days >= 45


def test_realised_volatility_is_causal():
    close = pd.Series([100, 101, 99, 102, 103, 104.0])
    original = realised_volatility(close, 3)
    changed = close.copy()
    changed.iloc[-1] = 1_000
    revised = realised_volatility(changed, 3)
    pd.testing.assert_series_equal(original.iloc[:-1], revised.iloc[:-1])
    assert original.iloc[-1] != revised.iloc[-1]


def test_synthetic_call_comparison_preserves_stock_trade_and_adds_option_columns():
    frame = make_ohlc(ONE_HAMMER_ROWS)
    cfg = make_config(
        instrument=InstrumentType.SYNTHETIC_ATM_CALL,
        options=OptionConfig(
            enabled=True,
            target_dte=45,
            roll_dte=10,
            volatility_window=3,
            iv_multiplier=1.0,
            iv_floor=0.20,
            iv_cap=1.0,
            premium_risk_pct=25,
            spread_pct=0.10,
            commission_per_contract=0.65,
        ),
    )
    stock = BacktestEngine(
        frame,
        replace(cfg, instrument=InstrumentType.STOCK,
                options=replace(cfg.options, enabled=False)),
    ).run()
    result = BacktestEngine(frame, cfg).run()
    assert len(result.trades) == 1
    trade = result.trades.iloc[0]
    pd.testing.assert_series_equal(result.equity_curve, stock.equity_curve)
    assert trade["entry_date"] == stock.trades.iloc[0]["entry_date"]
    assert trade["exit_date"] == stock.trades.iloc[0]["exit_date"]
    assert trade["pnl"] == pytest.approx(stock.trades.iloc[0]["pnl"])
    assert trade["option_instrument"] == "synthetic_atm_call"
    assert trade["option_synthetic"]
    assert trade["option_exit_reason"] == stock.trades.iloc[0]["exit_reason"]
    assert trade["option_contracts"] == int(trade["option_contracts"])
    assert trade["option_contracts"] > 0
    assert trade["option_entry_price"] > trade["option_entry_theoretical"]
    assert trade["option_exit_price"] < trade["option_exit_theoretical"]
    assert trade["option_strike"] == pytest.approx(trade["option_underlying_entry_price"])
    assert math.isfinite(trade["option_pnl"])
    assert len(result.equity_curve) == len(frame)
    assert result.equity_curve.map(math.isfinite).all()
    assert any("mark-to-model" in warning for warning in result.warnings)


def test_weekly_signals_are_not_recomputed_by_daily_option_pricing_data():
    weekly = make_ohlc(ONE_HAMMER_ROWS)
    weekly.index = pd.date_range("2020-01-03", periods=len(weekly), freq="W-FRI")
    daily_index = pd.date_range(weekly.index.min(), weekly.index.max(), freq="B")
    daily = weekly.reindex(daily_index).interpolate(method="time").bfill().ffill()
    cfg = make_config(
        instrument=InstrumentType.SYNTHETIC_ATM_CALL,
        options=OptionConfig(enabled=True, volatility_window=3, iv_floor=0.2,
                             premium_risk_pct=25),
    )
    stock_cfg = replace(cfg, instrument=InstrumentType.STOCK,
                        options=replace(cfg.options, enabled=False))

    stock = BacktestEngine(weekly, stock_cfg).run()
    compared = BacktestEngine(weekly, cfg, option_data=daily).run()

    assert len(compared.trades) == len(stock.trades) == 1
    assert compared.trades["entry_date"].tolist() == stock.trades["entry_date"].tolist()
    assert compared.trades["exit_date"].tolist() == stock.trades["exit_date"].tolist()
    assert compared.trades.iloc[0]["option_entry_date"] > compared.trades.iloc[0]["signal_date"]
    assert compared.trades.iloc[0]["option_status"] == "priced"


def test_otm_percentage_mode_is_applied_to_each_trade_strike():
    frame = make_ohlc(ONE_HAMMER_ROWS)
    cfg = make_config(
        instrument=InstrumentType.SYNTHETIC_ATM_CALL,
        options=OptionConfig(
            enabled=True,
            strike_mode="otm_pct",
            strike_interval=1,
            otm_pct=10,
            volatility_window=3,
            iv_floor=0.20,
            premium_risk_pct=50,
        ),
    )

    result = BacktestEngine(frame, cfg).run()

    trade = result.trades.iloc[0]
    expected = round(float(trade["option_underlying_entry_price"]) * 1.10)
    assert trade["option_strike"] == pytest.approx(expected)
    assert trade["option_strike"] > trade["option_underlying_entry_price"]


def test_small_fractional_dividend_yield_is_not_misread_as_percentage_points():
    frame = make_ohlc(ONE_HAMMER_ROWS)
    frame["dividend_yield"] = 0.0015
    cfg = make_config(
        instrument=InstrumentType.SYNTHETIC_ATM_CALL,
        options=OptionConfig(enabled=True, volatility_window=2, iv_floor=0.2,
                             premium_risk_pct=50),
    )
    result = BacktestEngine(frame, cfg).run()
    assert result.trades.iloc[0]["option_dividend_yield_entry"] == pytest.approx(0.0015)


def test_capital_event_closes_synthetic_contract_conservatively():
    frame = make_ohlc(ONE_HAMMER_ROWS)
    frame["capital_event"] = False
    frame.loc[frame.index[6], "capital_event"] = True
    cfg = make_config(
        instrument=InstrumentType.SYNTHETIC_ATM_CALL,
        options=OptionConfig(enabled=True, volatility_window=2, iv_floor=0.2,
                             premium_risk_pct=50),
    )
    result = BacktestEngine(frame, cfg).run()
    trade = result.trades.iloc[0]
    assert trade["exit_date"] != frame.index[6]
    assert trade["option_exit_date"] == frame.index[6]
    assert trade["exit_reason"] != "Capital event — synthetic contract closed"


def test_call_is_settled_at_expiry_without_rolling_when_stock_trade_continues():
    dates = pd.bdate_range("2024-01-02", periods=90)
    close = np.linspace(100.0, 130.0, len(dates))
    frame = pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
        },
        index=dates,
    )
    cfg = make_config(
        instrument=InstrumentType.SYNTHETIC_ATM_CALL,
        options=OptionConfig(
            enabled=True,
            target_dte=30,
            roll_dte=10,  # Legacy values are ignored: the engine never rolls.
            volatility_window=3,
            iv_floor=0.20,
            premium_risk_pct=50,
            spread_pct=0.10,
            commission_per_contract=0.65,
        ),
    )
    base = SimpleNamespace(
        config=cfg,
        data=frame,
        warnings=[],
        equity_curve=pd.Series(10_000.0, index=dates),
        trades=pd.DataFrame(
            [{
                "ticker": "TEST",
                "signal_date": dates[0],
                "entry_date": dates[1],
                "exit_date": dates[-1],
                "entry_price": float(frame.loc[dates[1], "open"]),
                "exit_price": float(frame.loc[dates[-1], "close"]),
                "exit_reason": "End of data",
                "rsi_at_signal": 5.0,
            }]
        ),
    )

    result = apply_synthetic_call_overlay(
        base,
        {"TEST": frame},
        cfg,
        initial_capital=10_000.0,
        include_scenarios=False,
    )

    trade = result.trades.iloc[0]
    assert trade["exit_reason"] == "Vencimento da call"
    assert pd.Timestamp(trade["exit_date"]) == pd.Timestamp(trade["expiration"])
    assert trade["dte_exit"] == 0
    assert trade["roll_count"] == 0
    assert trade["option_time_value_exit"] == pytest.approx(0.0)
    assert trade["exit_price"] == pytest.approx(trade["option_intrinsic_exit"])
    assert trade["option_commissions"] == pytest.approx(
        trade["contracts"] * cfg.options.commission_per_contract
    )
