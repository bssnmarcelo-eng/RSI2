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
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from . import norgate_loader
from .backtest_engine import build_signal_frame
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


def evaluate(df: pd.DataFrame, cfg: StrategyConfig, ignore_last: bool) -> Optional[dict]:
    """Run the entry logic and return the evaluated candle's state (or None)."""
    if len(df) < _min_bars(cfg):
        return None
    sf = build_signal_frame(df, cfg)
    pos = -2 if (ignore_last and len(sf) >= 2) else -1
    row = sf.iloc[pos]
    rng = float(row["high"] - row["low"])
    # Effective body percentile: how far the body's lowest point sits from the high,
    # as a fraction of the range. Equals the smallest `percentile` at which this
    # candle would still qualify as a hammer (lower = body hugs the high).
    body_low = min(float(row["open"]), float(row["close"]))
    body_pct = (float(row["high"]) - body_low) / rng if rng > 0 else float("nan")
    return {
        "date": sf.index[pos],
        "close": float(row["close"]),
        "rsi": float(row["rsi"]) if pd.notna(row["rsi"]) else float("nan"),
        "body_percentile": body_pct,
        "range": rng,
        "pattern": str(row["pattern"]),
        "signal": bool(row["entry_signal"]),
    }


def _screen_data(ohlc: Dict[str, pd.DataFrame], tickers: List[str],
                 cfg: StrategyConfig, ignore_last: bool) -> Tuple[pd.DataFrame, int]:
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
        ev = evaluate(df, cfg, ignore_last)
        if ev is None:
            continue
        scanned += 1
        if ev["signal"]:
            hits.append({"ticker": t, "date": ev["date"], "close": ev["close"],
                         "rsi": ev["rsi"], "body_percentile": ev["body_percentile"],
                         "range": ev["range"], "pattern": ev["pattern"]})
    hits_df = pd.DataFrame(hits)
    if not hits_df.empty:
        hits_df = hits_df.sort_values("rsi").reset_index(drop=True)
    return hits_df, scanned


def run_screen(tickers: List[str], timeframe: str, cfg: StrategyConfig,
               ignore_last: bool = True,
               progress: Optional[Callable[[float], None]] = None) -> Tuple[pd.DataFrame, int, int]:
    """Screen ``tickers`` on ``timeframe`` via Norgate. Returns hits/scanned/errors.

    ``hits_df`` rows are tickers whose entry_signal is True on the evaluated candle,
    sorted by RSI ascending (most oversold first).
    """
    frequency_label, lookback_years = TIMEFRAMES[timeframe]
    ohlc = fetch_ohlc(
        tickers, frequency_label, lookback_years, _min_bars(cfg), progress=progress
    )
    hits_df, scanned = _screen_data(ohlc, tickers, cfg, ignore_last)
    return hits_df, scanned, len(tickers) - scanned


# ── Norgate path ──────────────────────────────────────────────────────────────

# Screening timeframe -> (norgate frequency label, warmup lookback in days). The
# lookback is generous enough to leave >100 bars for RSI/ATR warmup at each freq.
NORGATE_TIMEFRAMES: Dict[str, str] = {
    "Daily":   "Diário",
    "Weekly":  "Semanal",
    "Monthly": "Mensal",
}

_NORGATE_LOOKBACK_DAYS: Dict[str, int] = {
    "Daily":   400,
    "Weekly":  365 * 4,
    "Monthly": 365 * 14,
}


def run_screen_norgate(tickers: List[str], timeframe: str, cfg: StrategyConfig,
                       adjustment_label: str = "Total Return (splits + dividendos)",
                       ignore_last: bool = True,
                       progress: Optional[Callable[[float], None]] = None,
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
    hits_df, scanned = _screen_data(ohlc, tickers, cfg, ignore_last)
    return hits_df, scanned, len(tickers) - scanned
