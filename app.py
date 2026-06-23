"""Streamlit entrypoint for the RSI(2) + bullish-candlestick mean-reversion
backtester. The UI lives in the ``ui`` package; this file only wires the mode
selector to the per-mode flows.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="RSI(2) + Candlestick Backtester", page_icon="📈", layout="wide")

from ui.data_source import build_data_source_params  # noqa: E402
from ui.modes import (  # noqa: E402
    run_log_mode,
    run_optimizer_mode,
    run_per_asset_mode,
    run_portfolio_mode,
    run_screening_mode,
    run_single_mode,
)
from ui.text import DISCLAIMER, STRATEGY_DESCRIPTION  # noqa: E402


def main() -> None:
    st.title("📈 RSI(2) + Candlestick Mean-Reversion Backtester")
    st.markdown(STRATEGY_DESCRIPTION)
    with st.expander("Important assumptions & disclaimer", expanded=False):
        st.markdown(DISCLAIMER)

    st.sidebar.header("🧭 Mode")
    mode = st.sidebar.radio(
        "Backtest mode",
        ["Portfolio (shared capital)", "Per-asset (independent)", "Single asset",
         "Optimizer (per-asset grid)", "🔎 Market Screening", "📁 Backtest Log"],
        index=0,
        help="Portfolio = one shared capital pool with aggregated results. "
             "Per-asset = every asset tested independently with the full capital. "
             "Single = one ticker. Optimizer = grid-search parameters on the per-asset "
             "pooled trades with an in/out-of-sample split. Market Screening = scan an "
             "index for tickers firing the signal now. Backtest Log = saved-run history.")

    if mode.startswith("📁"):
        run_log_mode()
        st.markdown("---")
        st.caption(DISCLAIMER)
        return

    if mode.startswith("🔎"):
        run_screening_mode()
        st.markdown("---")
        st.caption(DISCLAIMER)
        return

    data_src = build_data_source_params()

    note = st.sidebar.text_input(
        "Run label / note (optional)",
        help="Saved with the run in the backtest log to help you find it later "
             "(e.g. 'IBKR 2x leverage test').")

    if mode.startswith("Portfolio"):
        run_portfolio_mode(note, data_src)
    elif mode.startswith("Per-asset"):
        run_per_asset_mode(note, data_src)
    elif mode.startswith("Optimizer"):
        run_optimizer_mode(note, data_src)
    else:
        run_single_mode(note, data_src)

    st.markdown("---")
    st.caption(DISCLAIMER)


if __name__ == "__main__":
    main()
