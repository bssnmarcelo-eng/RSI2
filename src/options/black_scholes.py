"""Black-Scholes-Merton pricing for a European call with continuous yield."""
from __future__ import annotations

import math

from .types import OptionQuote


def _cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def price_call_bsm(
    spot: float,
    strike: float,
    time_years: float,
    rate: float,
    volatility: float,
    dividend_yield: float = 0.0,
) -> OptionQuote:
    if spot <= 0 or strike <= 0:
        raise ValueError("spot and strike must be positive")
    if volatility < 0:
        raise ValueError("volatility cannot be negative")

    intrinsic = max(spot - strike, 0.0)
    if time_years <= 0:
        delta = 1.0 if spot > strike else (0.5 if spot == strike else 0.0)
        return OptionQuote(intrinsic, intrinsic, 0.0, delta, 0.0, 0.0, 0.0, 0.0, "black_scholes")

    sigma = max(volatility, 1e-12)
    sqrt_t = math.sqrt(time_years)
    d1 = (math.log(spot / strike) + (rate - dividend_yield + 0.5 * sigma * sigma) * time_years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    discount_r = math.exp(-rate * time_years)
    discount_q = math.exp(-dividend_yield * time_years)
    nd1 = _cdf(d1)
    nd2 = _cdf(d2)
    price = max(spot * discount_q * nd1 - strike * discount_r * nd2, intrinsic, 0.0)

    pdf_d1 = _pdf(d1)
    delta = discount_q * nd1
    gamma = discount_q * pdf_d1 / (spot * sigma * sqrt_t)
    theta_year = (-(spot * discount_q * pdf_d1 * sigma) / (2.0 * sqrt_t)
                  - rate * strike * discount_r * nd2
                  + dividend_yield * spot * discount_q * nd1)
    return OptionQuote(
        price=price,
        intrinsic=intrinsic,
        time_value=max(price - intrinsic, 0.0),
        delta=delta,
        gamma=gamma,
        theta=theta_year / 365.0,
        vega=spot * discount_q * pdf_d1 * sqrt_t / 100.0,
        rho=strike * time_years * discount_r * nd2 / 100.0,
        model="black_scholes",
    )
