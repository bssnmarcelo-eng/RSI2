"""Per-asset (independent) backtest mode."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd
import streamlit as st

from src import logger
from src.backtest_engine import BacktestEngine
from src.entry_selection import select_trades_per_entry_date
from src.types import PortfolioEntryRanking
from src.utils import fmt_money
from ui.data_source import _resolve_norgate_pending, collect_multi_asset_data
from ui.params_form import configuration_form
from ui.render import aggregate_trade_stats, render_trades_overview
from ui.run_logging import save_to_log


def run_per_asset_mode(note: str = "", data_src: dict | None = None):
    data_box = st.container()
    cfg, selection, submitted = configuration_form("per_asset", with_run=True)

    with data_box:
        st.subheader("📥 Dados")
        pending = collect_multi_asset_data(cfg, "Ativos para testar independentemente", data_src)
        is_pending = isinstance(pending, dict) and pending.get("_pending")
        data_by_ticker = None
        option_data_by_ticker = None
        if pending is None:
            st.session_state.pop("_per_asset_combined", None)
            st.session_state.pop("_per_asset_results", None)
        elif not is_pending:
            data_by_ticker = pending
            st.caption(f"Testing **{len(data_by_ticker)}** assets independently · "
                       f"**{fmt_money(cfg.initial_capital, 0)}** capital applied to each · "
                       f"trade stats pooled across all assets.")
        else:
            st.caption(
                f"**{len(pending['symbols'])}** ativos selecionados via Norgate · "
                f"capital **{fmt_money(cfg.initial_capital, 0)}** por ativo · "
                f"{pending['start']} → {pending['end']}"
            )

    if submitted and pending is not None:
        if is_pending:
            resolved = _resolve_norgate_pending(pending, cfg)
            if resolved is not None:
                data_by_ticker, option_data_by_ticker = resolved
        if data_by_ticker is not None:
            all_trades = []
            results_by_ticker = {}
            _total = len(data_by_ticker)
            _bar = st.progress(0.0, text=f"0 / {_total} ativos processados…")
            for _idx, (t, d) in enumerate(data_by_ticker.items()):
                _bar.progress(
                    _idx / _total,
                    text=f"[{_idx + 1}/{_total}] {t} · {len(d):,} barras…",
                )
                res = BacktestEngine(
                    d,
                    replace(cfg, ticker=t),
                    option_data=(option_data_by_ticker or {}).get(t),
                ).run()
                results_by_ticker[t] = res
                if not res.trades.empty:
                    all_trades.append(res.trades)
            _bar.progress(1.0, text=f"Concluído! {_total} ativos · {sum(len(r.trades) for r in results_by_ticker.values())} trades")

            combined = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame(
                columns=["ticker", "signal_date", "rsi_at_signal", "pattern", "entry_date",
                         "entry_price", "exit_date", "exit_price", "exit_reason", "bars_held",
                         "gross_return", "net_return", "pnl"])
            combined = select_trades_per_entry_date(combined, results_by_ticker, selection)
            _bar.progress(
                1.0,
                text=f"Concluído! {_total} ativos · {len(combined)} operações selecionadas",
            )

            # Persist so reruns triggered by row-clicks can still render everything.
            st.session_state["_per_asset_results"] = results_by_ticker
            st.session_state["_per_asset_combined"] = combined
            st.session_state["_per_asset_n"] = len(data_by_ticker)
            st.session_state["_per_asset_selection"] = selection

            stats = aggregate_trade_stats(combined) if not combined.empty else {}
            starts = [d.index.min() for d in data_by_ticker.values()]
            ends = [d.index.max() for d in data_by_ticker.values()]
            save_to_log(
                "Per-asset",
                summary={"note": note, "tickers": ", ".join(sorted(data_by_ticker.keys())),
                         "n_assets": len(data_by_ticker),
                         "start": str(min(starts).date()), "end": str(max(ends).date()),
                         "n_trades": stats.get("total", 0), "win_rate": stats.get("win_rate", 0.0),
                         "loss_rate": stats.get("loss_rate", 0.0),
                         "profit_factor": stats.get("profit_factor", 0.0),
                         "expectancy": stats.get("expectancy_ret", 0.0),
                         "total_pnl": stats.get("total_pnl", 0.0),
                         "avg_holding": stats.get("avg_holding", 0.0)},
                tables={"all_operations": combined},
                full={"meta": {"tickers": sorted(data_by_ticker.keys()), "n_assets": len(data_by_ticker),
                               "start": str(min(starts).date()), "end": str(max(ends).date())},
                      "config": logger.config_dict(cfg, selection), "metrics": stats})
    elif submitted and pending is None:
        st.warning("Carregue os dados antes de rodar (seção 📥 Dados acima).")

    # Always render from session_state — survives every rerun (row clicks, sort changes, etc).
    if "_per_asset_combined" in st.session_state:
        st.markdown("---")
        active_selection = st.session_state.get("_per_asset_selection", selection)
        ranking_names = {
            PortfolioEntryRanking.LOWEST_RSI: "menor RSI(2)",
            PortfolioEntryRanking.LARGEST_HAMMER_ATR: "maior Hammer em ATR",
            PortfolioEntryRanking.HIGHEST_RELATIVE_VOLUME: "maior volume relativo",
            PortfolioEntryRanking.STRONGEST_TREND: "tendência mais forte",
            PortfolioEntryRanking.HIGHEST_VOLATILITY: "maior volatilidade",
        }
        st.info(
            f"Seleção aplicada: no máximo {active_selection.max_entries_per_date} operação(ões) "
            f"por data, priorizando {ranking_names[active_selection.entry_ranking]}."
        )
        render_trades_overview(
            st.session_state["_per_asset_combined"],
            st.session_state.get("_per_asset_n", 0),
        )
