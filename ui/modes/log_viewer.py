"""Backtest-log viewer mode."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import logger


def run_log_mode() -> None:
    st.header("Histórico de backtests")
    runs = logger.load_runs_index()
    if runs.empty:
        st.info("Ainda não há execuções salvas. Execute um backtest; cada resultado será salvo aqui "
                "automatically (results, metrics and tables).")
        return

    runs_sorted = runs.sort_values("timestamp", ascending=False).reset_index(drop=True)
    st.caption(f"**{len(runs_sorted)}** run(s) saved at `{logger.LOG_DIR}`.")
    st.dataframe(runs_sorted, use_container_width=True, hide_index=True)
    st.download_button("Baixar índice das execuções (CSV)", data=runs.to_csv(index=False).encode("utf-8"),
                       file_name="runs.csv", mime="text/csv", key="runs_index_csv")

    st.subheader("🔎 Inspect a run")
    sel = st.selectbox("Execução", runs_sorted["run_id"].astype(str).tolist())
    summ = logger.load_summary(sel)
    if summ:
        with st.expander("Config + metrics (summary.json)", expanded=False):
            st.json(summ)
    for name, path in logger.list_run_tables(sel).items():
        st.markdown(f"**{name}**")
        try:
            df = pd.read_csv(path)
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.download_button(f"Baixar {name}.csv",
                               data=df.to_csv(index=False).encode("utf-8"),
                               file_name=f"{sel}_{name}.csv", mime="text/csv",
                               key=f"dl_{sel}_{name}")
        except Exception as exc:
            st.warning(f"Could not read {name}.csv: {exc}")

    st.subheader("🗑️ Clear log")
    confirm = st.checkbox("I understand this permanently deletes ALL saved runs")
    if st.button("Delete entire backtest log", disabled=not confirm):
        logger.clear_log()
        st.success("Histórico removido. Recarregue a página para atualizar.")
