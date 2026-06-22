"""CSV loading, column normalisation, validation and cleaning.

The goal is to be forgiving about *input* formatting while guaranteeing a strict,
clean OHLCV frame for the engine. No external data sources are touched — every
byte comes from the user's uploaded file.
"""
from __future__ import annotations

import io
from typing import List, Optional, Tuple

import pandas as pd

# Canonical column name -> set of accepted variants (compared after lower/strip
# and replacing spaces/dashes with underscores).
_COLUMN_ALIASES = {
    "date": {"date", "datetime", "timestamp", "time", "day"},
    "ticker": {"ticker", "symbol", "asset", "instrument"},
    "open": {"open", "o"},
    "high": {"high", "h"},
    "low": {"low", "l"},
    "close": {"close", "c", "last"},
    "adj_close": {"adj_close", "adjclose", "adjusted_close", "adjusted", "adjustedclose"},
    "volume": {"volume", "vol", "v"},
}

REQUIRED_COLUMNS = ["date", "open", "high", "low", "close"]


def _canonical(name: str) -> Optional[str]:
    key = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    for canonical, variants in _COLUMN_ALIASES.items():
        if key == canonical or key in variants:
            return canonical
    return None


def _read_text(file) -> str:
    """Return the file contents as text, handling uploads, bytes and paths."""
    if hasattr(file, "read"):
        raw = file.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8-sig", errors="replace")
        return raw
    with open(file, "r", encoding="utf-8-sig", errors="replace") as fh:
        return fh.read()


def _detect_separator(text: str) -> str:
    """Guess the column delimiter by counting candidates on the header line.

    Header names rarely contain punctuation, so the delimiter is whichever
    candidate appears most on the first non-empty line. This correctly picks
    ``;`` for European exports whose data rows also contain decimal commas
    (which would otherwise fool a naive comma count). Falls back to comma.
    """
    header = next((ln for ln in text.splitlines() if ln.strip()), "")
    candidates = {
        ";": header.count(";"),
        ",": header.count(","),
        "\t": header.count("\t"),
        "|": header.count("|"),
    }
    best = max(candidates, key=candidates.get)
    return best if candidates[best] > 0 else ","


def read_csv(file) -> pd.DataFrame:
    """Read an uploaded file (Streamlit UploadedFile, path, or bytes) into a frame.

    The delimiter is auto-detected (comma, semicolon, tab or pipe). Numeric
    columns are read as-is; decimal commas (e.g. "32,8145") and other locale
    quirks are normalised later in :func:`prepare`.
    """
    text = _read_text(file)
    sep = _detect_separator(text)
    return pd.read_csv(io.StringIO(text), sep=sep)


def _coerce_numeric(series: pd.Series) -> pd.Series:
    """Coerce a column to float, tolerating decimal commas and thousands dots.

    Examples handled: "32,8145" -> 32.8145, "1.234,56" -> 1234.56,
    "186290400" -> 186290400.0. Anything unparseable becomes NaN.
    """
    if series.dtype.kind in "biufc":
        return series.astype(float)
    s = series.astype(str).str.strip()
    # When a value contains BOTH separators, the dot is a thousands separator.
    both = s.str.contains(",", regex=False) & s.str.contains(".", regex=False)
    s = s.mask(both, s.str.replace(".", "", regex=False))
    # Decimal comma -> decimal point.
    s = s.str.replace(",", ".", regex=False)
    return pd.to_numeric(s, errors="coerce")


def _parse_dates(series: pd.Series) -> pd.Series:
    """Parse dates, auto-detecting day-first (DD/MM/YYYY) vs month-first ordering.

    Picks whichever interpretation parses more rows; ties keep the default
    parser (which handles ISO ``YYYY-MM-DD`` and US ``M/D/Y``). This lets
    European ``13/01/2016``-style files parse correctly without breaking US data.
    """
    default = pd.to_datetime(series, errors="coerce")
    dayfirst = pd.to_datetime(series, errors="coerce", dayfirst=True)
    if dayfirst.isna().sum() < default.isna().sum():
        return dayfirst
    return default


def normalize_columns(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    """Rename columns to canonical names. Returns (frame, warnings)."""
    warnings: List[str] = []
    rename = {}
    seen = set()
    for col in df.columns:
        canon = _canonical(col)
        if canon is None:
            continue
        if canon in seen:
            warnings.append(f"Duplicate mapping for '{canon}' (column '{col}' ignored).")
            continue
        rename[col] = canon
        seen.add(canon)
    out = df.rename(columns=rename)
    # Drop any columns we could not map (keeps the frame tidy).
    out = out[[c for c in out.columns if c in _COLUMN_ALIASES]]
    return out, warnings


def validate_columns(df: pd.DataFrame) -> List[str]:
    """Return a list of missing required columns (empty list == valid)."""
    return [c for c in REQUIRED_COLUMNS if c not in df.columns]


def get_tickers(df: pd.DataFrame) -> List[str]:
    """Sorted unique tickers if a ticker column is present, else empty list."""
    if "ticker" not in df.columns:
        return []
    return sorted(df["ticker"].dropna().astype(str).unique().tolist())


def date_bounds(df: pd.DataFrame):
    """Return (min_date, max_date) across all rows, or (None, None) if empty."""
    if "date" not in df.columns:
        return None, None
    dates = _parse_dates(df["date"]).dropna()
    if dates.empty:
        return None, None
    return dates.min().date(), dates.max().date()


def load_and_combine(files) -> Tuple[pd.DataFrame, List[str], List[str]]:
    """Read and normalise one or more uploaded CSVs into a single tidy frame.

    Each file may itself contain multiple tickers (via a ticker/symbol column).
    Files without a ticker column have their ticker inferred from the filename
    (e.g. ``AMZN.csv`` -> ``AMZN``). Returns (combined_frame, warnings, errors);
    files that fail validation are reported in ``errors`` and skipped.
    """
    warnings: List[str] = []
    errors: List[str] = []
    frames: List[pd.DataFrame] = []

    items = files if isinstance(files, (list, tuple)) else [files]
    for f in items:
        name = getattr(f, "name", "uploaded.csv")
        try:
            raw = read_csv(f)
        except Exception as exc:  # robust against malformed files
            errors.append(f"{name}: could not read file ({exc}).")
            continue
        norm, w = normalize_columns(raw)
        warnings.extend(f"{name}: {msg}" for msg in w)
        missing = validate_columns(norm)
        if missing:
            errors.append(f"{name}: missing required column(s): {', '.join(missing)}.")
            continue
        if "ticker" not in norm.columns:
            stem = str(name).rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
            norm = norm.copy()
            norm["ticker"] = stem or "ASSET"
        frames.append(norm)

    if not frames:
        return pd.DataFrame(), warnings, errors
    combined = pd.concat(frames, ignore_index=True)
    return combined, warnings, errors


def prepare(
    df: pd.DataFrame,
    ticker: Optional[str] = None,
    start=None,
    end=None,
) -> Tuple[pd.DataFrame, List[str]]:
    """Clean and return a backtest-ready frame indexed by datetime.

    Steps: filter ticker -> parse dates -> sort chronologically -> drop duplicate
    dates -> coerce numeric OHLCV -> drop rows with unusable prices. All issues
    are surfaced as human-readable warnings rather than silent mutations.
    """
    warnings: List[str] = []
    out = df.copy()

    # --- Ticker filtering ---
    if "ticker" in out.columns and ticker:
        out = out[out["ticker"].astype(str) == str(ticker)]
    if out.empty:
        return out, ["No rows remain after ticker filtering."]

    # --- Date parsing ---
    out["date"] = _parse_dates(out["date"])
    n_bad_dates = int(out["date"].isna().sum())
    if n_bad_dates:
        warnings.append(f"Dropped {n_bad_dates} row(s) with unparseable dates.")
        out = out.dropna(subset=["date"])

    # --- Chronological sort ---
    out = out.sort_values("date")

    # --- Duplicate dates ---
    dup_mask = out["date"].duplicated(keep="first")
    n_dups = int(dup_mask.sum())
    if n_dups:
        warnings.append(f"Removed {n_dups} duplicate date row(s) (kept first occurrence).")
        out = out[~dup_mask]

    # --- Numeric coercion ---
    numeric_cols = [c for c in ["open", "high", "low", "close", "adj_close", "volume"] if c in out.columns]
    for col in numeric_cols:
        out[col] = _coerce_numeric(out[col])

    # --- Drop rows with missing/invalid OHLC ---
    before = len(out)
    out = out.dropna(subset=["open", "high", "low", "close"])
    out = out[(out[["open", "high", "low", "close"]] > 0).all(axis=1)]
    dropped = before - len(out)
    if dropped:
        warnings.append(f"Dropped {dropped} row(s) with missing or non-positive OHLC values.")

    # --- Basic sanity: high should be >= low ---
    bad_hl = int((out["high"] < out["low"]).sum())
    if bad_hl:
        warnings.append(f"Found {bad_hl} row(s) where high < low; these were removed.")
        out = out[out["high"] >= out["low"]]

    # --- Date range filtering ---
    if start is not None:
        out = out[out["date"] >= pd.Timestamp(start)]
    if end is not None:
        out = out[out["date"] <= pd.Timestamp(end)]

    out = out.set_index("date")
    if out.empty:
        warnings.append("No rows remain after cleaning / date-range filtering.")
    return out, warnings
