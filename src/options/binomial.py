"""Cox-Ross-Rubinstein American-call pricing with continuous dividend yield."""
from __future__ import annotations

import math

import numpy as np

from .types import OptionQuote


def _price(spot: float, strike: float, time_years: float, rate: float,
           volatility: float, dividend_yield: float, steps: int) -> float:
    if time_years <= 0:
        return max(spot - strike, 0.0)
    n = max(int(steps), 2)
    dt = time_years / n
    sigma = max(volatility, 1e-12)
    up = math.exp(sigma * math.sqrt(dt))
    down = 1.0 / up
    denominator = up - down
    if abs(denominator) < 1e-15:
        return max(spot * math.exp(-dividend_yield * time_years)
                   - strike * math.exp(-rate * time_years), 0.0)
    probability = (math.exp((rate - dividend_yield) * dt) - down) / denominator
    probability = min(max(probability, 0.0), 1.0)
    discount = math.exp(-rate * dt)
    j = np.arange(n + 1, dtype=float)
    stock = spot * np.power(up, j) * np.power(down, n - j)
    values = np.maximum(stock - strike, 0.0)
    for level in range(n - 1, -1, -1):
        values = discount * (probability * values[1:] + (1.0 - probability) * values[:-1])
        j = np.arange(level + 1, dtype=float)
        stock = spot * np.power(up, j) * np.power(down, level - j)
        values = np.maximum(values, stock - strike)
    return float(max(values[0], spot - strike, 0.0))


def price_call_binomial(spot: float, strike: float, time_years: float, rate: float,
                        volatility: float, dividend_yield: float = 0.0,
                        steps: int = 200) -> OptionQuote:
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if volatility < 0:
        raise ValueError("volatility cannot be negative")
    intrinsic = max(spot - strike, 0.0)
    if time_years <= 0:
        delta = 1.0 if spot > strike else (0.5 if spot == strike else 0.0)
        return OptionQuote(intrinsic, intrinsic, 0.0, delta, 0.0, 0.0, 0.0, 0.0, "binomial")
    base = _price(spot, strike, time_years, rate, volatility, dividend_yield, steps)
    ds = max(spot * 0.001, 0.01)
    up = _price(spot + ds, strike, time_years, rate, volatility, dividend_yield, steps)
    down = _price(max(spot - ds, 1e-9), strike, time_years, rate, volatility, dividend_yield, steps)
    delta = (up - down) / (2.0 * ds)
    gamma = (up - 2.0 * base + down) / (ds * ds)
    day = 1.0 / 365.0
    shorter = _price(spot, strike, max(time_years - day, 0.0), rate, volatility, dividend_yield, steps)
    vega = _price(spot, strike, time_years, rate, volatility + 0.01, dividend_yield, steps) - base
    rho = _price(spot, strike, time_years, rate + 0.01, volatility, dividend_yield, steps) - base
    return OptionQuote(base, intrinsic, max(base - intrinsic, 0.0),
                       float(min(max(delta, 0.0), 1.0)), float(max(gamma, 0.0)),
                       float(shorter - base), float(vega), float(rho), "binomial")
