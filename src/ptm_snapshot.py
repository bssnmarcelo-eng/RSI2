"""Point-in-time snapshot capture for PTM-style equity research.

Norgate exposes current LSEG/Refinitiv fundamentals, not historical fundamental
timeseries.  This module therefore records immutable observations that can be
used for honest forward tests after enough snapshots have accumulated.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from src import fundamentals

PTM_FIELDS: dict[str, str] = {
    "mktcap": "market_cap_usd_m",
    "arev": "revenue_actual_usd_m",
    "projsales": "revenue_consensus_usd_m",
    "epsactual": "eps_actual",
    "projeps": "eps_consensus",
    "peexclxor": "pe_ttm",
    "projltgrowthrate": "eps_long_term_growth_pct",
    "targetprice": "target_price_consensus",
    "qtotd2eq": "debt_to_equity_pct",
    "ttmnpmgn": "net_profit_margin_ttm_pct",
    "divyield_curttm": "dividend_yield_ttm_pct",
    "epssurpriseqprc": "eps_surprise_quarter_pct",
    "beta": "beta",
    "revgrpct": "revenue_cagr_3y_pct",
    "epsgrpct": "eps_cagr_3y_pct",
}

PTM_COVERAGE_GAPS: tuple[str, ...] = (
    "separate FY1/FY2/FY3 EPS and revenue consensus histories",
    "60-day FY1/FY2 estimate revision histories",
    "four-quarter earnings-surprise histories",
    "historical point-in-time sector consensus aggregates",
    "historical catalyst and qualitative-research records",
)

FetchField = Callable[[str, str], tuple[object | None, str | None]]
FetchOverview = Callable[[str], dict]


def _utc_observation(value: datetime | str | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        parsed = pd.Timestamp(value)
    else:
        parsed = pd.Timestamp(value)
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    else:
        parsed = parsed.tz_convert("UTC")
    return parsed.isoformat()


def collect_snapshot(
    symbols: Iterable[str],
    *,
    observed_at: datetime | str | None = None,
    fetch_field: FetchField = fundamentals.fetch_one,
    fetch_overview: FetchOverview = fundamentals.overview,
    max_workers: int = 8,
) -> pd.DataFrame:
    """Capture one immutable current snapshot for each unique symbol.

    Raw values are retained alongside the source date returned by Norgate.  The
    observation timestamp represents when this application first knew the value.
    """
    unique_symbols = tuple(dict.fromkeys(str(s).strip().upper() for s in symbols if str(s).strip()))
    if not unique_symbols:
        return pd.DataFrame()
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")

    observation = _utc_observation(observed_at)

    def capture(symbol: str) -> dict[str, object]:
        overview = fetch_overview(symbol) or {}
        row: dict[str, object] = {
            "observed_at": observation,
            "symbol": symbol,
            "name": overview.get("name"),
            "gics_sector": overview.get("gics_sector"),
            "gics_industry_group": overview.get("gics_industry_grp"),
            "gics_industry": overview.get("gics_industry"),
            "last_quoted": overview.get("last_quoted"),
        }
        for token, column in PTM_FIELDS.items():
            value, source_date = fetch_field(symbol, token)
            row[column] = value
            row[f"{column}_source_date"] = source_date
        return row

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        rows = list(executor.map(capture, unique_symbols))
    return pd.DataFrame(rows).sort_values("symbol", kind="stable").reset_index(drop=True)


def eligible_universe(snapshot: pd.DataFrame, minimum_market_cap_usd_m: float = 1_000.0) -> pd.DataFrame:
    """Apply the course workbook's explicit market-cap floor without ranking stocks."""
    if minimum_market_cap_usd_m < 0:
        raise ValueError("minimum_market_cap_usd_m cannot be negative")
    if "market_cap_usd_m" not in snapshot:
        raise ValueError("snapshot is missing market_cap_usd_m")
    market_cap = pd.to_numeric(snapshot["market_cap_usd_m"], errors="coerce")
    return snapshot.loc[market_cap >= minimum_market_cap_usd_m].reset_index(drop=True)


def save_snapshot(snapshot: pd.DataFrame, directory: str | Path) -> Path:
    """Persist a snapshot as a new CSV; an existing observation is never overwritten."""
    if snapshot.empty:
        raise ValueError("cannot save an empty PTM snapshot")
    observations = snapshot["observed_at"].dropna().astype(str).unique()
    if len(observations) != 1:
        raise ValueError("a snapshot file must contain exactly one observed_at timestamp")

    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    stamp = pd.Timestamp(observations[0]).tz_convert("UTC").strftime("%Y%m%dT%H%M%S%fZ")
    target = root / f"ptm_snapshot_{stamp}.csv"
    if target.exists():
        raise FileExistsError(f"snapshot already exists: {target}")
    temporary = root / f".{target.name}.tmp"
    snapshot.to_csv(temporary, index=False)
    temporary.replace(target)
    return target


def load_snapshots(directory: str | Path) -> pd.DataFrame:
    """Load every stored PTM snapshot in chronological observation order."""
    paths = sorted(Path(directory).glob("ptm_snapshot_*.csv"))
    if not paths:
        return pd.DataFrame()
    combined = pd.concat((pd.read_csv(path) for path in paths), ignore_index=True)
    combined["observed_at"] = pd.to_datetime(combined["observed_at"], utc=True)
    return combined.sort_values(["observed_at", "symbol"], kind="stable").reset_index(drop=True)
