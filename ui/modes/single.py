"""Single-asset backtest mode."""
from __future__ import annotations

import streamlit as st

from src import data_loader, logger, norgate_loader
from src.backtest_engine import BacktestEngine
from src.performance_metrics import compute_metrics
from ui.data_source import collect_norgate_single, date_range_picker, load_combined
from ui.params_form import configuration_form
from ui.render import render_charts, render_metrics, render_trade_log
from ui.run_logging import _equity_frame, save_to_log


def _render_single_results() -> None:
    """Render persisted single-asset results in tabs (Resumo / Gráficos / Trade Log)."""
    res = st.session_state.get("_single_result")
    if res is None:
        return
    meta = st.session_state.get("_single_meta", {})
    st.markdown("---")
    if meta:
        st.caption(f"Resultados de **{meta['ticker']}** ({meta['start']} → {meta['end']}).")
    tab_sum, tab_charts, tab_log = st.tabs(["📊 Resumo", "📈 Gráficos", "📒 Trade Log"])
    with tab_sum:
        render_metrics(st.session_state["_single_metrics"])
    with tab_charts:
        render_charts(res)
    with tab_log:
        render_trade_log(res.trades, res.equity_curve, key="single")


def run_single_mode(note: str = "", data_src: dict | None = None):
    data_src = data_src or {"source": "CSV upload", "adjustment": norgate_loader.ADJ_LABELS[0]}

    # Reserve the data section at the top, then build the parameter form below it
    # (so ``cfg`` is available while loading data), then fill the data section.
    data_box = st.container()
    cfg, _pconf, submitted = configuration_form("single", with_run=True)

    selected = None
    data = None
    with data_box:
        st.subheader("📥 Dados")
        if data_src["source"] == "Norgate Data":
            data, selected = collect_norgate_single(cfg, data_src)
        else:
            uploaded = st.file_uploader(
                "Upload an OHLCV CSV (columns: date, ticker/symbol, open, high, low, close, "
                "adj/adjusted close, volume). Decimal commas, ; separators and DD/MM/YYYY dates are handled.",
                type=["csv"], accept_multiple_files=False)
            if uploaded is None:
                st.info("⬆️ Upload a CSV to begin. All processing is local — no external APIs are used.")
            else:
                combined = load_combined(uploaded)
                if not combined.empty:
                    tickers = data_loader.get_tickers(combined)
                    selected = (tickers[0] if len(tickers) == 1
                                else st.selectbox("Ticker", tickers) if tickers else None)
                    if tickers and len(tickers) == 1:
                        st.caption(f"Single ticker detected: **{selected}**")
                    start, end = date_range_picker(combined)
                    if start is not None:
                        prepared, warns = data_loader.prepare(
                            combined, ticker=selected, start=start, end=end)
                        for w in warns:
                            st.warning(w)
                        if prepared.empty:
                            st.error("No data in the selected range.")
                        else:
                            data = prepared
        if data is not None:
            cfg.ticker = selected or ""
            st.caption(f"Loaded **{len(data)}** candles "
                       f"({data.index.min().date()} → {data.index.max().date()}).")

    # Drop persisted results once the loaded data no longer matches what produced
    # them, so stale metrics/charts never render against a different selection.
    _sig = None
    if data is not None:
        _restrict = st.session_state.get("_ng_restrict")
        _index = st.session_state.get("_ng_index_name")
        _sig = (f"{cfg.ticker}|{data.index.min()}|{data.index.max()}|{len(data)}"
                f"|{_restrict}|{_index}")
        if ("_single_result" in st.session_state
                and st.session_state.get("_single_sig") != _sig):
            for _k in ("_single_result", "_single_metrics", "_single_meta", "_single_sig"):
                st.session_state.pop(_k, None)

    if submitted and data is not None:
        if not cfg.patterns.any_enabled():
            st.error("Habilite ao menos um padrão de candlestick (aba Entrada).")
        else:
            _n = len(data)
            _bar = st.progress(0.0, text=f"Processando {cfg.ticker} · 0 / {_n:,} barras…")
            result = BacktestEngine(data, cfg).run(
                progress=lambda p: _bar.progress(
                    p, text=f"Processando {cfg.ticker} · {int(p * _n):,} / {_n:,} barras…"
                )
            )
            _bar.progress(1.0, text=f"Concluído! {_n:,} barras · {len(result.trades)} trades")
            metrics = compute_metrics(result.equity_curve, result.trades, cfg.initial_capital, _n)
            for w in result.warnings:
                st.warning(w)
            st.session_state["_single_result"] = result
            st.session_state["_single_metrics"] = metrics
            st.session_state["_single_meta"] = {
                "ticker": selected or "", "start": str(data.index.min().date()),
                "end": str(data.index.max().date())}
            st.session_state["_single_sig"] = _sig

            save_to_log(
                "Single asset",
                summary={"note": note, "tickers": selected or "", "n_assets": 1,
                         "start": str(data.index.min().date()), "end": str(data.index.max().date()),
                         "n_trades": int(metrics["num_trades"]), "total_return": metrics["total_return"],
                         "cagr": metrics["cagr"], "sharpe": metrics["sharpe"], "win_rate": metrics["win_rate"],
                         "profit_factor": metrics["profit_factor"], "max_drawdown": metrics["max_drawdown"],
                         "final_equity": metrics["final_equity"]},
                tables={"trades": result.trades, "equity": _equity_frame(result.equity_curve)},
                full={"meta": {"ticker": selected, "start": str(data.index.min().date()),
                               "end": str(data.index.max().date()), "candles": len(data)},
                      "config": logger.config_dict(cfg), "metrics": metrics})
    elif submitted and data is None:
        st.warning("Carregue os dados antes de rodar (seção 📥 Dados acima).")

    _render_single_results()
