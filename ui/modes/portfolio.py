"""Portfolio (shared capital) backtest mode."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import logger
from src.performance_metrics import compute_metrics
from src.portfolio_engine import PortfolioEngine
from src.types import PortfolioSizing
from src.utils import fmt_money
from ui.data_source import _resolve_norgate_pending, collect_multi_asset_data
from ui.params_form import configuration_form
from ui.render import render_portfolio, render_portfolio_metrics, render_trade_log
from ui.run_logging import _equity_frame, save_to_log


def _render_portfolio_results() -> None:
    """Render persisted portfolio results in tabs (Resumo / Gráficos & Ativos / Trade Log)."""
    res = st.session_state.get("_portfolio_result")
    if res is None:
        return
    meta = st.session_state.get("_portfolio_meta", {})
    st.markdown("---")
    if meta:
        st.caption(f"Resultados de **{meta['n_assets']}** ativos "
                   f"({meta['start']} → {meta['end']}).")
    if res.portfolio.use_breadth_filter:
        st.info(
            f"Filtro ativo: novas entradas exigem breadth ≥ "
            f"{res.portfolio.breadth_threshold_pct:g}% acima da "
            f"MM{res.portfolio.breadth_sma_period}. Posições abertas não são encerradas pelo filtro."
        )
    tab_sum, tab_charts, tab_log = st.tabs(["Resumo", "Gráficos e ativos", "Operações"])
    with tab_sum:
        render_portfolio_metrics(st.session_state["_portfolio_metrics"], res)
    with tab_charts:
        render_portfolio(res)
    with tab_log:
        render_trade_log(res.trades, res.equity_curve, key="pf")


def run_portfolio_mode(note: str = "", data_src: dict | None = None):
    data_box = st.container()
    cfg, pconf, submitted = configuration_form("portfolio", with_run=True)

    data_by_ticker = None
    option_data_by_ticker = None
    _pf_sig = None
    with data_box:
        st.subheader("📥 Dados")
        pending = collect_multi_asset_data(
            cfg,
            "Ativos da carteira",
            data_src,
            breadth_filter=pconf.use_breadth_filter,
        )
        is_pending = isinstance(pending, dict) and pending.get("_pending")
        if pending is not None and not is_pending:
            data_by_ticker = pending
            total_bars = sum(len(d) for d in data_by_ticker.values())
            _pf_sig = f"csv|{sorted(data_by_ticker.keys())}|{total_bars}"
            if pconf.sizing_mode == PortfolioSizing.FULL_EQUITY:
                sizing_txt = "**100%**/trade · **unlimited** buying power"
            else:
                sizing_txt = f"**{pconf.pct_per_trade:g}%**/trade · **{pconf.leverage:g}×** leverage"
            st.caption(f"Carteira com **{len(data_by_ticker)}** ativos · "
                       f"capital **{fmt_money(pconf.initial_capital, 0)}** · {sizing_txt} · "
                       f"{total_bars:,} candle-rows.")
        elif is_pending:
            _pf_sig = (f"ng|{pending['symbols']}|{pending['start']}|{pending['end']}"
                       f"|{pending['adjustment']}|{pending.get('frequency')}"
                       f"|{pending.get('index_name')}|{pending.get('restrict')}")
            st.caption(
                f"**{len(pending['symbols'])}** ativos selecionados via Norgate · "
                f"capital **{fmt_money(pconf.initial_capital, 0)}** · "
                f"{pending['start']} → {pending['end']}"
            )

    # Drop persisted results once the data selection no longer matches them.
    if (_pf_sig is not None and "_portfolio_result" in st.session_state
            and st.session_state.get("_portfolio_sig") != _pf_sig):
        for _k in ("_portfolio_result", "_portfolio_metrics", "_portfolio_meta", "_portfolio_sig"):
            st.session_state.pop(_k, None)

    if submitted and pending is not None:
        _bar = st.progress(0.0, text="Preparando sinais…")
        if (is_pending and pconf.use_breadth_filter
                and (not pending.get("restrict") or not pending.get("complete_universe"))):
            _bar.empty()
            st.error(
                "Para calcular o breadth do índice corretamente, selecione a coleção inteira "
                "e ative os constituintes históricos point-in-time."
            )
            return
        if is_pending:
            resolved = _resolve_norgate_pending(pending, cfg)
            if resolved is not None:
                data_by_ticker, option_data_by_ticker = resolved
        if data_by_ticker is None:
            _bar.empty()
        else:
            _n_assets = len(data_by_ticker)
            _bar.progress(0.0, text=f"Executando portfolio · {_n_assets} ativos…")
            result = PortfolioEngine(
                data_by_ticker, cfg, pconf,
                option_data_by_ticker=option_data_by_ticker,
            ).run(
                progress=lambda p: _bar.progress(
                    p, text=f"Executando portfolio · {p:.0%} do calendário processado…"
                )
            )
            _bar.progress(1.0, text=f"Concluído! {_n_assets} ativos · {len(result.trades)} trades")
            metrics = compute_metrics(result.equity_curve, result.trades, pconf.initial_capital,
                                      len(result.equity_curve))
            metrics["exposure"] = result.time_in_market
            for w in result.warnings:
                st.warning(w)
            st.session_state["_portfolio_result"] = result
            st.session_state["_portfolio_metrics"] = metrics
            st.session_state["_portfolio_sig"] = _pf_sig

            tickers = sorted(result.frames.keys())
            eq = result.equity_curve
            st.session_state["_portfolio_meta"] = {
                "n_assets": len(tickers), "start": str(eq.index.min().date()),
                "end": str(eq.index.max().date())}
            positions = pd.concat(
                [result.positions_open, result.exposure, result.breadth], axis=1
            )
            save_to_log(
                "Portfolio",
                summary={"note": note, "tickers": ", ".join(tickers), "n_assets": len(tickers),
                         "sizing_mode": pconf.sizing_mode.value,
                         "start": str(eq.index.min().date()), "end": str(eq.index.max().date()),
                         "n_trades": int(metrics["num_trades"]), "total_return": metrics["total_return"],
                         "cagr": metrics["cagr"], "sharpe": metrics["sharpe"],
                         "max_drawdown": metrics["max_drawdown"], "win_rate": metrics["win_rate"],
                         "profit_factor": metrics["profit_factor"], "final_equity": metrics["final_equity"],
                         "time_in_market": result.time_in_market, "max_concurrent": result.max_concurrent},
                tables={"trades": result.trades, "equity": _equity_frame(eq), "positions": positions},
                full={"meta": {"tickers": tickers, "n_assets": len(tickers),
                               "start": str(eq.index.min().date()), "end": str(eq.index.max().date())},
                      "config": logger.config_dict(cfg, pconf), "metrics": metrics})
    elif submitted and pending is None:
        st.warning("Carregue os dados antes de rodar (seção 📥 Dados acima).")

    _render_portfolio_results()
