"""Small, dependency-light helper functions shared across modules."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .types import CommissionModel, CostConfig


def commission_for(costs: CostConfig, shares: float, notional: float) -> float:
    """Commission for a single order/fill under the configured model.

    * GENERIC:    ``commission_fixed + commission_pct * notional``.
    * IBKR_FIXED: ``clamp(shares * per_share, min=min_per_order,
                          max=max_pct * trade_value)`` — the 1%-of-trade cap is
                  applied last, so it can pull the charge below the $1 minimum on
                  very small orders (matching IBKR's stated rule).
    """
    shares = abs(shares)
    notional = abs(notional)
    if costs.model == CommissionModel.IBKR_FIXED:
        comm = shares * costs.ibkr_per_share
        comm = max(comm, costs.ibkr_min_per_order)
        comm = min(comm, costs.ibkr_max_pct * notional)
        return comm
    return costs.commission_fixed + costs.commission_pct * notional


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Divide, returning ``default`` instead of raising/inf on a zero denominator."""
    if denominator is None or denominator == 0 or pd.isna(denominator):
        return default
    return numerator / denominator


def periods_per_year(index: pd.DatetimeIndex) -> float:
    """Estimate how many bars occur per year for a given DatetimeIndex.

    Frequency-agnostic: derived from the actual elapsed time spanned by the data
    and the number of bars, so it works for daily *and* intraday candles. Used to
    annualise Sharpe / Sortino / volatility figures.
    """
    if index is None or len(index) < 3:
        return 252.0  # sensible daily fallback
    span = index[-1] - index[0]
    span_years = span.total_seconds() / (365.25 * 24 * 3600)
    if span_years <= 0:
        return 252.0
    return max((len(index) - 1) / span_years, 1.0)


def years_between(start, end) -> float:
    """Fractional number of years between two timestamps (>= a tiny positive)."""
    delta = pd.Timestamp(end) - pd.Timestamp(start)
    return max(delta.total_seconds() / (365.25 * 24 * 3600), 1e-9)


def to_series(values, index) -> pd.Series:
    """Build a float Series aligned to ``index`` (helper for chart inputs)."""
    return pd.Series(np.asarray(values, dtype=float), index=index)


def fmt_pct(x: float, decimals: int = 2) -> str:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "—"
    return f"{x * 100:.{decimals}f}%"


def fmt_money(x: float, decimals: int = 2) -> str:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "—"
    return f"{x:,.{decimals}f}"


def fmt_num(x: float, decimals: int = 2) -> str:
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "—"
    return f"{x:.{decimals}f}"
