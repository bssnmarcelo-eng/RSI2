"""Causal realised-volatility proxies for synthetic implied volatility."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.types import OptionConfig


def realised_volatility(close: pd.Series, window: int = 20) -> pd.Series:
    returns = np.log(close.astype(float) / close.astype(float).shift(1))
    minimum = max(int(window), 2)
    return returns.rolling(minimum, min_periods=minimum).std(ddof=1) * np.sqrt(252.0)


def synthetic_iv(close: pd.Series, config: OptionConfig) -> pd.Series:
    iv = realised_volatility(close, config.volatility_window)
    iv = iv * config.iv_multiplier * config.iv_scenario
    return iv.clip(lower=config.iv_floor, upper=config.iv_cap).fillna(config.iv_floor)
