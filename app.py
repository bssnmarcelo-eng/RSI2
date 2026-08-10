"""Streamlit entrypoint for the RSI(2) + bullish-candlestick mean-reversion
backtester. The UI lives in the ``ui`` package; this file only wires the mode
selector to the per-mode flows.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="RSI(2) · Laboratório de estratégias", page_icon="📈", layout="wide")

from ui.data_source import build_data_source_params  # noqa: E402
from ui.modes import (  # noqa: E402
    run_fundamentals_mode,
    run_log_mode,
    run_optimizer_mode,
    run_per_asset_mode,
    run_portfolio_mode,
    run_screening_mode,
)
from ui.text import DISCLAIMER, STRATEGY_DESCRIPTION  # noqa: E402
from ui.theme import apply_theme  # noqa: E402


def main() -> None:
    apply_theme()
    st.title("RSI(2) · Laboratório de estratégias")
    st.markdown(STRATEGY_DESCRIPTION)
    with st.expander("Premissas importantes e aviso de risco", expanded=False):
        st.markdown(DISCLAIMER)

    st.sidebar.header("Navegação")
    mode = st.sidebar.radio(
        "Área",
        ["Carteira (capital compartilhado)", "Por ativo (independente)",
         "Otimizador (grade por ativo)", "Screening de mercado", "Análise fundamentalista",
         "Histórico de backtests"],
        index=0,
        help="Carteira usa um único capital compartilhado. Por ativo reaplica o capital "
             "independentemente. O otimizador pesquisa parâmetros com validação fora da amostra. "
             "Screening procura sinais atuais; fundamentos usa dados Norgate; histórico abre execuções salvas.")

    if mode.startswith("Histórico"):
        run_log_mode()
        st.markdown("---")
        st.caption(DISCLAIMER)
        return

    if mode.startswith("Screening"):
        run_screening_mode()
        st.markdown("---")
        st.caption(DISCLAIMER)
        return

    if mode.startswith("Análise"):
        run_fundamentals_mode()
        st.markdown("---")
        st.caption(DISCLAIMER)
        return

    data_src = build_data_source_params()

    note = st.sidebar.text_input(
        "Nome ou observação da execução (opcional)",
        help="Fica salvo no histórico para facilitar a busca posterior, por exemplo: 'IBKR 2x'.")

    if mode.startswith("Por ativo"):
        run_per_asset_mode(note, data_src)
    elif mode.startswith("Otimizador"):
        run_optimizer_mode(note, data_src)
    else:
        run_portfolio_mode(note, data_src)

    st.markdown("---")
    st.caption(DISCLAIMER)


if __name__ == "__main__":
    main()
