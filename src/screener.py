"""Market screening: scan a universe for tickers currently firing the entry signal.

For each ticker the strategy's own :func:`build_signal_frame` is run so the screen
is IDENTICAL to the backtest entry condition (RSI(period) < threshold AND
percentile hammer, plus the optional ATR and price filters). A "hit" is a ticker
whose ``entry_signal`` is True on the evaluated candle.

Both screening entry points use local Norgate data. ``run_screen_norgate`` also
allows the caller to choose the adjustment convention.
"""
from __future__ import annotations

import datetime
from dataclasses import replace
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from . import norgate_loader
from .backtest_engine import BacktestEngine, BacktestResult, build_signal_frame
from .types import StrategyConfig

# UI index label -> current-constituent Norgate watchlist.
_NORGATE_WATCHLISTS = {
    "Nasdaq 100": "Nasdaq 100",
    "S&P 500": "S&P 500",
    "S&P 400 (MidCap)": "S&P MidCap 400",
    "S&P 600 (SmallCap)": "S&P SmallCap 600",
    "S&P 1500": "S&P Composite 1500",
}
INDICES: List[str] = ["Nasdaq 100", "S&P 500", "S&P 400 (MidCap)",
                      "S&P 600 (SmallCap)", "S&P 1500"]

# Timeframe label -> (Norgate frequency label, lookback years).
TIMEFRAMES: Dict[str, Tuple[str, int]] = {
    "Daily": ("Diário", 1),
    "Weekly": ("Semanal", 5),
    "Monthly": ("Mensal", 10),
}

def get_constituents(index: str) -> List[str]:
    """Return current constituents from the corresponding Norgate watchlist."""
    if index not in _NORGATE_WATCHLISTS:
        raise ValueError(f"Unknown index: {index}")
    watchlist = _NORGATE_WATCHLISTS[index]
    symbols = norgate_loader.get_watchlist_symbols(watchlist)
    if not symbols:
        raise RuntimeError(
            f"Norgate watchlist '{watchlist}' is unavailable or has no constituents."
        )
    return symbols


def fetch_ohlc(tickers: List[str], frequency_label: str, lookback_years: int,
               min_bars: int,
               progress: Optional[Callable[[float], None]] = None) -> Dict[str, pd.DataFrame]:
    """Load adjusted OHLC for many tickers from the local Norgate database."""
    end = pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(years=lookback_years)
    data, _warnings, _skipped = norgate_loader.fetch_many(
        tickers,
        adjustment_label="Total Return (splits + dividendos)",
        start_date=start.date().isoformat(),
        end_date=end.date().isoformat(),
        min_bars=min_bars,
        frequency_label=frequency_label,
        progress=progress,
    )
    return data


def _min_bars(cfg: StrategyConfig) -> int:
    need = cfg.rsi_period + 3
    if cfg.patterns.hammer.use_atr_filter:
        need = max(need, cfg.patterns.hammer.atr_period + 3)
    return max(need, 5)


def evaluate(
    df: pd.DataFrame,
    cfg: StrategyConfig,
    ignore_last: bool,
    sma_price_filter: str = "any",
    sma_slope_filter: str = "any",
) -> Optional[dict]:
    """Run the entry logic and return the evaluated candle's state (or None)."""
    if sma_price_filter not in {"any", "above", "below"}:
        raise ValueError(f"Filtro de posição da MM200 inválido: {sma_price_filter}")
    if sma_slope_filter not in {"any", "rising", "falling"}:
        raise ValueError(f"Filtro de inclinação da MM200 inválido: {sma_slope_filter}")
    if len(df) < _min_bars(cfg):
        return None
    sf = build_signal_frame(df, cfg)
    pos = -2 if (ignore_last and len(sf) >= 2) else -1
    row = sf.iloc[pos]
    sma = pd.to_numeric(sf["close"], errors="coerce").rolling(200, min_periods=200).mean()
    sma_200 = float(sma.iloc[pos]) if pd.notna(sma.iloc[pos]) else float("nan")
    previous_sma = float(sma.iloc[pos - 1]) if len(sma) >= abs(pos - 1) and pd.notna(sma.iloc[pos - 1]) else float("nan")
    close = float(row["close"])
    distance_sma_200 = close / sma_200 - 1 if pd.notna(sma_200) and sma_200 else float("nan")
    sma_200_slope = sma_200 / previous_sma - 1 if pd.notna(sma_200) and pd.notna(previous_sma) and previous_sma else float("nan")
    price_filter_match = (
        sma_price_filter == "any"
        or (
            pd.notna(sma_200)
            and ((sma_price_filter == "above" and close > sma_200) or (sma_price_filter == "below" and close < sma_200))
        )
    )
    slope_filter_match = (
        sma_slope_filter == "any"
        or (
            pd.notna(sma_200_slope)
            and ((sma_slope_filter == "rising" and sma_200_slope > 0) or (sma_slope_filter == "falling" and sma_200_slope < 0))
        )
    )
    rng = float(row["high"] - row["low"])
    # Effective body percentile: how far the body's lowest point sits from the high,
    # as a fraction of the range. Equals the smallest `percentile` at which this
    # candle would still qualify as a hammer (lower = body hugs the high).
    body_low = min(float(row["open"]), float(row["close"]))
    body_pct = (float(row["high"]) - body_low) / rng if rng > 0 else float("nan")
    return {
        "date": sf.index[pos],
        "close": close,
        "rsi": float(row["rsi"]) if pd.notna(row["rsi"]) else float("nan"),
        "body_percentile": body_pct,
        "range": rng,
        "atr_multiple": (
            float(row["atr_mult"]) if pd.notna(row["atr_mult"]) else float("nan")
        ),
        "atr_period": int(cfg.patterns.hammer.atr_period),
        "pattern": str(row["pattern"]),
        "signal": bool(row["entry_signal"]),
        "sma_200": sma_200,
        "distance_sma_200": distance_sma_200,
        "sma_200_slope": sma_200_slope,
        "price_vs_sma_200": "above" if pd.notna(sma_200) and close > sma_200 else "below" if pd.notna(sma_200) and close < sma_200 else "equal_or_unavailable",
        "sma_filter_match": bool(price_filter_match and slope_filter_match),
    }


def _screen_data(ohlc: Dict[str, pd.DataFrame], tickers: List[str],
                 cfg: StrategyConfig, ignore_last: bool,
                 sma_price_filter: str = "any",
                 sma_slope_filter: str = "any") -> Tuple[pd.DataFrame, int]:
    """Run :func:`evaluate` on each ticker's OHLC and collect the hits.

    Returns ``(hits_df, n_scanned)`` where *n_scanned* counts tickers that had
    enough data to be evaluated. ``hits_df`` is sorted by RSI ascending
    (most oversold first).
    """
    hits: List[dict] = []
    scanned = 0
    for t in tickers:
        df = ohlc.get(t)
        if df is None:
            continue
        ev = evaluate(df, cfg, ignore_last, sma_price_filter, sma_slope_filter)
        if ev is None:
            continue
        scanned += 1
        if ev["signal"] and ev["sma_filter_match"]:
            hits.append({"ticker": t, "date": ev["date"], "close": ev["close"],
                         "rsi": ev["rsi"], "body_percentile": ev["body_percentile"],
                         "range": ev["range"], "atr_multiple": ev["atr_multiple"],
                         "atr_period": ev["atr_period"], "pattern": ev["pattern"],
                         "sma_200": ev["sma_200"],
                         "distance_sma_200": ev["distance_sma_200"],
                         "sma_200_slope": ev["sma_200_slope"],
                         "price_vs_sma_200": ev["price_vs_sma_200"]})
    hits_df = pd.DataFrame(hits)
    if not hits_df.empty:
        hits_df = hits_df.sort_values("rsi").reset_index(drop=True)
    return hits_df, scanned


def run_screen(tickers: List[str], timeframe: str, cfg: StrategyConfig,
               ignore_last: bool = True,
               progress: Optional[Callable[[float], None]] = None,
               sma_price_filter: str = "any",
               sma_slope_filter: str = "any") -> Tuple[pd.DataFrame, int, int]:
    """Screen ``tickers`` on ``timeframe`` via Norgate. Returns hits/scanned/errors.

    ``hits_df`` rows are tickers whose entry_signal is True on the evaluated candle,
    sorted by RSI ascending (most oversold first).
    """
    frequency_label, lookback_years = TIMEFRAMES[timeframe]
    ohlc = fetch_ohlc(
        tickers, frequency_label, lookback_years, _min_bars(cfg), progress=progress
    )
    hits_df, scanned = _screen_data(
        ohlc, tickers, cfg, ignore_last, sma_price_filter, sma_slope_filter
    )
    return hits_df, scanned, len(tickers) - scanned


# ── Norgate path ──────────────────────────────────────────────────────────────

# Screening timeframe -> (norgate frequency label, warmup lookback in days). The
# lookback is generous enough to calculate MM200 and its one-bar slope.
NORGATE_TIMEFRAMES: Dict[str, str] = {
    "Daily":   "Diário",
    "Weekly":  "Semanal",
    "Monthly": "Mensal",
}

_NORGATE_LOOKBACK_DAYS: Dict[str, int] = {
    "Daily":   400,
    "Weekly":  365 * 4,
    "Monthly": 365 * 20,
}

SMA_PRICE_FILTERS: Dict[str, str] = {
    "Qualquer posição": "any",
    "Preço acima da MM200": "above",
    "Preço abaixo da MM200": "below",
}

SMA_SLOPE_FILTERS: Dict[str, str] = {
    "Qualquer inclinação": "any",
    "MM200 ascendente": "rising",
    "MM200 descendente": "falling",
}


def fetch_screen_chart(
    ticker: str,
    timeframe: str,
    cfg: StrategyConfig,
    adjustment_label: str = "Total Return (splits + dividendos)",
) -> Tuple[pd.DataFrame, List[str]]:
    """Load all available history for one screening ticker and calculate signals."""
    freq_label = NORGATE_TIMEFRAMES[timeframe]
    end = datetime.date.today()
    frame, warnings = norgate_loader.fetch_price(
        ticker,
        adjustment_label=adjustment_label,
        start_date="1900-01-01",
        end_date=str(end),
        frequency_label=freq_label,
    )
    if frame.empty:
        return frame, warnings
    return build_signal_frame(frame, cfg), warnings


def add_historical_trade_stats(
    hits: pd.DataFrame,
    timeframe: str,
    cfg: StrategyConfig,
    adjustment_label: str = "Total Return (splits + dividendos)",
    progress: Optional[Callable[[float], None]] = None,
) -> Tuple[pd.DataFrame, Dict[str, Tuple[BacktestResult, List[str]]], List[str]]:
    """Attach full-history win/loss statistics to each screening hit."""
    enriched = hits.copy()
    enriched["trade_count"] = pd.NA
    for column in ("win_rate", "avg_gain", "avg_loss", "mfe_12w"):
        enriched[column] = float("nan")
    details: Dict[str, Tuple[BacktestResult, List[str]]] = {}
    errors: List[str] = []
    total = len(enriched)

    for number, (index, row) in enumerate(enriched.iterrows(), start=1):
        ticker = str(row["ticker"])
        try:
            frame, warnings = fetch_screen_chart(
                ticker,
                timeframe,
                cfg,
                adjustment_label=adjustment_label,
            )
            if frame.empty:
                errors.append(f"{ticker}: histórico vazio")
                continue
            result = BacktestEngine(frame, replace(cfg, ticker=ticker)).run()
            details[ticker] = (result, warnings)
            enriched.at[index, "trade_count"] = len(result.trades)
            mfe_12w = (
                pd.to_numeric(result.trades["mfe_12w"], errors="coerce").dropna()
                if "mfe_12w" in result.trades
                else pd.Series(dtype=float)
            )
            if not mfe_12w.empty:
                enriched.at[index, "mfe_12w"] = float(mfe_12w.mean())
            returns = (
                pd.to_numeric(result.trades["net_return"], errors="coerce").dropna()
                if "net_return" in result.trades
                else pd.Series(dtype=float)
            )
            if not returns.empty:
                gains = returns.loc[returns > 0]
                losses = returns.loc[returns < 0]
                enriched.at[index, "win_rate"] = float(returns.gt(0).mean())
                if not gains.empty:
                    enriched.at[index, "avg_gain"] = float(gains.mean())
                if not losses.empty:
                    enriched.at[index, "avg_loss"] = float(losses.mean())
        except Exception as exc:
            errors.append(f"{ticker}: {exc}")
        finally:
            if progress is not None and total:
                progress(number / total)

    return enriched, details, errors


def run_screen_norgate(tickers: List[str], timeframe: str, cfg: StrategyConfig,
                       adjustment_label: str = "Total Return (splits + dividendos)",
                       ignore_last: bool = True,
                       progress: Optional[Callable[[float], None]] = None,
                       sma_price_filter: str = "any",
                       sma_slope_filter: str = "any",
                       ) -> Tuple[pd.DataFrame, int, int]:
    """Screen ``tickers`` on ``timeframe`` using Norgate Data.

    Fetches a warmup window of OHLC for each ticker via :mod:`src.norgate_loader`,
    then runs the exact backtest entry logic. Returns (hits_df, scanned, errors).
    """
    from . import norgate_loader

    freq_label = NORGATE_TIMEFRAMES[timeframe]
    end = datetime.date.today()
    start = end - datetime.timedelta(days=_NORGATE_LOOKBACK_DAYS[timeframe])

    ohlc, _warns, _skipped = norgate_loader.fetch_many(
        tickers,
        adjustment_label=adjustment_label,
        start_date=str(start),
        end_date=str(end),
        min_bars=_min_bars(cfg),
        frequency_label=freq_label,
        progress=progress,
    )
    hits_df, scanned = _screen_data(
        ohlc, tickers, cfg, ignore_last, sma_price_filter, sma_slope_filter
    )
    return hits_df, scanned, len(tickers) - scanned
