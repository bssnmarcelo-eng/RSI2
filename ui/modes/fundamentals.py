"""Fundamental analysis panel (Norgate current fundamentals via LSEG/Refinitiv).

Standalone from the backtest flows: pick a ticker and browse the full set of
fundamental fields grouped into tabs. Data is a *current snapshot* (no history).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import fundamentals as F


@st.cache_data(ttl=21_600, show_spinner=False)
def _cached_fundamentals(symbol: str) -> dict:
    return F.fetch_all(symbol)


@st.cache_data(ttl=21_600, show_spinner=False)
def _cached_overview(symbol: str) -> dict:
    return F.overview(symbol)


def _unit_of(token: str) -> str:
    return next((u for t, _, u in F.ALL_FIELDS if t == token), "N")


def _category_table(category_fields, values: dict) -> pd.DataFrame:
    rows = []
    for token, label, unit in category_fields:
        value, date = values.get(token, (None, None))
        rows.append({
            "Métrica": label,
            "Valor": F.format_value(value, unit),
            "Data ref.": date or "—",
            "Campo": token,
        })
    return pd.DataFrame(rows, columns=["Métrica", "Valor", "Data ref.", "Campo"])


def _headline(values: dict) -> None:
    """Key valuation metrics as metric cards."""
    def g(token):
        v, _ = values.get(token, (None, None))
        return F.format_value(v, _unit_of(token))

    r1 = st.columns(4)
    r1[0].metric("Valor de mercado", g("mktcap"))
    r1[1].metric("P/L (TTM)", g("peexclxor"))
    r1[2].metric("Preço/Vendas (TTM)", g("ttmpr2rev"))
    r1[3].metric("Dividend yield", g("divyield_curttm"))
    r2 = st.columns(4)
    r2[0].metric("ROE (TTM)", g("ttmroepct"))
    r2[1].metric("Margem líquida (TTM)", g("ttmnpmgn"))
    r2[2].metric("Beta", g("beta"))
    r2[3].metric("Preço-alvo (consenso)", g("targetprice"))


def run_fundamentals_mode() -> None:
    st.header("💼 Análise Fundamentalista")
    st.markdown(
        "Fundamentos **atuais** das ações via Norgate (dados LSEG/Refinitiv). "
        "Inclui demonstrativos TTM, ano fiscal e trimestre, múltiplos de valuation, "
        "crescimento (CAGR) e consenso de analistas.")
    st.info(
        "ℹ️ São valores **point-in-time (snapshot atual)** — a Norgate não fornece "
        "histórico desses campos, então isto serve para análise/screening de hoje, "
        "não para backtests fundamentalistas. Cada valor traz a data do período de "
        "reporte a que se refere.")

    if not F.is_available():
        st.error(
            "⚠️ Norgate Data Updater (NDU) não está rodando (ou o pacote `norgatedata` "
            "não está instalado). Inicie o NDU e recarregue a página.")
        return

    c1, c2 = st.columns([3, 1])
    symbol = c1.text_input(
        "Ticker", value="AAPL",
        help="Símbolo Norgate (ex.: AAPL, MSFT, PETR4 para AU/CA conforme assinatura). "
             "Os tickers disponíveis são os mesmos das watchlists/databases dos modos de backtest."
    ).strip().upper()
    c2.markdown("<div style='height:1.8em'></div>", unsafe_allow_html=True)
    run = c2.button("🔍 Analisar", type="primary", use_container_width=True)

    if not symbol:
        st.info("Digite um ticker para começar.")
        return

    # Fetch on button press or whenever the symbol changes (cached per symbol).
    if not run and st.session_state.get("_fund_symbol") != symbol:
        st.caption("Pressione **Analisar** para carregar os fundamentos.")
        return
    st.session_state["_fund_symbol"] = symbol

    with st.spinner(f"Carregando fundamentos de {symbol}…"):
        ov = _cached_overview(symbol)
        values = _cached_fundamentals(symbol)

    non_null = sum(1 for v, _ in values.values() if v is not None)
    if non_null == 0 and not ov.get("name"):
        st.error(f"Nenhum dado fundamentalista encontrado para **{symbol}**. "
                 "Verifique o ticker (deve existir na sua assinatura Norgate).")
        return

    # ── header ──────────────────────────────────────────────────────────────
    title = ov.get("name") or symbol
    st.subheader(f"{symbol} · {title}")
    bits = [b for b in [
        ov.get("exchange"), ov.get("currency"), ov.get("gics_sector"),
        ov.get("gics_industry"),
    ] if b]
    if bits:
        st.caption(" · ".join(bits))
    _headline(values)

    # ── tabs: overview + one per category ─────────────────────────────────────
    tab_titles = ["📋 Visão Geral"] + [t for t, _, _ in F.CATALOG]
    tabs = st.tabs(tab_titles)

    with tabs[0]:
        gcols = st.columns(2)
        with gcols[0]:
            st.markdown("**Classificação (GICS)**")
            st.dataframe(pd.DataFrame({
                "Nível": ["Setor", "Grupo industrial", "Indústria", "Sub-indústria"],
                "Classificação": [ov.get("gics_sector") or "—", ov.get("gics_industry_grp") or "—",
                                   ov.get("gics_industry") or "—", ov.get("gics_sub_industry") or "—"],
            }), use_container_width=True, hide_index=True)
        with gcols[1]:
            st.markdown("**Identificação**")
            st.dataframe(pd.DataFrame({
                "Item": ["Bolsa", "Moeda", "Domicílio", "Tipo", "Subtipo",
                         "Última cotação"],
                "Valor": [ov.get("exchange") or "—", ov.get("currency") or "—",
                          ov.get("domicile") or "—", ov.get("subtype1") or "—",
                          ov.get("subtype2") or "—", ov.get("last_quoted") or "—"],
            }), use_container_width=True, hide_index=True)
        if ov.get("financial_summary"):
            st.markdown("**Resumo financeiro**")
            st.write(ov["financial_summary"])
        if ov.get("business_summary"):
            st.markdown("**Resumo do negócio**")
            st.write(ov["business_summary"])

    for tab, (cat_title, cat_help, cat_fields) in zip(tabs[1:], F.CATALOG):
        with tab:
            st.caption(cat_help)
            tbl = _category_table(cat_fields, values)
            st.dataframe(tbl, use_container_width=True, hide_index=True)

    # ── full export ───────────────────────────────────────────────────────────
    export_rows = []
    for cat_title, _, cat_fields in F.CATALOG:
        for token, label, unit in cat_fields:
            value, date = values.get(token, (None, None))
            export_rows.append({
                "categoria": cat_title, "campo": token, "metrica": label,
                "valor": value, "valor_fmt": F.format_value(value, unit),
                "unidade": unit, "data_ref": date,
            })
    export_df = pd.DataFrame(export_rows)
    st.download_button(
        "⬇️ Baixar todos os fundamentos (CSV)",
        data=export_df.to_csv(index=False).encode("utf-8"),
        file_name=f"fundamentals_{symbol}.csv", mime="text/csv", key="fund_csv")
    st.caption(f"{non_null} campos com dados de {len(F.ALL_FIELDS)} no catálogo · "
               f"fonte: Norgate Data / LSEG.")
