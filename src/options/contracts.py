"""Deterministic synthetic strike and monthly-expiration rules."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

import pandas as pd


def select_strike(
    spot: float,
    mode: str = "exact_atm",
    interval: float = 1.0,
    otm_pct: float = 10.0,
) -> float:
    if spot <= 0:
        raise ValueError("spot must be positive")
    if mode == "exact_atm":
        return float(spot)
    if interval <= 0:
        raise ValueError("strike interval must be positive")
    if mode == "rounded":
        target = spot
    elif mode == "otm_pct":
        if otm_pct <= 0:
            raise ValueError("OTM percentage must be positive")
        target = spot * (1.0 + otm_pct / 100.0)
    else:
        raise ValueError(f"unsupported strike mode: {mode}")
    return max(float(round(target / interval) * interval), interval)


def _third_friday(year: int, month: int) -> date:
    first = date(year, month, 1)
    offset = (calendar.FRIDAY - first.weekday()) % 7
    return first + timedelta(days=offset + 14)


def select_expiration(entry_date, target_dte: int = 45) -> pd.Timestamp:
    entry = pd.Timestamp(entry_date).normalize()
    for offset in range(25):
        month0 = entry.month - 1 + offset
        expiry = pd.Timestamp(_third_friday(entry.year + month0 // 12, month0 % 12 + 1))
        if entry.tzinfo is not None:
            expiry = expiry.tz_localize(entry.tzinfo)
        if (expiry - entry).days >= target_dte:
            return expiry
    raise RuntimeError("could not construct a synthetic monthly expiration")


def year_fraction(as_of, expiration) -> float:
    return max((pd.Timestamp(expiration) - pd.Timestamp(as_of)).total_seconds()
               / (365.0 * 86_400.0), 0.0)
