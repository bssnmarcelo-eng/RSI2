from __future__ import annotations

import numpy as np
import pandas as pd

GICS_SECTORS = ("XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU")
COUNTRIES = ("EWJ", "EWU", "EWG", "EWC", "EWA", "EWS", "EWH", "EWL", "EWP", "EWI", "FXI", "INDA", "EWZ", "EWW", "EWT", "EWY", "EZA", "TUR", "KSA")
LIQUID_TREND = ("SPY", "QQQ", "IWM", "EFA", "EEM", "IEF", "TLT", "LQD", "HYG", "GLD", "DBC", "UUP")


def _available(close: pd.DataFrame, symbols: tuple[str, ...]) -> list[str]:
    return [symbol for symbol in symbols if symbol in close]


def _normalize(signal: pd.DataFrame) -> pd.DataFrame:
    gross = signal.abs().sum(axis=1).replace(0, np.nan)
    return signal.div(gross, axis=0).fillna(0.0)


def _hold_at_frequency(weights: pd.DataFrame, frequency: str = "monthly") -> pd.DataFrame:
    periods = weights.index.to_period("M" if frequency == "monthly" else "W-FRI")
    period_series = pd.Series(periods.astype(str), index=weights.index)
    is_period_end = period_series.ne(period_series.shift(-1))
    return weights.where(is_period_end, axis=0).ffill().fillna(0.0)


def regime_panel(close: pd.DataFrame, indicators: pd.DataFrame | None = None) -> pd.DataFrame:
    aligned = pd.DataFrame(index=close.index)
    aligned["equity_trend"] = (close["SPY"] > close["SPY"].rolling(200, min_periods=150).mean()).astype(float)
    aligned["credit_trend"] = (close["HYG"] / close["IEF"]).pct_change(126).gt(0).astype(float)
    aligned["cyclical_leadership"] = (close["XLY"] / close["XLP"]).pct_change(126).gt(0).astype(float)
    if indicators is not None and not indicators.empty:
        # Economic timestamps can represent observation periods. A 21-session lag
        # prevents using a monthly value before a conservative release window.
        macro = indicators.reindex(close.index).ffill().shift(21)
        def observed_condition(values: pd.Series, condition: pd.Series) -> pd.Series:
            result = pd.Series(np.nan, index=close.index)
            available = values.notna()
            result.loc[available] = condition.loc[available].astype(float)
            return result

        claims = macro.get("jobless_claims", pd.Series(index=close.index, dtype=float))
        real_rate = macro.get("real_rate_10y", pd.Series(index=close.index, dtype=float))
        yield_curve = macro.get("yield_curve", pd.Series(index=close.index, dtype=float))
        ig_spread = macro.get("ig_spread", pd.Series(index=close.index, dtype=float))
        hy_spread = macro.get("hy_spread", pd.Series(index=close.index, dtype=float))
        m2 = macro.get("money_supply_m2", pd.Series(index=close.index, dtype=float))
        manufacturing = macro.get("ism_manufacturing", macro.get("pmi", pd.Series(index=close.index, dtype=float)))
        services = macro.get("ism_services", pd.Series(index=close.index, dtype=float))
        raw_conditions = {
            "real_rate": (real_rate, real_rate.lt(1.75) | real_rate.diff(63).lt(0)),
            "yield_curve": (yield_curve, yield_curve.gt(0) | yield_curve.diff(63).gt(0)),
            "ig_credit_spread": (ig_spread, ig_spread.lt(ig_spread.rolling(252, min_periods=60).median())),
            "hy_credit_spread": (hy_spread, hy_spread.lt(hy_spread.rolling(252, min_periods=60).median())),
            "money_supply": (m2, m2.pct_change(252).gt(0)),
            "ism_manufacturing": (manufacturing, manufacturing.gt(50)),
            "ism_services": (services, services.gt(50)),
            "claims": (claims, claims.lt(claims.rolling(52 * 5, min_periods=60).median())),
            "financial_conditions": (
                macro.get("financial_conditions", pd.Series(index=close.index, dtype=float)),
                macro.get("financial_conditions", pd.Series(index=close.index, dtype=float)).lt(0),
            ),
            "activity": (
                macro.get("activity", pd.Series(index=close.index, dtype=float)),
                macro.get("activity", pd.Series(index=close.index, dtype=float)).gt(-0.7),
            ),
        }
        for name, (values, condition) in raw_conditions.items():
            aligned[name] = observed_condition(values, condition)
    aligned["score"] = aligned.mean(axis=1)
    aligned["risk_on"] = aligned["score"] >= 0.60
    aligned["risk_off"] = aligned["score"] < 0.40
    return aligned


def macro_leading_allocation(close: pd.DataFrame, regime: pd.DataFrame) -> pd.DataFrame:
    """Monthly long-only allocation driven by lagged leading data and market regime."""
    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    growth = _available(close, ("QQQ", "SPY", "MDY", "IWM"))
    defensive = _available(close, ("IEF", "TLT", "GLD", "BIL"))
    growth_score = close[growth].pct_change(252) + 0.5 * close[growth].pct_change(126)
    defensive_score = close[defensive].pct_change(126)
    growth_winner = growth_score.fillna(-np.inf).idxmax(axis=1)
    defensive_winner = defensive_score.fillna(-np.inf).idxmax(axis=1)
    for symbol in growth:
        weights.loc[regime["risk_on"] & growth_winner.eq(symbol), symbol] = 1.0
    for symbol in defensive:
        weights.loc[~regime["risk_on"] & defensive_winner.eq(symbol), symbol] = 1.0
    return _hold_at_frequency(weights)


def gics_sector_long_short(close: pd.DataFrame, regime: pd.DataFrame) -> pd.DataFrame:
    """Monthly GICS relative momentum: leaders long, liquid laggards short."""
    sectors = _available(close, GICS_SECTORS)
    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    score = close[sectors].pct_change(252) - close[sectors].pct_change(21)
    ranks = score.rank(axis=1, ascending=False, method="first")
    trend = close[sectors] > close[sectors].rolling(200, min_periods=150).mean()
    for symbol in sectors:
        long_gate = (ranks[symbol] <= 3) & trend[symbol]
        weights.loc[long_gate & regime["risk_on"], symbol] = 1.0 / 3.0
        weights.loc[long_gate & ~regime["risk_on"], symbol] = 1.0 / 6.0
        short_gate = (ranks[symbol] >= len(sectors) - 1) & ~trend[symbol] & ~regime["risk_on"]
        weights.loc[short_gate, symbol] = -0.25
    return _hold_at_frequency(weights)


def country_momentum(close: pd.DataFrame, regime: pd.DataFrame) -> pd.DataFrame:
    """Monthly country momentum, long the four strongest positive-trend markets."""
    countries = _available(close, COUNTRIES)
    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    score = close[countries].pct_change(252) + 0.5 * close[countries].pct_change(126) - close[countries].pct_change(21)
    ranks = score.rank(axis=1, ascending=False, method="first")
    trend = close[countries] > close[countries].rolling(200, min_periods=150).mean()
    for symbol in countries:
        weights.loc[(ranks[symbol] <= 3) & trend[symbol] & ~regime["risk_off"], symbol] = 1.0 / 3.0
    if "BIL" in close:
        idle = weights.abs().sum(axis=1).eq(0)
        weights.loc[idle, "BIL"] = 1.0
    return _hold_at_frequency(weights)


def multi_asset_trend_long_short(close: pd.DataFrame) -> pd.DataFrame:
    """Slow 6/12-month trend across liquid ETFs; direct shorts on negative trends."""
    symbols = _available(close, LIQUID_TREND)
    returns = close[symbols].pct_change(fill_method=None)
    vol = returns.rolling(63, min_periods=40).std() * np.sqrt(252)
    trend = 0.5 * np.sign(close[symbols].pct_change(126)) + 0.5 * np.sign(close[symbols].pct_change(252))
    raw = trend.div(vol.clip(lower=0.06))
    return _hold_at_frequency(_normalize(raw))


def covel_style_trend(close: pd.DataFrame) -> pd.DataFrame:
    """Public, classic trend-following proxy; not Covel's proprietary rules.

    Positions enter on a 55-session Donchian breakout and exit on the opposite
    20-session channel. Active markets are scaled by inverse 20-session realized
    volatility, capped at 25% each, and refreshed weekly. All channels are shifted
    one session so a signal never observes future prices.
    """
    symbols = _available(close, LIQUID_TREND)
    positions = pd.DataFrame(0.0, index=close.index, columns=symbols)
    for symbol in symbols:
        price = close[symbol]
        entry_high = price.rolling(55, min_periods=55).max().shift(1)
        entry_low = price.rolling(55, min_periods=55).min().shift(1)
        exit_high = price.rolling(20, min_periods=20).max().shift(1)
        exit_low = price.rolling(20, min_periods=20).min().shift(1)
        state = 0.0
        values: list[float] = []
        for date, value in price.items():
            if pd.isna(value):
                state = 0.0
            elif state > 0 and value < exit_low.loc[date]:
                state = 0.0
            elif state < 0 and value > exit_high.loc[date]:
                state = 0.0
            elif state == 0 and value > entry_high.loc[date]:
                state = 1.0
            elif state == 0 and value < entry_low.loc[date]:
                state = -1.0
            values.append(state)
        positions[symbol] = values

    returns = close[symbols].pct_change(fill_method=None)
    annual_vol = returns.rolling(20, min_periods=20).std() * np.sqrt(252)
    inverse_vol = positions.div(annual_vol.clip(lower=0.06))
    normalized = _normalize(inverse_vol).clip(-0.25, 0.25)
    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    weights.loc[:, symbols] = normalized
    return _hold_at_frequency(weights, "weekly")


def us_factor_rotation(close: pd.DataFrame, regime: pd.DataFrame) -> pd.DataFrame:
    """Monthly 3/6/12-month relative strength across liquid US styles and factors."""
    growth = _available(close, ("SPY", "QQQ", "VUG", "MTUM", "QUAL", "XLK", "MDY", "IWM", "RSP"))
    defensive = _available(close, ("USMV", "XLU", "XLP", "IEF", "GLD", "BIL"))
    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    score = (
        close[growth].pct_change(252)
        + 0.5 * close[growth].pct_change(126)
        - 0.25 * close[growth].pct_change(21)
    )
    ranks = score.rank(axis=1, ascending=False, method="first")
    positive = close[growth] > close[growth].rolling(200, min_periods=150).mean()
    for symbol in growth:
        weights.loc[(ranks[symbol] <= 3) & positive[symbol] & ~regime["risk_off"], symbol] = 1.0 / 3.0
    defensive_score = close[defensive].pct_change(126)
    defensive_rank = defensive_score.rank(axis=1, ascending=False, method="first")
    idle = weights.abs().sum(axis=1).eq(0)
    for symbol in defensive:
        weights.loc[idle & defensive_rank[symbol].eq(1), symbol] = 1.0
    return _hold_at_frequency(weights)


def technical_breakout(close: pd.DataFrame, regime: pd.DataFrame) -> pd.DataFrame:
    """Weekly medium-term Donchian breakout with exits at the 13-week channel."""
    symbols = _available(close, ("SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "GLD"))
    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    for symbol in symbols:
        upper = close[symbol].rolling(126, min_periods=100).max().shift(1)
        lower = close[symbol].rolling(126, min_periods=100).min().shift(1)
        exit_high = close[symbol].rolling(63, min_periods=50).max().shift(1)
        exit_low = close[symbol].rolling(63, min_periods=50).min().shift(1)
        state = pd.Series(np.nan, index=close.index)
        state.loc[close[symbol] > upper] = 1.0
        state.loc[close[symbol] < lower] = -1.0
        state.loc[(close[symbol] < exit_low) & (state.shift().ffill() > 0)] = 0.0
        state.loc[(close[symbol] > exit_high) & (state.shift().ffill() < 0)] = 0.0
        held = state.ffill().fillna(0.0)
        # Short leg restricted to the most liquid equity index ETFs.
        if symbol not in {"SPY", "QQQ", "IWM", "EFA", "EEM"}:
            held = held.clip(lower=0)
        weights[symbol] = held / len(symbols)
    return _hold_at_frequency(weights, "weekly")


def credit_cycle(close: pd.DataFrame, regime: pd.DataFrame) -> pd.DataFrame:
    """Monthly credit-risk sleeve using HYG/LQD leadership and financial conditions."""
    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    ratio = close["HYG"] / close["LQD"]
    improving = ratio.pct_change(126).gt(0) & ratio.gt(ratio.rolling(200, min_periods=150).mean())
    weights.loc[improving & ~regime["risk_off"], "HYG"] = 0.70
    weights.loc[improving & ~regime["risk_off"], "FLOT"] = 0.30
    weights.loc[~improving, "IEF"] = 0.60
    weights.loc[~improving, "LQD"] = 0.40
    severe = regime["risk_off"] & ratio.lt(ratio.rolling(200, min_periods=150).mean())
    weights.loc[severe, ["IEF", "LQD"]] = (0.70, 0.10)
    weights.loc[severe, "HYG"] = -0.20
    return _hold_at_frequency(weights)


def strategy_signals(
    close: pd.DataFrame, indicators: pd.DataFrame | None = None
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    regime = regime_panel(close, indicators)
    signals = {
        "Macro Leading": macro_leading_allocation(close, regime),
        "US Factor Rotation": us_factor_rotation(close, regime),
        "GICS Long/Short": gics_sector_long_short(close, regime),
        "Country Momentum": country_momentum(close, regime),
        "Multi-Asset Trend": multi_asset_trend_long_short(close),
        "Covel-Style Trend (Public Proxy)": covel_style_trend(close),
        "Technical Breakout": technical_breakout(close, regime),
        "Credit Cycle": credit_cycle(close, regime),
    }
    return signals, regime
