"""Data-source UI: sidebar source picker, Norgate pickers/caches, CSV loading,
and the shared multi-asset data collection used by every backtest mode."""
from __future__ import annotations

import streamlit as st

from src import data_loader, norgate_loader
from src.types import StrategyConfig


def build_data_source_params() -> dict:
    """Render sidebar data-source widgets; return {"source", "adjustment", "frequency"}."""
    st.sidebar.header("📡 Data Source")
    source = st.sidebar.radio(
        "Fonte de dados",
        ["CSV upload", "Norgate Data"],
        index=0,
        horizontal=True,
    )
    adj  = norgate_loader.ADJ_LABELS[0]
    freq = norgate_loader.FREQ_LABELS[0]   # "Semanal" default
    if source == "Norgate Data":
        freq = st.sidebar.selectbox(
            "Periodicidade",
            norgate_loader.FREQ_LABELS,
            index=0,
            help="Semanal é o padrão recomendado para estratégias de médio prazo.",
        )
        adj = st.sidebar.selectbox(
            "Ajuste de preço",
            norgate_loader.ADJ_LABELS,
            index=0,
            help="Total Return é o padrão para backtests — ajusta splits e dividendos.",
        )
        if not norgate_loader.is_available():
            st.sidebar.error(
                "⚠️ Norgate Data Updater (NDU) não está rodando "
                "ou o pacote norgatedata não está instalado.\n\n"
                "`pip install norgatedata`"
            )
    return {"source": source, "adjustment": adj, "frequency": freq}


def _ng_symbol_list(collection_type: str, collection_name: str) -> list[str]:
    """Return symbol list for the chosen watchlist or database."""
    if collection_type == "Watchlist":
        return _ng_watchlist_symbols(collection_name)
    return _ng_database_symbols(collection_name)


def _ng_collection_ui(key_prefix: str) -> tuple[str, str]:
    """Render watchlist/database picker; return (collection_type, collection_name)."""
    ctype = st.radio(
        "Tipo de coleção",
        ["Watchlist", "Database"],
        horizontal=True,
        key=f"{key_prefix}_ctype",
    )
    if ctype == "Watchlist":
        names = _ng_watchlists()
        if not names:
            st.warning("Nenhuma watchlist encontrada no Norgate.")
            return ctype, ""
        # Suggest the most useful default for equity backtesting.
        default_idx = next(
            (i for i, n in enumerate(names) if "Current & Past" in n and "S&P 500" in n),
            0,
        )
        name = st.selectbox("Watchlist", names, index=default_idx, key=f"{key_prefix}_wl")
    else:
        names = _ng_databases()
        if not names:
            st.warning("Nenhum database encontrado no Norgate.")
            return ctype, ""
        default_idx = next(
            (i for i, n in enumerate(names) if "US Equities" in n), 0
        )
        name = st.selectbox("Database", names, index=default_idx, key=f"{key_prefix}_db")
    return ctype, name


def _ng_date_range_ui(key_prefix: str):
    """Date range widgets for Norgate mode; returns (start_date_str, end_date_str)."""
    import datetime
    c1, c2 = st.columns(2)
    start = c1.date_input(
        "Data inicial",
        value=datetime.date(1990, 1, 1),
        min_value=datetime.date(1990, 1, 1),
        key=f"{key_prefix}_start",
    )
    end = c2.date_input(
        "Data final",
        value=datetime.date.today(),
        min_value=datetime.date(1990, 1, 1),
        key=f"{key_prefix}_end",
    )
    if start > end:
        st.error("Data inicial deve ser anterior à data final.")
        return None, None
    return str(start), str(end)


def collect_norgate_single(cfg: StrategyConfig, data_src: dict):
    """Norgate data-loading UI for single-asset mode.

    Returns (data_df, ticker_str) or (None, None) if not ready.
    """
    if not norgate_loader.is_available():
        st.error("Norgate Data Updater não está rodando. Inicie o NDU e tente novamente.")
        return None, None

    st.header("1 · Selecionar ativo")
    ctype, cname = _ng_collection_ui("ng_single")
    if not cname:
        return None, None

    with st.spinner("Carregando lista de ativos do Norgate…"):
        symbols = _ng_symbol_list(ctype, cname)
    if not symbols:
        st.error(f"Nenhum símbolo encontrado em '{cname}'.")
        return None, None

    ticker = st.selectbox(
        f"Ativo ({len(symbols)} disponíveis)",
        symbols,
        key="ng_single_ticker",
    )

    st.header("2 · Período")
    start_str, end_str = _ng_date_range_ui("ng_single")
    if start_str is None:
        return None, None

    with st.spinner(f"Carregando dados de {ticker}…"):
        df, warns = norgate_loader.fetch_price(
            ticker, data_src["adjustment"], start_str, end_str,
            frequency_label=data_src.get("frequency", "Semanal"),
        )
    for w in warns:
        st.warning(w)
    if df.empty:
        st.error(f"Sem dados para {ticker} no período selecionado.")
        return None, None

    st.caption(
        f"**{ticker}** · {len(df)} barras "
        f"({df.index.min().date()} → {df.index.max().date()}) · "
        f"{data_src.get('frequency', 'Semanal')} · ajuste: {data_src['adjustment']}"
    )
    cfg.ticker = ticker
    return df, ticker


def collect_norgate_multi(cfg: StrategyConfig, data_src: dict, select_label: str):
    """Norgate data-loading UI for multi-asset modes.

    Returns data_by_ticker dict or None if not ready.
    """
    if not norgate_loader.is_available():
        st.error("Norgate Data Updater não está rodando. Inicie o NDU e tente novamente.")
        return None

    st.header("1 · Selecionar ativos")
    ctype, cname = _ng_collection_ui("ng_multi")
    if not cname:
        return None

    with st.spinner("Carregando lista de ativos do Norgate…"):
        all_symbols = _ng_symbol_list(ctype, cname)
    if not all_symbols:
        st.error(f"Nenhum símbolo encontrado em '{cname}'.")
        return None

    st.caption(
        f"**{len(all_symbols)}** ativos em '{cname}' — inclui deslistados "
        f"e constituintes históricos."
    )
    default_sel = all_symbols[:50] if len(all_symbols) > 50 else all_symbols
    selected = st.multiselect(
        select_label,
        all_symbols,
        default=default_sel,
        key="ng_multi_sel",
    )
    if not selected:
        st.warning("Selecione ao menos um ativo.")
        return None

    st.header("2 · Período")
    start_str, end_str = _ng_date_range_ui("ng_multi")
    if start_str is None:
        return None

    if not cfg.patterns.any_enabled():
        st.error("Habilite ao menos um padrão de candlestick na aba 📥 Entrada.")
        return None

    return {"_pending": True, "symbols": selected, "start": start_str,
            "end": end_str, "adjustment": data_src["adjustment"],
            "frequency": data_src.get("frequency", "Semanal")}


def load_combined(uploaded):
    combined, warnings, errors = data_loader.load_and_combine(uploaded)
    for e in errors:
        st.error(e)
    for w in warnings:
        st.warning(w)
    return combined


def date_range_picker(combined, label_suffix=""):
    min_d, max_d = data_loader.date_bounds(combined)
    if min_d is None:
        st.error("No parseable dates found in the data.")
        return None, None
    c1, c2 = st.columns(2)
    start = c1.date_input("Start date" + label_suffix, value=min_d, min_value=min_d, max_value=max_d)
    end = c2.date_input("End date" + label_suffix, value=max_d, min_value=min_d, max_value=max_d)
    if start > end:
        st.error("Start date must be on or before end date.")
        return None, None
    return start, end


def collect_multi_asset_data(
    cfg: StrategyConfig,
    select_label: str,
    data_src: dict | None = None,
):
    """Shared steps 1–2 for multi-asset modes: load data, pick tickers, date range.

    Supports both CSV upload and Norgate Data source.
    Returns a dict ``{ticker: cleaned_ohlc}`` or ``None`` if not ready.
    """
    data_src = data_src or {"source": "CSV upload", "adjustment": norgate_loader.ADJ_LABELS[0]}

    # ── Norgate path ──────────────────────────────────────────────────────────
    if data_src["source"] == "Norgate Data":
        pending = collect_norgate_multi(cfg, data_src, select_label)
        if pending is None:
            return None

        # pending is returned here; actual data fetch happens in the mode function
        # after the Run button is pressed (so we defer to avoid loading all data
        # on every sidebar interaction).
        return pending

    # ── CSV path ─────────────────────────────────────────────────────────────
    st.header("1 · Load data")
    uploaded = st.file_uploader(
        "Upload one CSV with multiple tickers (ticker/symbol column) **or** several "
        "single-ticker CSVs at once. Decimal commas, ; separators and DD/MM/YYYY dates are handled.",
        type=["csv"], accept_multiple_files=True)
    if not uploaded:
        st.info("⬆️ Upload your CSV file(s) to begin. All processing is local — no external APIs are used.")
        return None
    combined = load_combined(uploaded)
    if combined.empty:
        return None

    st.header("2 · Select tickers & date range")
    tickers = data_loader.get_tickers(combined)
    if not tickers:
        st.error("Could not identify any tickers. Provide a ticker/symbol column or name files per asset.")
        return None
    default_sel = tickers if len(tickers) <= 20 else tickers[:20]
    selected = st.multiselect(select_label, tickers, default=default_sel)
    if len(selected) < 1:
        st.warning("Select at least one ticker.")
        return None
    start, end = date_range_picker(combined)
    if start is None:
        return None

    if not cfg.patterns.any_enabled():
        st.error("Enable at least one candlestick pattern in the 📥 Entrada tab.")
        return None

    # Prepare each ticker independently (per-ticker dedup/clean).
    data_by_ticker = {}
    skipped = []
    for t in selected:
        d, _ = data_loader.prepare(combined, ticker=t, start=start, end=end)
        if d.empty or len(d) < max(cfg.rsi_period + 2, 5):
            skipped.append(t)
            continue
        data_by_ticker[t] = d
    if skipped:
        st.warning(f"Skipped (too few/no candles in range): {', '.join(skipped)}")
    if not data_by_ticker:
        st.error("No usable tickers in the selected range.")
        return None
    return data_by_ticker


def _resolve_norgate_pending(pending: dict, cfg: StrategyConfig) -> dict | None:
    """Fetch Norgate data for a pending multi-asset spec (called inside Run spinner).

    Returns a ready {ticker: df} dict, or None on failure.
    """
    symbols = pending["symbols"]
    min_bars = max(cfg.rsi_period + 2, 5)
    bar = st.progress(0.0, text="Baixando dados do Norgate…")

    data, warns, skipped = norgate_loader.fetch_many(
        symbols,
        adjustment_label=pending["adjustment"],
        start_date=pending["start"],
        end_date=pending["end"],
        min_bars=min_bars,
        frequency_label=pending.get("frequency", "Semanal"),
        progress=lambda p: bar.progress(p, text="Baixando dados do Norgate…"),
    )
    bar.empty()
    for w in warns:
        st.warning(w)
    if skipped:
        st.warning(
            f"Ignorados (sem dados suficientes no período): "
            f"{', '.join(skipped[:20])}"
            + (f" … e mais {len(skipped) - 20}" if len(skipped) > 20 else "")
        )
    if not data:
        st.error("Nenhum ativo com dados válidos no período selecionado.")
        return None
    return data


@st.cache_data(ttl=3600, show_spinner=False)
def _ng_watchlists():
    return norgate_loader.get_watchlists()


@st.cache_data(ttl=3600, show_spinner=False)
def _ng_watchlist_symbols(name: str):
    return norgate_loader.get_watchlist_symbols(name)


@st.cache_data(ttl=3600, show_spinner=False)
def _ng_databases():
    return norgate_loader.get_databases()


@st.cache_data(ttl=3600, show_spinner=False)
def _ng_database_symbols(name: str):
    return norgate_loader.get_database_symbols(name)
