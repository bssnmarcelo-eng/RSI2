"""Synthetic option pricing and portfolio-overlay utilities."""

from .pricing import price_call
from .types import OptionQuote

__all__ = ["OptionQuote", "price_call"]
