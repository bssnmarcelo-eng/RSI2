"""Shared test fixtures/builders for the backtester test-suite.

Kept deliberately dependency-light: every test builds deterministic synthetic
OHLC frames so behaviour is exactly predictable (no random data, no network).
"""
from __future__ import annotations

import pandas as pd

from src.types import (
    CommissionModel,
    CostConfig,
    Execution,
    ExitConfig,
    HammerParams,
    PatternConfig,
    SizingConfig,
    SizingMethod,
    StrategyConfig,
)


def make_ohlc(rows, start: str = "2020-01-01", freq: str = "D") -> pd.DataFrame:
    """Build an OHLC frame from ``rows`` = list of ``(open, high, low, close)``.

    The index is a contiguous ``DatetimeIndex`` so the engine's date handling and
    the metric annualisation behave as in production.
    """
    idx = pd.date_range(start=start, periods=len(rows), freq=freq)
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)
    return df.astype(float)


def make_config(**overrides) -> StrategyConfig:
    """A neutral StrategyConfig for engine tests.

    Defaults chosen so signals are driven purely by the hammer pattern:
      * ``rsi_entry_threshold = 1000`` -> the ``rsi < threshold`` test is always
        satisfied once RSI is defined, so entries depend only on the hammer.
      * hammer percentile 0.5, ATR filter OFF -> easy to craft qualifying candles.
      * every exit rule OFF and zero costs -> deterministic, friction-free maths.
      * FULL sizing with fractional shares -> exact equity arithmetic.
    Pass ``exits=``/``costs=``/``sizing=`` (or any top-level field) to override.
    """
    cfg = StrategyConfig(
        rsi_period=2,
        rsi_entry_threshold=1000.0,
        patterns=PatternConfig(
            use_hammer=True,
            hammer=HammerParams(percentile=0.5, require_bullish_close=False,
                                use_atr_filter=False),
        ),
        entry_execution=Execution.NEXT_OPEN,
        exit_execution=Execution.NEXT_OPEN,
        exits=ExitConfig(
            use_rsi_exit=False, use_max_bars=False, use_profit_target=False,
            use_stop_loss=False, use_sma_exit=False, use_signal_low_stop=False,
            use_rsi_cum_exit=False,
        ),
        costs=CostConfig(model=CommissionModel.GENERIC, commission_fixed=0.0,
                         commission_pct=0.0, slippage_bps=0.0),
        sizing=SizingConfig(method=SizingMethod.FULL, allow_fractional=True),
        initial_capital=10_000.0,
        ticker="TEST",
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


# A reusable price path with exactly one hammer at index 3 (low 104) and no other
# qualifying candle, used by several engine tests. Entry (NEXT_OPEN) fills at
# index 4's open = 105.
ONE_HAMMER_ROWS = [
    (100, 101, 99, 100),
    (100, 101, 99, 99),
    (99, 100, 98, 98),
    (108, 110, 104, 109),    # idx 3: hammer (range 6, threshold 107; o/c above it)
    (105, 106, 104.5, 105),  # idx 4: entry fills at open 105
    (105, 106, 104.5, 105),
    (105, 106, 104.5, 105),
    (105, 106, 104.5, 105),
]
