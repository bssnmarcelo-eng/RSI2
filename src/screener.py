"""Market screening using current Norgate universes and Norgate OHLC bars.

The strategy's own :func:`build_signal_frame` is run on each ticker so the screen
is identical to the backtest entry condition. A "hit" is a ticker whose
``entry_signal`` is true on the evaluated candle.
"""
from __future__ import annotations

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


def run_screen(tickers: List[str], timeframe: str, cfg: StrategyConfig,
               ignore_last: bool = True,
               progress: Optional[Callable[[float], None]] = None) -> Tuple[pd.DataFrame, int, int]:
    """Screen ``tickers`` on ``timeframe``. Returns (hits_df, n_scanned, n_errors).

    ``hits_df`` rows are tickers whose entry_signal is True on the evaluated candle,
    sorted by RSI ascending (most oversold first).
    """
    frequency_label, lookback_years = TIMEFRAMES[timeframe]
    ohlc = fetch_ohlc(
        tickers, frequency_label, lookback_years, _min_bars(cfg), progress=progress
    )

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
    errors = len(tickers) - scanned
    hits_df = pd.DataFrame(hits)
    if not hits_df.empty:
        hits_df = hits_df.sort_values("rsi").reset_index(drop=True)
    return hits_df, scanned, errors
