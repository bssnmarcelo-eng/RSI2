"""Market screening mode (scan a Norgate watchlist/database for live entry signals)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import norgate_loader, screener
from src.utils import fmt_money, fmt_num
from ui.data_source import (
    _ng_databases,
    _ng_database_symbols,
    _ng_watchlist_symbols,
    _ng_watchlists,
)
from ui.params_form import configuration_form


def _collection_picker() -> list[str] | None:
    """Watchlist/Database picker; returns the symbol list (or None if unavailable)."""
    ctype = st.radio("Tipo de coleção", ["Watchlist", "Database"],
                     horizontal=True, key="screen_ctype")
    if ctype == "Watchlist":
        names = _ng_watchlists()
        if not names:
            st.warning("Nenhuma watchlist encontrada no Norgate.")
            return None
        default_idx = next(
            (i for i, n in enumerate(names) if "Current & Past" in n and "S&P 500" in n),
            0,
        )
        name = st.selectbox("Watchlist", names, index=default_idx, key="screen_wl")
        return _ng_watchlist_symbols(name)

    names = _ng_databases()
    if not names:
        st.warning("Nenhum database encontrado no Norgate.")
        return None
    default_idx = next((i for i, n in enumerate(names) if "US Equities" in n), 0)
    name = st.selectbox("Database", names, index=default_idx, key="screen_db")
    return _ng_database_symbols(name)


def run_screening_mode() -> None:
    st.header("🔎 Market Screening")
    st.markdown(
        "Scan a Norgate watchlist/database for tickers **currently firing the entry signal** "
        "on the chosen timeframe. The conditions are exactly the entry rules below — "
        "RSI(period) below threshold **and** a percentile hammer (plus the optional ATR and "
        "price filters). Exits, sizing and costs are ignored here. Data: **Norgate Data**.")

    if not norgate_loader.is_available():
        st.error(
            "⚠️ Norgate Data Updater (NDU) não está rodando ou o pacote "
            "norgatedata não está instalado.\n\n`pip install norgatedata`"
        )
        return

    cfg, _pconf, _submitted = configuration_form("screening", with_run=False)

    if not cfg.patterns.any_enabled():
        st.error("Habilite o padrão Hammer (aba 📥 Entrada) para fazer o screening.")
        return

    with st.spinner("Carregando coleções do Norgate…"):
        symbols = _collection_picker()
    if not symbols:
        return
    st.caption(f"**{len(symbols)}** ativos na coleção "
               f"(inclui deslistados e constituintes históricos).")

    c1, c2, c3 = st.columns(3)
    timeframe = c1.selectbox("Timeframe", list(screener.NORGATE_TIMEFRAMES.keys()), index=0)
    adjustment = c2.selectbox("Ajuste de preço", norgate_loader.ADJ_LABELS, index=0)
    max_tickers = c3.number_input("Max tickers (0 = all)", min_value=0, max_value=10000,
                                  value=0, step=50)
    ignore_last = st.checkbox(
        "Ignorar a última barra (avaliar a penúltima)",
        value=False,
        help="Os dados EOD do Norgate só contêm barras já fechadas, então normalmente "
             "deixe DESmarcado para avaliar o último candle disponível. Marque apenas se "
             "quiser conferir o sinal da barra anterior.")
    st.caption("Entry condition recap: "
               f"RSI({cfg.rsi_period}) < {cfg.rsi_entry_threshold:g} · hammer percentile "
               f"{cfg.patterns.hammer.percentile:g}"
               + (f" · range > {cfg.patterns.hammer.atr_multiple:g}×ATR({cfg.patterns.hammer.atr_period})"
                  if cfg.patterns.hammer.use_atr_filter else "")
               + ((f" · price ≥ {cfg.min_price:g}" if cfg.min_price > 0 else "")
                  + (f" · price ≤ {cfg.max_price:g}" if cfg.max_price > 0 else "")))

    if not st.button("▶️ Run Screening", type="primary"):
        return

    tickers = symbols if max_tickers == 0 else symbols[:int(max_tickers)]
    st.caption(f"Scanning **{len(tickers)}** tickers on **{timeframe}**…")

    bar = st.progress(0.0, text="Baixando dados do Norgate & screening…")
    try:
        hits, scanned, errors = screener.run_screen_norgate(
            tickers, timeframe, cfg, adjustment_label=adjustment, ignore_last=ignore_last,
            progress=lambda p: bar.progress(min(p, 1.0),
                                            text="Baixando dados do Norgate & screening…"))
    except ImportError:
        bar.empty()
        st.error("Pacote `norgatedata` não instalado. `pip install norgatedata`.")
        return
    except Exception as exc:
        bar.empty()
        st.error(f"Screening failed: {exc}")
        return
    bar.empty()

    st.success(f"**{len(hits)}** hit(s) out of **{scanned}** scanned "
               f"({errors} ticker(s) had no/insufficient data).")
    if hits.empty:
        st.info("No tickers currently satisfy the entry conditions.")
        return

    disp = hits.copy()
    disp["date"] = pd.to_datetime(disp["date"]).dt.strftime("%Y-%m-%d")
    disp["close"] = hits["close"].map(fmt_money)
    disp["rsi"] = hits["rsi"].map(lambda v: fmt_num(v, 2))
    disp["body_percentile"] = hits["body_percentile"].map(lambda v: fmt_num(v, 3))
    disp["range"] = hits["range"].map(lambda v: fmt_num(v, 2))
    st.dataframe(disp, use_container_width=True, hide_index=True)
    st.download_button("⬇️ Download screening hits (CSV)",
                       data=hits.to_csv(index=False).encode("utf-8"),
                       file_name=f"screening_{timeframe}.csv",
                       mime="text/csv", key="screen_csv")
    st.caption(f"Sorted by RSI (most oversold first). 'date' is the evaluated candle. "
               f"'body_percentile' = (high − body bottom) ÷ range — always ≤ your percentile "
               f"setting ({cfg.patterns.hammer.percentile:g}); lower = body closer to the high "
               f"(stronger hammer).")
