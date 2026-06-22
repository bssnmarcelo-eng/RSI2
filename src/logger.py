"""Persistent backtest log.

Every run (any mode) is saved under ``backtest_app/logs/``:

    logs/
      runs.csv                 # one summary row per run (the index)
      <run_id>/
        summary.json           # full config + metrics + metadata
        <table>.csv            # one CSV per result table (trades, equity, …)

``log_run`` appends to the index and writes the per-run folder; the log-viewer
mode reads them back. Logging failures are non-fatal (callers wrap in try/except).
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
RUNS_INDEX = LOG_DIR / "runs.csv"


def _run_id() -> str:
    """Millisecond-precision timestamp id (sortable, collision-resistant)."""
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]


def config_dict(cfg, portfolio=None) -> dict:
    """Full, JSON-serialisable snapshot of the strategy (+ portfolio) config."""
    d = asdict(cfg)
    if portfolio is not None:
        d["portfolio"] = asdict(portfolio)
    return d


def log_run(mode: str, summary: Dict, tables: Dict[str, pd.DataFrame], full: Dict) -> str:
    """Persist one run. Returns the run_id.

    * ``summary`` — curated key/values appended as a row to ``runs.csv``.
    * ``tables``  — name -> DataFrame; each saved as ``<name>.csv``.
    * ``full``    — complete JSON-able record saved as ``summary.json``.
    """
    run_id = _run_id()
    run_dir = LOG_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    for name, df in tables.items():
        if df is None:
            continue
        # Keep a meaningful (named/date) index; drop plain RangeIndex.
        keep_index = not isinstance(df.index, pd.RangeIndex)
        df.to_csv(run_dir / f"{name}.csv", index=keep_index)

    record = {"run_id": run_id, "timestamp": datetime.now().isoformat(timespec="seconds"),
              "mode": mode, **full}
    (run_dir / "summary.json").write_text(json.dumps(record, default=str, indent=2), encoding="utf-8")

    row = {"run_id": run_id, "timestamp": record["timestamp"], "mode": mode, **summary}
    index = load_runs_index()
    index = pd.concat([index, pd.DataFrame([row])], ignore_index=True, sort=False)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    index.to_csv(RUNS_INDEX, index=False)
    return run_id


def load_runs_index() -> pd.DataFrame:
    """The runs index (empty DataFrame if nothing logged yet)."""
    if RUNS_INDEX.exists():
        try:
            return pd.read_csv(RUNS_INDEX)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def list_run_tables(run_id: str) -> Dict[str, Path]:
    """Map of table-name -> CSV path for a run (excludes summary.json)."""
    run_dir = LOG_DIR / run_id
    if not run_dir.exists():
        return {}
    return {p.stem: p for p in sorted(run_dir.glob("*.csv"))}


def load_summary(run_id: str) -> Optional[dict]:
    path = LOG_DIR / run_id / "summary.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def list_run_ids() -> List[str]:
    if not LOG_DIR.exists():
        return []
    return sorted((p.name for p in LOG_DIR.iterdir() if p.is_dir()), reverse=True)


def clear_log() -> None:
    """Delete the entire log directory (index + all runs)."""
    if LOG_DIR.exists():
        shutil.rmtree(LOG_DIR)
