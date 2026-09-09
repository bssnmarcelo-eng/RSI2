"""Live Yahoo Finance call-chain selection for the RSI2 diagonal structure."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DiagonalProposal:
    ticker: str
    yahoo_symbol: str
    spot: float
    quote_time: pd.Timestamp | None
    short_expiration: pd.Timestamp
    long_expiration: pd.Timestamp
    short_dte_business: int
    long_dte_business: int
    long_call: dict
    short_call: dict
    longs_per_short: int
    mfe_20d: float
    mfe_60d: float
    short_target: float
    target_60d: float
    packages: int
    long_quantity: int
    short_quantity: int
    debit_per_package: float
    long_cost: float
    short_credit: float
    entry_commissions: float
    total_debit: float
    risk_budget: float
    required_target: float
    required_move: float
    target_value: float
    long_target_profit: float
    short_target_profit: float
    target_profit: float
    reward_risk: float
    min_reward_risk: float
    qualifies: bool


def yahoo_symbol(ticker: str) -> str:
    """Translate the common Norgate class-share notation to Yahoo's notation."""
    return ticker.strip().upper().replace(".", "-")


def business_dte(expiration, as_of=None) -> int:
    start = pd.Timestamp(as_of or date.today()).normalize()
    end = pd.Timestamp(expiration).normalize()
    return max(int(np.busday_count(start.date(), end.date())), 0)


def is_standard_monthly_expiration(expiration) -> bool:
    """Return True for a third Friday, including its holiday-adjusted Thursday."""
    expiry = pd.Timestamp(expiration).date()
    is_third_friday = expiry.weekday() == 4 and 15 <= expiry.day <= 21
    next_day = expiry + timedelta(days=1)
    is_holiday_thursday = (
        expiry.weekday() == 3
        and next_day.weekday() == 4
        and 15 <= next_day.day <= 21
    )
    return is_third_friday or is_holiday_thursday


def select_expiration(
    expirations: Iterable[str],
    target_business_days: int,
    *,
    as_of=None,
    after=None,
) -> str:
    """Return the listed expiration closest to a target business-day DTE."""
    candidates = []
    after_ts = pd.Timestamp(after).normalize() if after is not None else None
    for value in expirations:
        expiry = pd.Timestamp(value).normalize()
        if not is_standard_monthly_expiration(expiry):
            continue
        dte = business_dte(expiry, as_of)
        if dte <= 0 or (after_ts is not None and expiry <= after_ts):
            continue
        candidates.append((abs(dte - target_business_days), dte, expiry, str(value)))
    if not candidates:
        raise ValueError("Nenhum vencimento futuro compatível foi encontrado no Yahoo Finance.")
    return min(candidates, key=lambda item: (item[0], item[1]))[3]


def _numeric_row(row: pd.Series) -> dict:
    result = row.to_dict()
    for name in ("strike", "bid", "ask", "lastPrice", "openInterest", "volume", "impliedVolatility"):
        value = pd.to_numeric(result.get(name), errors="coerce")
        result[name] = float(value) if pd.notna(value) else float("nan")
    result["mid"] = (result["bid"] + result["ask"]) / 2.0
    return result


def _select_call(calls: pd.DataFrame, target_strike: float) -> dict:
    required = {"strike", "bid", "ask"}
    if calls.empty or not required.issubset(calls.columns):
        raise ValueError("Cadeia de calls vazia ou sem bid/ask e strike.")
    eligible = calls.copy()
    eligible["strike"] = pd.to_numeric(eligible["strike"], errors="coerce")
    eligible["bid"] = pd.to_numeric(eligible["bid"], errors="coerce")
    eligible["ask"] = pd.to_numeric(eligible["ask"], errors="coerce")
    eligible["openInterest"] = pd.to_numeric(
        eligible.get("openInterest", pd.Series(index=eligible.index, dtype=float)),
        errors="coerce",
    ).fillna(0)
    eligible = eligible.loc[
        eligible["strike"].notna()
        & eligible["bid"].notna()
        & eligible["ask"].notna()
        & (eligible["bid"] > 0)
        & (eligible["ask"] > 0)
        & (eligible["openInterest"] > 0)
    ].copy()
    if eligible.empty:
        raise ValueError("Nenhuma call com preço executável e open interest positivo.")
    eligible["distance"] = (eligible["strike"] - target_strike).abs()
    # For an equal distance, prefer the strike at/above the MFE target on the short leg.
    eligible["below_target"] = eligible["strike"] < target_strike
    eligible = eligible.sort_values(
        ["distance", "below_target", "openInterest"],
        ascending=[True, True, False],
    )
    return _numeric_row(eligible.iloc[0])


def build_diagonal_proposal(
    *,
    ticker: str,
    spot: float,
    short_expiration,
    long_expiration,
    short_calls: pd.DataFrame,
    long_calls: pd.DataFrame,
    mfe_20d: float,
    mfe_60d: float,
    capital: float = 100_000.0,
    risk_pct: float = 6.0,
    min_reward_risk: float = 3.0,
    commission_per_contract: float = 0.65,
    longs_per_short: int = 2,
    as_of=None,
    quote_time=None,
) -> DiagonalProposal:
    """Select the two Yahoo calls and size ratio packages."""
    if spot <= 0 or capital <= 0 or not 0 < risk_pct <= 100:
        raise ValueError("Preço, patrimônio e percentual de risco devem ser positivos.")
    if longs_per_short not in (1, 2):
        raise ValueError("A proporção deve ser 1:1 ou 2:1.")
    mfe_20d = max(float(mfe_20d), 0.0)
    mfe_60d = max(float(mfe_60d), 0.0)
    short_target = spot * (1.0 + mfe_20d)
    target_60d = spot * (1.0 + mfe_60d)
    long_call = _select_call(long_calls, spot)
    short_call = _select_call(short_calls, short_target)

    multiplier = 100
    package_commission = (longs_per_short + 1) * max(float(commission_per_contract), 0.0)
    target_value_per_package = (
        longs_per_short * multiplier * max(target_60d - long_call["strike"], 0.0)
    )
    debit_per_package = (
        (longs_per_short * long_call["mid"] - short_call["mid"]) * multiplier
        + package_commission
    )
    if debit_per_package <= 0:
        raise ValueError("A combinação encontrada não possui débito líquido positivo.")
    risk_budget = capital * risk_pct / 100.0
    required_target = long_call["strike"] + (
        debit_per_package * (min_reward_risk + 1.0)
        / (longs_per_short * multiplier)
    )
    required_move = required_target / spot - 1.0
    packages = int(risk_budget // debit_per_package)
    long_quantity = packages * longs_per_short
    short_quantity = packages
    long_cost = long_quantity * long_call["mid"] * multiplier
    short_credit = short_quantity * short_call["mid"] * multiplier
    entry_commissions = (
        (long_quantity + short_quantity) * max(float(commission_per_contract), 0.0)
    )
    total_debit = long_cost - short_credit + entry_commissions
    target_profit_per_package = target_value_per_package - debit_per_package
    target_value = packages * target_value_per_package
    long_target_profit = target_value - long_cost
    short_target_profit = short_credit
    target_profit = long_target_profit + short_target_profit - entry_commissions
    reward_risk = target_profit_per_package / debit_per_package
    qualifies = packages > 0 and np.isfinite(reward_risk) and reward_risk >= min_reward_risk

    return DiagonalProposal(
        ticker=ticker,
        yahoo_symbol=yahoo_symbol(ticker),
        spot=float(spot),
        quote_time=pd.Timestamp(quote_time) if quote_time is not None else None,
        short_expiration=pd.Timestamp(short_expiration).normalize(),
        long_expiration=pd.Timestamp(long_expiration).normalize(),
        short_dte_business=business_dte(short_expiration, as_of),
        long_dte_business=business_dte(long_expiration, as_of),
        long_call=long_call,
        short_call=short_call,
        longs_per_short=longs_per_short,
        mfe_20d=mfe_20d,
        mfe_60d=mfe_60d,
        short_target=short_target,
        target_60d=target_60d,
        packages=packages,
        long_quantity=long_quantity,
        short_quantity=short_quantity,
        debit_per_package=debit_per_package,
        long_cost=long_cost,
        short_credit=short_credit,
        entry_commissions=entry_commissions,
        total_debit=total_debit,
        risk_budget=risk_budget,
        required_target=required_target,
        required_move=required_move,
        target_value=target_value,
        long_target_profit=long_target_profit,
        short_target_profit=short_target_profit,
        target_profit=target_profit,
        reward_risk=float(reward_risk),
        min_reward_risk=float(min_reward_risk),
        qualifies=bool(qualifies),
    )


def _fetch_yahoo_market(ticker: str) -> dict:
    """Download the selected Yahoo chains once and return proposal inputs."""
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - depends on optional runtime package
        raise ImportError("Instale o pacote opcional com `pip install yfinance`.") from exc

    symbol = yahoo_symbol(ticker)
    instrument = yf.Ticker(symbol)
    expirations = list(instrument.options)
    if not expirations:
        raise ValueError(f"O Yahoo Finance não retornou vencimentos de opções para {symbol}.")
    today = date.today()
    short_expiration = select_expiration(expirations, 20, as_of=today)
    long_expiration = select_expiration(
        expirations,
        60,
        as_of=today,
        after=short_expiration,
    )
    short_chain = instrument.option_chain(short_expiration)
    long_chain = instrument.option_chain(long_expiration)
    underlying = getattr(long_chain, "underlying", None) or getattr(short_chain, "underlying", None) or {}
    spot = pd.to_numeric(underlying.get("regularMarketPrice"), errors="coerce")
    if pd.isna(spot) or float(spot) <= 0:
        history = instrument.history(period="5d", auto_adjust=False)
        if history.empty or "Close" not in history:
            raise ValueError(f"O Yahoo Finance não retornou o preço atual de {symbol}.")
        spot = float(pd.to_numeric(history["Close"], errors="coerce").dropna().iloc[-1])
    market_time = underlying.get("regularMarketTime")
    quote_time = (
        pd.Timestamp(int(market_time), unit="s", tz="UTC")
        if market_time is not None
        else None
    )
    return {
        "ticker": ticker,
        "spot": float(spot),
        "short_expiration": short_expiration,
        "long_expiration": long_expiration,
        "short_calls": short_chain.calls,
        "long_calls": long_chain.calls,
        "as_of": today,
        "quote_time": quote_time,
    }


def fetch_yahoo_diagonal(
    ticker: str,
    *,
    mfe_20d: float,
    mfe_60d: float,
    capital: float = 100_000.0,
    risk_pct: float = 6.0,
    min_reward_risk: float = 3.0,
    commission_per_contract: float = 0.65,
    longs_per_short: int = 2,
) -> DiagonalProposal:
    """Download the Yahoo chains and build one ratio proposal."""
    market = _fetch_yahoo_market(ticker)
    return build_diagonal_proposal(
        **market,
        mfe_20d=mfe_20d,
        mfe_60d=mfe_60d,
        capital=capital,
        risk_pct=risk_pct,
        min_reward_risk=min_reward_risk,
        commission_per_contract=commission_per_contract,
        longs_per_short=longs_per_short,
    )


def fetch_yahoo_diagonals(
    ticker: str,
    *,
    mfe_20d: float,
    mfe_60d: float,
    capital: float = 100_000.0,
    risk_pct: float = 6.0,
    min_reward_risk: float = 3.0,
    commission_per_contract: float = 0.65,
) -> tuple[DiagonalProposal, DiagonalProposal]:
    """Build 2:1 and 1:1 alternatives from the same Yahoo chain selections."""
    market = _fetch_yahoo_market(ticker)
    common = {
        **market,
        "mfe_20d": mfe_20d,
        "mfe_60d": mfe_60d,
        "capital": capital,
        "risk_pct": risk_pct,
        "min_reward_risk": min_reward_risk,
        "commission_per_contract": commission_per_contract,
    }
    ratio_2_1 = build_diagonal_proposal(**common, longs_per_short=2)
    ratio_1_1 = build_diagonal_proposal(**common, longs_per_short=1)
    return ratio_2_1, ratio_1_1
