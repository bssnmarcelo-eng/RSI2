from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

from src.ptm_snapshot import collect_snapshot, eligible_universe, load_snapshots, save_snapshot


def _overview(symbol: str) -> dict:
    return {
        "name": f"{symbol} Corp",
        "gics_sector": "Industrials",
        "gics_industry_grp": "Capital Goods",
        "gics_industry": "Machinery",
        "last_quoted": "2026-08-14",
    }


def _field(symbol: str, token: str):
    values = {
        ("BIG", "mktcap"): 2_000.0,
        ("SMALL", "mktcap"): 999.0,
        ("BIG", "projeps"): 5.5,
    }
    return values.get((symbol, token)), "2026-08-14"


def test_collect_snapshot_is_dated_deduplicated_and_keeps_source_dates():
    snapshot = collect_snapshot(
        ["big", "BIG", "small"],
        observed_at="2026-08-17T12:00:00-03:00",
        fetch_field=_field,
        fetch_overview=_overview,
        max_workers=2,
    )

    assert snapshot["symbol"].tolist() == ["BIG", "SMALL"]
    assert snapshot["observed_at"].nunique() == 1
    assert snapshot.loc[0, "observed_at"] == "2026-08-17T15:00:00+00:00"
    assert snapshot.loc[0, "eps_consensus"] == 5.5
    assert snapshot.loc[0, "eps_consensus_source_date"] == "2026-08-14"


def test_market_cap_filter_is_explicit_and_preserves_missing_raw_data():
    snapshot = collect_snapshot(
        ["BIG", "SMALL"], fetch_field=_field, fetch_overview=_overview, max_workers=1
    )
    eligible = eligible_universe(snapshot)
    assert eligible["symbol"].tolist() == ["BIG"]
    assert pd.isna(snapshot.loc[snapshot["symbol"].eq("SMALL"), "eps_consensus"]).all()


def test_snapshot_files_are_immutable_and_round_trip():
    output = Path(".local-run") / f"ptm-test-{uuid4().hex}"
    snapshot = collect_snapshot(
        ["BIG"], observed_at="2026-08-17T15:00:00Z",
        fetch_field=_field, fetch_overview=_overview, max_workers=1,
    )
    try:
        path = save_snapshot(snapshot, output)
        assert path.exists()
        with pytest.raises(FileExistsError):
            save_snapshot(snapshot, output)

        loaded = load_snapshots(output)
        assert loaded.loc[0, "symbol"] == "BIG"
        assert str(loaded.loc[0, "observed_at"]) == "2026-08-17 15:00:00+00:00"
    finally:
        if output.exists():
            for child in output.iterdir():
                child.unlink()
            output.rmdir()
