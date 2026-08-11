"""Value objects used by the synthetic option layer."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OptionQuote:
    price: float
    intrinsic: float
    time_value: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    model: str
