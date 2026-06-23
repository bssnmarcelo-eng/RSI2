"""Persist a backtest run to the on-disk log (never breaks the app on error)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import logger


def save_to_log(mode: str, summary: dict, tables: dict, full: dict) -> None:
    """Persist a run to the backtest log; never let a logging error break the app."""
    try:
        run_id = logger.log_run(mode, summary, tables, full)
        st.success(f"💾 Saved to backtest log: **{run_id}** (see the *Backtest Log* mode).")
    except Exception as exc:
        st.warning(f"Could not write to the backtest log: {exc}")


def _equity_frame(equity: pd.Series) -> pd.DataFrame:
    eq = equity.rename("equity").to_frame()
    eq.index.name = "date"
    return eq
