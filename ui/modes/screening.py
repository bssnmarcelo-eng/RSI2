"""Market screening mode using Norgate current constituents and OHLC data."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import norgate_loader, screener
from src.utils import fmt_money, fmt_num
from ui.params_form import configuration_form


@st.cache_data(ttl=86_400, show_spinner=False)
def _cached_constituents(index: str):
    return screener.get_constituents(index)


def run_screening_mode() -> None:
    st.header("Screening de mercado")
    st.markdown(
        "Scan an index for tickers **currently firing the entry signal** on the chosen "
        "timeframe. The conditions are exactly the entry rules below — RSI(period) below "
        "threshold **and** a percentile hammer (plus the optional ATR and price filters). "
        "Exits, sizing and costs are ignored here. Constituents and adjusted OHLC data "
        "come from the local Norgate database.")

    if not norgate_loader.is_available():
        st.error("Norgate Data Updater não está rodando ou o pacote `norgatedata` não está instalado.")
        return

    cfg, _pconf, _submitted = configuration_form("screening", with_run=False)

    if not cfg.patterns.any_enabled():
        st.error("Habilite o padrão Hammer (aba 📥 Entrada) para fazer o screening.")
        return

    c1, c2, c3 = st.columns(3)
    index = c1.selectbox("Index", screener.INDICES, index=1)
    timeframe = c2.selectbox("Timeframe", list(screener.TIMEFRAMES.keys()), index=0)
    max_tickers = c3.number_input("Max tickers (0 = all)", min_value=0, max_value=5000, value=0, step=50)
    ignore_last = st.checkbox(
        "Ignore the latest candle if it may still be in progress",
        value=timeframe != "Daily",
        help=("Norgate daily bars are end-of-day data, so the latest available daily candle is used "
              "by default. Weekly and monthly screens ignore the current partial period by default."),
    )
    st.caption("Entry condition recap: "
               f"RSI({cfg.rsi_period}) < {cfg.rsi_entry_threshold:g} · hammer percentile "
               f"{cfg.patterns.hammer.percentile:g}"
               + (f" · range > {cfg.patterns.hammer.atr_multiple:g}×ATR({cfg.patterns.hammer.atr_period})"
                  if cfg.patterns.hammer.use_atr_filter else "")
               + ((f" · price ≥ {cfg.min_price:g}" if cfg.min_price > 0 else "")
                  + (f" · price ≤ {cfg.max_price:g}" if cfg.max_price > 0 else "")))

    if not st.button("Executar screening", type="primary"):
        return

    # Constituents (cached for a day).
    try:
        with st.spinner(f"Fetching {index} constituents…"):
            tickers = _cached_constituents(index)
    except Exception as exc:
        st.error(f"Could not fetch constituents for {index}: {exc}")
        return
    if not tickers:
        st.error("No constituents found.")
        return
    if max_tickers > 0:
        tickers = tickers[:int(max_tickers)]
    st.caption(f"Scanning **{len(tickers)}** tickers on **{timeframe}**…")

    bar = st.progress(0.0, text="Baixando dados e procurando sinais…")
    try:
        hits, scanned, errors = screener.run_screen(
            tickers, timeframe, cfg, ignore_last=ignore_last,
            progress=lambda p: bar.progress(min(p, 1.0), text="Baixando dados e procurando sinais…"))
    except ImportError:
        bar.empty()
        st.error("Pacote Norgate ausente. Execute `pip install -r requirements-norgate.txt`.")
        return
    except Exception as exc:
        bar.empty()
        st.error(f"Falha no screening: {exc}")
        return
    bar.empty()

    st.success(f"**{len(hits)}** hit(s) out of **{scanned}** scanned "
               f"({errors} ticker(s) had no/insufficient data).")
    if hits.empty:
        st.info("No tickers currently satisfy the entry conditions.")
        return

    disp = hits.copy()
    disp["date"] = pd.to_datetime(disp["date"]).dt.strftime("%Y-%m-%d %H:%M")
    disp["close"] = hits["close"].map(fmt_money)
    disp["rsi"] = hits["rsi"].map(lambda v: fmt_num(v, 2))
    disp["body_percentile"] = hits["body_percentile"].map(lambda v: fmt_num(v, 3))
    disp["range"] = hits["range"].map(lambda v: fmt_num(v, 2))
    st.dataframe(disp, use_container_width=True, hide_index=True)
    st.download_button("Baixar sinais encontrados (CSV)",
                       data=hits.to_csv(index=False).encode("utf-8"),
                       file_name=f"screening_{index.replace(' ', '_')}_{timeframe.replace(' ', '')}.csv",
                       mime="text/csv", key="screen_csv")
    st.caption(f"Sorted by RSI (most oversold first). 'date' is the evaluated candle. "
               f"'body_percentile' = (high − body bottom) ÷ range — always ≤ your percentile "
               f"setting ({cfg.patterns.hammer.percentile:g}); lower = body closer to the high "
               f"(stronger hammer).")
