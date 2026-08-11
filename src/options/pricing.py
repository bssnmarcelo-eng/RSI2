"""Pricing-model dispatcher."""
from __future__ import annotations

from src.types import OptionPricingModel

from .binomial import price_call_binomial
from .black_scholes import price_call_bsm
from .types import OptionQuote


def price_call(spot: float, strike: float, time_years: float, rate: float,
               volatility: float, dividend_yield: float = 0.0,
               model: OptionPricingModel | str = OptionPricingModel.BLACK_SCHOLES,
               binomial_steps: int = 200) -> OptionQuote:
    selected = OptionPricingModel(model)
    if selected == OptionPricingModel.BINOMIAL:
        return price_call_binomial(spot, strike, time_years, rate, volatility,
                                   dividend_yield, binomial_steps)
    return price_call_bsm(spot, strike, time_years, rate, volatility, dividend_yield)
