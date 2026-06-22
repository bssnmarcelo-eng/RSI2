"""Norgate Data loader — wraps the norgatedata Python package.

Only imported when the user selects "Norgate Data" as the data source.
Requirements:
  - pip install norgatedata
  - Norgate Data Updater (NDU) running in the background
  - Active Norgate Data subscription (Gold or higher)
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd


# ── labels shown in the UI ────────────────────────────────────────────────────

ADJ_LABELS: List[str] = [
    "Total Return (splits + dividendos)",
    "Capital (apenas splits)",
    "Capital + dividendos especiais",
    "Sem ajuste",
]

_ADJ_ENUM_KEY = {
    "Total Return (splits + dividendos)":    "TOTALRETURN",
    "Capital (apenas splits)":               "CAPITAL",
    "Capital + dividendos especiais":        "CAPITALSPECIAL",
    "Sem ajuste":                            "NONE",
}

FREQ_LABELS: List[str] = [
    "Semanal",
    "Diário",
    "Mensal",
]

_FREQ_INTERVAL = {
    "Diário":  "D",
    "Semanal": "W",
    "Mensal":  "M",
}


# ── internal helpers ──────────────────────────────────────────────────────────

def _nd():
    """Return the norgatedata module or raise a readable ImportError."""
    try:
        import norgatedata  # noqa: PLC0415
        return norgatedata
    except ImportError:
        raise ImportError(
            "Pacote 'norgatedata' não encontrado. "
            "Instale com:  pip install norgatedata"
        )


# ── availability ──────────────────────────────────────────────────────────────

def is_available() -> bool:
    """True when norgatedata is importable AND Norgate Data Updater is running."""
    try:
        return bool(_nd().status())
    except Exception:
        return False


# ── discovery ─────────────────────────────────────────────────────────────────

def get_watchlists() -> List[str]:
    """All watchlist names available in the local Norgate database."""
    try:
        result = _nd().watchlists()
        return sorted(str(w) for w in result) if result else []
    except Exception:
        return []


def get_databases() -> List[str]:
    """All database names available in the local Norgate database."""
    try:
        result = _nd().databases()
        return sorted(str(d) for d in result) if result else []
    except Exception:
        return []


def get_watchlist_symbols(name: str) -> List[str]:
    """Symbols in a watchlist (e.g. 'S&P 500 Current & Past')."""
    try:
        syms = _nd().watchlist_symbols(name)
        return sorted(str(s) for s in syms) if syms else []
    except Exception:
        return []


def get_database_symbols(name: str) -> List[str]:
    """Symbols in a Norgate database (e.g. 'US Equities')."""
    try:
        syms = _nd().database_symbols(name)
        return sorted(str(s) for s in syms) if syms else []
    except Exception:
        return []


# ── price data ────────────────────────────────────────────────────────────────

def fetch_price(
    symbol: str,
    adjustment_label: str = "Total Return (splits + dividendos)",
    start_date: str = "1990-01-01",
    end_date: Optional[str] = None,
    frequency_label: str = "Semanal",
) -> Tuple[pd.DataFrame, List[str]]:
    """Fetch OHLCV for *symbol* and return (df, warnings).

    The DataFrame is indexed by datetime with lowercase columns
    [open, high, low, close, volume], ready for BacktestEngine.
    Padding is always NONE so delisted tickers end at their last trade date.
    """
    nd = _nd()
    warnings: List[str] = []

    adj_key  = _ADJ_ENUM_KEY.get(adjustment_label, "TOTALRETURN")
    adj      = getattr(nd.StockPriceAdjustmentType, adj_key)
    interval = _FREQ_INTERVAL.get(frequency_label, "W")

    kwargs: dict = dict(
        stock_price_adjustment_setting=adj,
        padding_setting=nd.PaddingType.NONE,
        timeseriesformat="pandas-dataframe",
        interval=interval,
        start_date=start_date,
    )
    if end_date:
        kwargs["end_date"] = end_date

    try:
        raw = nd.price_timeseries(symbol, **kwargs)
    except Exception as exc:
        return pd.DataFrame(), [f"{symbol}: erro ao buscar dados — {exc}"]

    if raw is None or raw.empty:
        return pd.DataFrame(), [f"{symbol}: sem dados no período solicitado."]

    # Norgate returns Date as index with Title-case column names.
    df = raw.copy()
    df.index = pd.to_datetime(df.index)
    df.index.name = "date"
    df.columns = [c.lower() for c in df.columns]

    keep = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[keep]

    # Drop rows with missing or non-positive OHLC (Norgate padding rows have 0s).
    before = len(df)
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    dropped = before - len(df)
    if dropped:
        warnings.append(f"{symbol}: {dropped} barra(s) com OHLC inválido removidas.")

    if df.empty:
        warnings.append(f"{symbol}: sem barras válidas após limpeza.")

    return df, warnings


def fetch_many(
    symbols: List[str],
    adjustment_label: str = "Total Return (splits + dividendos)",
    start_date: str = "1990-01-01",
    end_date: Optional[str] = None,
    min_bars: int = 20,
    frequency_label: str = "Semanal",
    progress: Optional[Callable[[float], None]] = None,
) -> Tuple[Dict[str, pd.DataFrame], List[str], List[str]]:
    """Fetch OHLCV for multiple symbols.

    Returns (data_dict, all_warnings, skipped_symbols).
    Symbols with fewer than *min_bars* rows go into *skipped_symbols*.
    """
    data: Dict[str, pd.DataFrame] = {}
    all_warnings: List[str] = []
    skipped: List[str] = []
    n = len(symbols)

    for i, sym in enumerate(symbols):
        df, w = fetch_price(sym, adjustment_label, start_date, end_date, frequency_label)
        all_warnings.extend(w)
        if df.empty or len(df) < min_bars:
            skipped.append(sym)
        else:
            data[sym] = df
        if progress:
            progress((i + 1) / n)

    return data, all_warnings, skipped


# ── metadata ──────────────────────────────────────────────────────────────────

def security_name(symbol: str) -> str:
    """Full security name, or the symbol itself if unavailable."""
    try:
        return _nd().security_name(symbol) or symbol
    except Exception:
        return symbol


def last_quoted_date(symbol: str) -> Optional[str]:
    """ISO date string of the last quote (None on error)."""
    try:
        return _nd().last_quoted_date(symbol, datetimeformat="iso")
    except Exception:
        return None
