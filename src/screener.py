"""Market screening: scan an index for tickers currently firing the entry signal.

Constituents are scraped from Wikipedia; OHLC bars are downloaded with yfinance;
the strategy's own :func:`build_signal_frame` is then run on each ticker so the
screen is IDENTICAL to the backtest entry condition (RSI(period) < threshold AND
percentile hammer, plus the optional ATR and price filters). A "hit" is a ticker
whose ``entry_signal`` is True on the evaluated candle.

External data (yfinance / Wikipedia) is only used here, in the screening mode.
"""
from __future__ import annotations

import io
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from .backtest_engine import build_signal_frame
from .types import StrategyConfig

# Index -> Wikipedia URL (constituent tables). S&P 1500 is the union of 500+400+600.
_WIKI = {
    "Nasdaq 100": "https://en.wikipedia.org/wiki/Nasdaq-100",
    "S&P 500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "S&P 400 (MidCap)": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "S&P 600 (SmallCap)": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}
INDICES: List[str] = ["Nasdaq 100", "S&P 500", "S&P 400 (MidCap)",
                      "S&P 600 (SmallCap)", "S&P 1500"]

# Timeframe label -> (yfinance interval, yfinance period). Periods give >100 bars
# (enough warmup for RSI and ATR) while staying within yfinance's limits.
TIMEFRAMES: Dict[str, Tuple[str, str]] = {
    "60 minutes": ("60m", "3mo"),
    "Daily": ("1d", "1y"),
    "Weekly": ("1wk", "5y"),
    "Monthly": ("1mo", "10y"),
}

_HEADERS = {"User-Agent": "Mozilla/5.0 (backtest-screener)"}


def _normalize_symbol(sym: str) -> str:
    """Wikipedia/Yahoo symbol normalisation (e.g. 'BRK.B' -> 'BRK-B')."""
    return str(sym).strip().upper().replace(".", "-").replace("\xa0", "")


def _symbols_from_wiki(url: str) -> List[str]:
    import requests
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    # Pick the table that has a Symbol/Ticker column and the most rows.
    best: List[str] = []
    for t in tables:
        cols = {str(c): c for c in t.columns}
        key = next((cols[c] for c in ("Symbol", "Ticker") if c in cols), None)
        if key is None:
            continue
        syms = [_normalize_symbol(s) for s in t[key].astype(str) if str(s).strip()]
        syms = [s for s in syms if s and s.lower() != "nan"]
        if len(syms) > len(best):
            best = syms
    return best


def get_constituents(index: str) -> List[str]:
    """Return the list of tickers for ``index`` (raises on network/parse failure)."""
    if index == "S&P 1500":
        out: List[str] = []
        for name in ("S&P 500", "S&P 400 (MidCap)", "S&P 600 (SmallCap)"):
            out.extend(_symbols_from_wiki(_WIKI[name]))
        return sorted(set(out))
    if index not in _WIKI:
        raise ValueError(f"Unknown index: {index}")
    return sorted(set(_symbols_from_wiki(_WIKI[index])))


def _extract_ohlc(data: pd.DataFrame, ticker: str) -> Optional[pd.DataFrame]:
    """Pull one ticker's OHLC out of a (possibly multi-index) yfinance frame."""
    try:
        if isinstance(data.columns, pd.MultiIndex):
            lvl0 = data.columns.get_level_values(0)
            lvl1 = data.columns.get_level_values(1)
            if ticker in lvl0:
                sub = data[ticker]
            elif ticker in lvl1:
                sub = data.xs(ticker, axis=1, level=1)
            else:
                return None
        else:
            sub = data
        sub = sub.rename(columns=str.lower)
        if not {"open", "high", "low", "close"}.issubset(sub.columns):
            return None
        sub = sub[["open", "high", "low", "close"]].dropna()
        return sub if len(sub) else None
    except Exception:
        return None


def fetch_ohlc(tickers: List[str], interval: str, period: str,
               batch_size: int = 120,
               progress: Optional[Callable[[float], None]] = None) -> Dict[str, pd.DataFrame]:
    """Download OHLC for many tickers via yfinance, in batches. Returns ticker->df."""
    import yfinance as yf

    out: Dict[str, pd.DataFrame] = {}
    n = len(tickers)
    for start in range(0, n, batch_size):
        batch = tickers[start:start + batch_size]
        try:
            data = yf.download(batch, period=period, interval=interval, group_by="ticker",
                               auto_adjust=True, threads=True, progress=False)
        except Exception:
            data = None
        if data is not None and not data.empty:
            for t in batch:
                df = _extract_ohlc(data, t)
                if df is not None:
                    out[t] = df
        if progress:
            progress(min((start + batch_size) / n, 1.0))
    return out


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
    interval, period = TIMEFRAMES[timeframe]
    ohlc = fetch_ohlc(tickers, interval, period, progress=progress)

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
