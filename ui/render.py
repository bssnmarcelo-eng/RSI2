"""Shared result-rendering helpers (metrics grids, charts, trade tables)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import charts, norgate_loader
from src.advanced_analysis import (
    buy_and_hold_equity,
    compare_with_benchmark,
    monte_carlo_summary,
    monte_carlo_trades,
)
from src.utils import fmt_money, fmt_num, fmt_pct


@st.cache_data(ttl=3600, show_spinner=False)
def _membership_label(symbol: str, indexname: str) -> str:
    """Cached per-(symbol, index) point-in-time membership periods string."""
    return norgate_loader.membership_label(symbol, indexname)


def _index_name_from_state():
    """The Norgate index chosen for membership history, or None."""
    return st.session_state.get("_ng_index_name")


def render_trade_log(trades: pd.DataFrame, equity: pd.Series, key: str) -> None:
    st.subheader("Registro de operações")
    if trades.empty:
        st.info("Nenhuma operação foi gerada com os parâmetros atuais.")
        return
    display = trades.copy()
    for col in ["signal_close", "entry_price", "exit_price", "pnl", "equity_after"]:
        display[col] = display[col].map(fmt_money)
    display["rsi_at_signal"] = display["rsi_at_signal"].map(lambda v: fmt_num(v, 2))
    if "signal_range" in display:
        display["signal_range"] = trades["signal_range"].map(lambda v: fmt_num(v, 2))
    if "signal_body_percentile" in display:
        display["signal_body_percentile"] = trades["signal_body_percentile"].map(lambda v: fmt_num(v, 3))
    if "signal_atr_mult" in display:
        display["signal_atr_mult"] = trades["signal_atr_mult"].map(lambda v: fmt_num(v, 2))
    display["gross_return"] = trades["gross_return"].map(fmt_pct)
    display["net_return"] = trades["net_return"].map(fmt_pct)
    for mfe_col in ["mfe", "mfe_1w", "mfe_2w", "mfe_3w", "mfe_4w", "mfe_5w", "mfe_12w"]:
        if mfe_col in display:
            display[mfe_col] = trades[mfe_col].map(lambda v: fmt_pct(v) if pd.notna(v) else "—")
    for col in ["option_underlying_entry_price", "option_underlying_exit_price",
                "option_strike", "option_entry_price", "option_exit_price", "option_pnl",
                "option_commissions"]:
        if col in display:
            display[col] = trades[col].map(lambda v: fmt_money(v) if pd.notna(v) else "—")
    for col in ["option_underlying_return", "option_gross_return", "option_net_return",
                "option_iv_entry", "option_iv_exit", "option_mfe"]:
        if col in display:
            display[col] = trades[col].map(lambda v: fmt_pct(v) if pd.notna(v) else "—")
    st.dataframe(display, use_container_width=True, hide_index=True)
    cols = st.columns(2)
    cols[0].download_button("Baixar operações (CSV)", data=trades.to_csv(index=False).encode("utf-8"),
                            file_name="trade_log.csv", mime="text/csv", key=f"{key}_trades")
    eq = equity.rename("equity").to_frame()
    eq.index.name = "date"
    cols[1].download_button("Baixar curva patrimonial (CSV)", data=eq.to_csv().encode("utf-8"),
                            file_name="equity_curve.csv", mime="text/csv", key=f"{key}_equity")


def render_portfolio_metrics(metrics: dict, result) -> None:
    st.subheader("Desempenho da carteira")
    r1 = st.columns(4)
    r1[0].metric("Patrimônio final", fmt_money(metrics["final_equity"]))
    r1[1].metric("Retorno total", fmt_pct(metrics["total_return"]))
    r1[2].metric("CAGR", fmt_pct(metrics["cagr"]))
    r1[3].metric("Drawdown máximo", fmt_pct(metrics["max_drawdown"]))
    r2 = st.columns(4)
    r2[0].metric("Operações", f"{metrics['num_trades']}")
    r2[1].metric("Taxa de acerto", fmt_pct(metrics["win_rate"]))
    pf = metrics["profit_factor"]
    r2[2].metric("Fator de lucro", "∞" if pf == float("inf") else fmt_num(pf))
    r2[3].metric("Expectativa por operação", fmt_money(metrics["expectancy"]))
    r3 = st.columns(4)
    r3[0].metric("Sharpe", fmt_num(metrics["sharpe"]))
    r3[1].metric("Sortino", fmt_num(metrics["sortino"]))
    r3[2].metric("Tempo no mercado", fmt_pct(result.time_in_market))
    r3[3].metric("Média de posições", fmt_num(result.avg_positions, 2))
    r4 = st.columns(4)
    r4[0].metric("Pico simultâneo", f"{result.max_concurrent}")
    r4[1].metric("Exposição bruta máxima", fmt_pct(result.exposure.max()))
    r4[2].metric("Melhor operação", fmt_pct(metrics["best_trade"]))
    r4[3].metric("Pior operação", fmt_pct(metrics["worst_trade"]))
    r5 = st.columns(3)
    r5[0].metric("Calmar", fmt_num(metrics.get("calmar", 0.0)))
    r5[1].metric("Ulcer Index", fmt_pct(metrics.get("ulcer_index", 0.0)))
    r5[2].metric("Volatilidade anual", fmt_pct(metrics.get("volatility", 0.0)))
    if result.financing_costs or result.dividend_income:
        r6 = st.columns(2)
        r6[0].metric("Juros de margem", fmt_money(-result.financing_costs))
        r6[1].metric("Dividendos recebidos", fmt_money(result.dividend_income))
    if result.config.options.enabled:
        st.markdown("#### Sensibilidade da call sintética")
        st.caption("Mark-to-model: os cenários recalculam IV, contratos e patrimônio com os mesmos sinais da ação.")
        scenario_metrics = getattr(result, "scenario_metrics", {})
        scenario_equity = getattr(result, "scenario_equity", {})
        labels = [("low", "IV baixa (0,85×)"), ("base", "IV base"), ("high", "IV alta (1,15×)")]
        cols = st.columns(3)
        for col, (key, label) in zip(cols, labels, strict=True):
            values = scenario_metrics.get(key, {})
            col.metric(label, fmt_pct(values.get("total_return", 0.0)),
                       fmt_money(values.get("final_equity", 0.0)))
        available = [(key, label) for key, label in labels if key in scenario_equity]
        if available:
            tabs = st.tabs([label for _, label in available])
            for tab, (key, _label) in zip(tabs, available, strict=True):
                with tab:
                    st.plotly_chart(
                        charts.equity_chart(scenario_equity[key], result.portfolio.initial_capital),
                        use_container_width=True,
                    )


def per_ticker_table(trades: pd.DataFrame, indexname: str | None = None) -> pd.DataFrame:
    g = trades.groupby("ticker")
    tbl = pd.DataFrame({
        "Trades": g.size(),
        "Win rate": g["net_return"].apply(lambda s: (s > 0).mean()),
        "Net P&L": g["pnl"].sum(),
        "Avg return": g["net_return"].mean(),
        "Best": g["net_return"].max(),
        "Worst": g["net_return"].min(),
    }).sort_values("Net P&L", ascending=False)
    out = tbl.copy()
    out["Win rate"] = tbl["Win rate"].map(fmt_pct)
    out["Net P&L"] = tbl["Net P&L"].map(fmt_money)
    out["Avg return"] = tbl["Avg return"].map(fmt_pct)
    out["Best"] = tbl["Best"].map(fmt_pct)
    out["Worst"] = tbl["Worst"].map(fmt_pct)
    out = out.reset_index().rename(columns={"ticker": "Ticker"})
    if indexname:
        out[f"No índice ({indexname})"] = out["Ticker"].map(
            lambda t: _membership_label(t, indexname))
    return out


def render_portfolio(result) -> None:
    cfg = result.config
    st.subheader("Gráficos da carteira")
    c1, c2 = st.columns(2)
    c1.plotly_chart(charts.equity_chart(result.equity_curve, result.portfolio.initial_capital),
                    use_container_width=True)
    c2.plotly_chart(charts.drawdown_chart(result.equity_curve), use_container_width=True)
    c3, c4 = st.columns(2)
    c3.plotly_chart(charts.positions_over_time(result.positions_open), use_container_width=True)
    c4.plotly_chart(charts.returns_histogram(result.trades), use_container_width=True)
    c5, c6 = st.columns(2)
    c5.plotly_chart(charts.ticker_contribution(result.trades), use_container_width=True)
    c6.plotly_chart(charts.yearly_bar(result.equity_curve), use_container_width=True)
    st.plotly_chart(charts.monthly_heatmap(result.equity_curve), use_container_width=True)

    st.subheader("Comparação com benchmark")
    benchmark_ticker = st.selectbox(
        "Benchmark (buy and hold)", sorted(result.frames), key="portfolio_benchmark"
    )
    benchmark = buy_and_hold_equity(
        result.frames[benchmark_ticker]["close"], result.portfolio.initial_capital
    )
    comparison = compare_with_benchmark(result.equity_curve, benchmark)
    if comparison:
        bcols = st.columns(3)
        bcols[0].metric("Retorno da estratégia", fmt_pct(comparison["strategy_return"]))
        bcols[1].metric(f"Retorno de {benchmark_ticker}", fmt_pct(comparison["benchmark_return"]))
        bcols[2].metric("Retorno excedente", fmt_pct(comparison["excess_return"]))
        st.plotly_chart(
            charts.benchmark_chart(result.equity_curve, benchmark, f"Estratégia vs. {benchmark_ticker}"),
            use_container_width=True,
        )

    with st.expander("Simulação Monte Carlo das operações", expanded=False):
        simulations = monte_carlo_trades(
            result.trades, result.portfolio.initial_capital, simulations=2_000
        )
        summary = monte_carlo_summary(simulations)
        if not summary:
            st.info("São necessárias operações para executar a simulação.")
        else:
            st.caption(
                "Bootstrap das operações observadas; mede incerteza de sequência e amostragem, "
                "não prevê mudanças futuras de regime."
            )
            mcols = st.columns(4)
            mcols[0].metric("Probabilidade de perda", fmt_pct(summary["probability_of_loss"]))
            mcols[1].metric("Retorno P5", fmt_pct(summary["return_p05"]))
            mcols[2].metric("Retorno mediano", fmt_pct(summary["return_median"]))
            mcols[3].metric("Retorno P95", fmt_pct(summary["return_p95"]))

    st.subheader("Detalhamento por ativo")
    if result.trades.empty:
        st.info("Nenhuma operação foi gerada com os parâmetros atuais.")
    else:
        st.dataframe(per_ticker_table(result.trades, _index_name_from_state()),
                     use_container_width=True, hide_index=True)

    # Drill-down: inspect one asset's price + signals.
    st.subheader("Inspecionar um ativo")
    tickers = sorted(result.frames.keys())
    sel = st.selectbox("Ticker", tickers)
    frame = result.frames[sel]
    tr = result.trades[result.trades["ticker"] == sel] if not result.trades.empty else result.trades
    st.plotly_chart(charts.price_chart(frame, tr, sel), use_container_width=True)
    st.plotly_chart(charts.rsi_chart(frame, cfg.rsi_entry_threshold, cfg.exits.rsi_exit_threshold),
                    use_container_width=True)


def aggregate_trade_stats(trades: pd.DataFrame) -> dict:
    """Trade-level statistics pooled over ALL trades (ticker-agnostic)."""
    n = len(trades)
    nr = trades["net_return"]
    pnl = trades["pnl"]
    wins = nr[nr > 0]
    losses = nr[nr < 0]
    gross_win = pnl[pnl > 0].sum()
    gross_loss = abs(pnl[pnl < 0].sum())
    return {
        "total": n,
        "wins": int((nr > 0).sum()),
        "losses": int((nr < 0).sum()),
        "breakeven": int((nr == 0).sum()),
        "win_rate": len(wins) / n if n else 0.0,
        "loss_rate": len(losses) / n if n else 0.0,
        "avg_gain": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0
        else (float("inf") if gross_win > 0 else 0.0),
        "expectancy_ret": float(nr.mean()) if n else 0.0,
        "avg_pnl": float(pnl.mean()) if n else 0.0,
        "total_pnl": float(pnl.sum()) if n else 0.0,
        "best": float(nr.max()) if n else 0.0,
        "worst": float(nr.min()) if n else 0.0,
        "avg_holding": float(trades["bars_held"].mean()) if n else 0.0,
    }


def _max_consecutive(bool_series) -> int:
    """Max run of consecutive True values in a boolean iterable."""
    max_run = cur = 0
    for v in bool_series:
        if v:
            cur += 1
            max_run = max(max_run, cur)
        else:
            cur = 0
    return max_run


def per_asset_summary_table(
    trades: pd.DataFrame, indexname: str | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rich per-ticker statistics. Returns (display_df, raw_df) sorted by Total PnL desc."""

    rows = []
    for ticker, g in trades.groupby("ticker"):
        g = g.sort_values("entry_date").reset_index(drop=True)
        nr = g["net_return"]
        pnl = g["pnl"]
        wins_mask = nr > 0
        losses_mask = nr < 0
        n = len(g)
        n_wins = int(wins_mask.sum())
        n_losses = int(losses_mask.sum())
        n_be = n - n_wins - n_losses

        gross_win = float(pnl[wins_mask].sum())
        gross_loss = float(abs(pnl[losses_mask].sum()))

        avg_gain = float(nr[wins_mask].mean()) if n_wins else 0.0
        avg_loss = float(nr[losses_mask].mean()) if n_losses else 0.0  # negative
        payoff = abs(avg_gain / avg_loss) if avg_loss < 0 else (float("inf") if avg_gain > 0 else 0.0)
        pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
        win_rate = n_wins / n if n else 0.0

        if n_wins == 0:
            kelly = 0.0
        elif n_losses == 0:
            kelly = win_rate
        elif payoff == 0.0:
            kelly = 0.0
        else:
            kelly = win_rate - (1.0 - win_rate) / payoff

        std_ret = float(nr.std(ddof=1)) if n > 1 else 0.0
        median_ret = float(nr.median()) if n else 0.0

        rows.append({
            "Ticker": ticker,
            "Trades": n,
            "Wins": n_wins,
            "Losses": n_losses,
            "BE": n_be,
            "Win Rate": win_rate,
            "Loss Rate": n_losses / n if n else 0.0,
            "Profit Factor": pf,
            "Payoff Ratio": payoff,
            "Avg Gain": avg_gain,
            "Avg Loss": avg_loss,
            "Expectancy": float(nr.mean()) if n else 0.0,
            "Std Return": std_ret,
            "Median Return": median_ret,
            "Best Trade": float(nr.max()) if n else 0.0,
            "Worst Trade": float(nr.min()) if n else 0.0,
            "Total PnL": float(pnl.sum()),
            "Avg PnL": float(pnl.mean()) if n else 0.0,
            "Avg Holding": float(g["bars_held"].mean()) if n else 0.0,
            "Max Holding": int(g["bars_held"].max()) if n else 0,
            "Max Consec Wins": _max_consecutive(wins_mask),
            "Max Consec Losses": _max_consecutive(losses_mask),
            "Kelly %": kelly,
        })

    raw = (pd.DataFrame(rows)
           .sort_values("Total PnL", ascending=False)
           .reset_index(drop=True))
    if indexname:
        raw[f"No índice ({indexname})"] = raw["Ticker"].map(
            lambda t: _membership_label(t, indexname))

    disp = raw.copy()
    pct_cols = ["Win Rate", "Loss Rate", "Avg Gain", "Avg Loss", "Expectancy",
                "Std Return", "Median Return", "Best Trade", "Worst Trade", "Kelly %"]
    for col in pct_cols:
        disp[col] = raw[col].map(fmt_pct)
    for col in ["Total PnL", "Avg PnL"]:
        disp[col] = raw[col].map(fmt_money)
    disp["Profit Factor"] = raw["Profit Factor"].map(
        lambda v: "∞" if v == float("inf") else fmt_num(v))
    disp["Payoff Ratio"] = raw["Payoff Ratio"].map(
        lambda v: "∞" if v == float("inf") else fmt_num(v))
    disp["Avg Holding"] = raw["Avg Holding"].map(lambda v: fmt_num(v, 1))

    return disp, raw


def render_trades_overview(trades: pd.DataFrame, n_assets: int) -> None:
    """Aggregate trades panorama + table of every operation (per-asset mode)."""
    st.subheader("Visão geral das operações")
    if trades.empty:
        st.info("Nenhuma operação foi gerada com os parâmetros atuais.")
        return

    s = aggregate_trade_stats(trades)
    st.caption(f"**{n_assets}** assets tested independently (full capital applied to each). "
               f"Statistics pooled over **all {s['total']} trades**.")

    r1 = st.columns(4)
    r1[0].metric("Total trades", f"{s['total']}")
    r1[1].metric("Win rate", fmt_pct(s["win_rate"]))
    r1[2].metric("Loss rate", fmt_pct(s["loss_rate"]))
    pf = s["profit_factor"]
    r1[3].metric("Profit factor", "∞" if pf == float("inf") else fmt_num(pf))

    r2 = st.columns(4)
    r2[0].metric("Winning trades", f"{s['wins']}")
    r2[1].metric("Losing trades", f"{s['losses']}")
    r2[2].metric("Avg gain", fmt_pct(s["avg_gain"]))
    r2[3].metric("Avg loss", fmt_pct(s["avg_loss"]))

    r3 = st.columns(4)
    r3[0].metric("Expectancy / trade", fmt_pct(s["expectancy_ret"]))
    r3[1].metric("Best trade", fmt_pct(s["best"]))
    r3[2].metric("Worst trade", fmt_pct(s["worst"]))
    r3[3].metric("Avg holding (bars)", fmt_num(s["avg_holding"], 1))

    priced_options = (trades[trades["option_status"] == "priced"]
                      if "option_status" in trades else pd.DataFrame())
    if not priced_options.empty and "option_net_return" in priced_options:
        st.subheader("Equivalência das mesmas operações em Call sintética")
        option_returns = pd.to_numeric(priced_options["option_net_return"], errors="coerce").dropna()
        option_pnl = pd.to_numeric(priced_options["option_pnl"], errors="coerce").dropna()
        ocols = st.columns(4)
        ocols[0].metric("Trades precificados", f"{len(option_returns)} / {len(trades)}")
        ocols[1].metric("Taxa de acerto da call", fmt_pct(float((option_returns > 0).mean())))
        ocols[2].metric("Retorno médio da call", fmt_pct(float(option_returns.mean())))
        ocols[3].metric("P&L total equivalente", fmt_money(float(option_pnl.sum())))
        st.caption(
            "Os números principais acima continuam sendo das ações. Esta linha usa exatamente "
            "as mesmas entradas e saídas para estimar a call sintética."
        )

    # Per-asset breakdown table.
    st.subheader("Detalhamento por ativo")
    st.caption(
        "Each row is one ticker backtested independently. "
        "Sorted by Total PnL descending. "
        "**Payoff Ratio** = avg gain / |avg loss|. "
        "**Kelly %** = optimal fraction of capital per trade (full Kelly — halve it in practice)."
    )
    sort_col = st.selectbox(
        "Sort by",
        ["Total PnL", "Trades", "Win Rate", "Profit Factor", "Expectancy",
         "Best Trade", "Worst Trade", "Max Consec Wins", "Max Consec Losses",
         "Avg Holding", "Kelly %"],
        index=0,
        key="per_asset_sort",
    )
    disp_tbl, raw_tbl = per_asset_summary_table(trades, _index_name_from_state())
    # Re-sort display by the chosen column using the raw numeric values.
    sort_order = raw_tbl.sort_values(sort_col, ascending=False).index
    disp_sorted = disp_tbl.loc[sort_order].reset_index(drop=True)
    st.caption("💡 Clique em uma linha para abrir o gráfico do ativo com marcação das operações.")
    event = st.dataframe(
        disp_sorted,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="per_asset_tbl",
    )
    st.download_button(
        "Baixar resumo por ativo (CSV)",
        data=raw_tbl.sort_values(sort_col, ascending=False).to_csv(index=False).encode("utf-8"),
        file_name="per_asset_summary.csv",
        mime="text/csv",
        key="per_asset_csv",
    )

    # Chart drill-down: show chart for the selected row's ticker.
    sel_rows = (event.selection.rows
                if event and hasattr(event, "selection") and event.selection.rows
                else [])
    if sel_rows:
        sel_ticker = disp_sorted.iloc[sel_rows[0]]["Ticker"]
        res = st.session_state.get("_per_asset_results", {}).get(sel_ticker)
        if res is not None:
            st.subheader(f"📈 {sel_ticker} — Gráfico de Preço & Sinais")
            st.plotly_chart(
                charts.price_chart(
                    res.data, res.trades, sel_ticker,
                    rsi_entry=res.config.rsi_entry_threshold,
                    rsi_exit=res.config.exits.rsi_exit_threshold,
                ),
                use_container_width=True,
            )

    # Distribution of all trade returns.
    st.subheader("Distribuição dos retornos agregados")
    st.plotly_chart(charts.returns_histogram(trades), use_container_width=True)

    with st.expander("Simulação Monte Carlo agregada", expanded=False):
        simulations = monte_carlo_trades(trades, simulations=2_000)
        summary = monte_carlo_summary(simulations)
        if summary:
            cols = st.columns(4)
            cols[0].metric("Probabilidade de perda", fmt_pct(summary["probability_of_loss"]))
            cols[1].metric("Retorno P5", fmt_pct(summary["return_p05"]))
            cols[2].metric("Retorno mediano", fmt_pct(summary["return_median"]))
            cols[3].metric("Retorno P95", fmt_pct(summary["return_p95"]))

    # Table with every operation (all assets), most recent first.
    st.subheader("Todas as operações")
    cols_order = ["ticker", "signal_date", "rsi_at_signal", "signal_range",
                  "signal_body_percentile", "signal_atr_mult", "pattern", "entry_date",
                  "entry_price", "exit_date", "exit_price", "exit_reason", "bars_held",
                  "gross_return", "net_return", "pnl",
                  "mfe", "mfe_1w", "mfe_2w", "mfe_3w", "mfe_4w", "mfe_5w", "mfe_12w",
                  "option_status", "option_entry_date", "option_exit_date", "option_exit_reason",
                  "option_underlying_entry_price", "option_underlying_exit_price",
                  "option_strike", "option_expiration", "option_dte_entry", "option_dte_exit",
                  "option_contracts", "option_iv_entry", "option_iv_exit", "option_delta_entry",
                  "option_entry_price", "option_exit_price", "option_net_return", "option_pnl",
                  "option_commissions"]
    cols_order = [c for c in cols_order if c in trades.columns]
    raw = trades[cols_order].sort_values("entry_date").reset_index(drop=True)
    disp = raw.copy()
    for col in ["entry_price", "exit_price", "pnl"]:
        disp[col] = raw[col].map(fmt_money)
    disp["rsi_at_signal"] = raw["rsi_at_signal"].map(lambda v: fmt_num(v, 2))
    if "signal_range" in disp:
        disp["signal_range"] = raw["signal_range"].map(lambda v: fmt_num(v, 2))
    if "signal_body_percentile" in disp:
        disp["signal_body_percentile"] = raw["signal_body_percentile"].map(lambda v: fmt_num(v, 3))
    if "signal_atr_mult" in disp:
        disp["signal_atr_mult"] = raw["signal_atr_mult"].map(lambda v: fmt_num(v, 2))
    disp["gross_return"] = raw["gross_return"].map(fmt_pct)
    disp["net_return"] = raw["net_return"].map(fmt_pct)
    for mfe_col in ["mfe", "mfe_1w", "mfe_2w", "mfe_3w", "mfe_4w", "mfe_5w", "mfe_12w"]:
        if mfe_col in disp:
            disp[mfe_col] = raw[mfe_col].map(lambda v: fmt_pct(v) if pd.notna(v) else "—")
    for col in ["option_underlying_entry_price", "option_underlying_exit_price",
                "option_strike", "option_entry_price", "option_exit_price", "option_pnl",
                "option_commissions"]:
        if col in disp:
            disp[col] = raw[col].map(lambda v: fmt_money(v) if pd.notna(v) else "—")
    for col in ["option_iv_entry", "option_iv_exit", "option_net_return"]:
        if col in disp:
            disp[col] = raw[col].map(lambda v: fmt_pct(v) if pd.notna(v) else "—")
    st.dataframe(disp, use_container_width=True, hide_index=True)

    st.download_button("Baixar todas as operações (CSV)",
                       data=trades.sort_values("entry_date").to_csv(index=False).encode("utf-8"),
                       file_name="all_operations.csv", mime="text/csv", key="all_ops_csv")
