"""Painel independente para estudo das sete famílias de estratégias."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from fear_greed.analytics import analyze_portfolio, benchmark_curve
from fear_greed.catalog import BOOK_BENCHMARKS, RULE_DETAILS, STRATEGIES
from fear_greed.data import (
    NORGATE_ADJUSTMENTS,
    download_norgate,
    download_yahoo,
    norgate_collections,
    norgate_status,
    norgate_symbols,
    read_uploaded_csv,
)
from fear_greed.engine import StrategyConfig, run_backtest, screen_latest
from fear_greed.ibkr_paper import build_order_specs, fetch_paper_executions, stage_untransmitted_orders
from fear_greed.paper_ledger import append_event, append_signal_rows, ledger_frame, signal_event_key, verify_ledger
from fear_greed.portfolio import PortfolioConfig, run_portfolio


APP_ROOT = Path(__file__).resolve().parent
PAPER_LEDGER = APP_ROOT / "state" / "paper_ledger.jsonl"

st.set_page_config(page_title="Buy Fear, Sell Greed Lab", page_icon="📉", layout="wide")


@st.cache_data(ttl=3600, show_spinner=False)
def get_yahoo(tickers: tuple[str, ...], start: date, end: date):
    return download_yahoo(tickers, start, end)


@st.cache_data(ttl=3600, show_spinner=False)
def get_norgate(tickers: tuple[str, ...], start: date, end: date, adjustment: str, index_name: str | None):
    return download_norgate(tickers, start, end, adjustment, index_name)


@st.cache_data(ttl=300, show_spinner=False)
def get_norgate_collections(kind: str):
    return norgate_collections(kind)


@st.cache_data(ttl=300, show_spinner=False)
def get_norgate_symbols(kind: str, name: str):
    return norgate_symbols(kind, name)


def pct(value: float) -> str:
    return f"{value:.2f}%"


def ratio_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def money(value: float) -> str:
    return f"US$ {value:,.2f}"


def number(value: float) -> str:
    if value == float("inf"):
        return "∞"
    return f"{value:.2f}"


st.title("Buy Fear, Sell Greed — laboratório quantitativo")
st.caption("Implementação educacional independente das regras públicas estudadas. Não constitui recomendação de investimento.")

with st.sidebar:
    st.header("Dados")
    source = st.radio("Fonte", ["Yahoo Finance", "Norgate Data", "CSV"])
    raw_tickers = st.text_area("Tickers", "SPY, QQQ, IWM, EEM, EWZ, FXI, VXX")
    tickers = tuple(dict.fromkeys(t.strip().upper() for t in raw_tickers.split(",") if t.strip()))
    norgate_adjustment = "Total Return (splits + dividendos)"
    norgate_ready = False
    point_in_time_index = None
    collection = None
    if source == "Norgate Data":
        norgate_ready, norgate_message = norgate_status()
        (st.success if norgate_ready else st.error)(norgate_message)
        norgate_adjustment = st.selectbox("Ajuste Norgate", list(NORGATE_ADJUSTMENTS))
        universe_mode = st.radio("Universo Norgate", ["Tickers informados", "Watchlist", "Database"])
        if norgate_ready and universe_mode != "Tickers informados":
            collections = get_norgate_collections(universe_mode)
            collection = st.selectbox(universe_mode, collections, index=None, placeholder="Selecione uma coleção")
            maximum = st.number_input("Máximo de ativos", min_value=1, max_value=5000, value=250, step=25, help="Limita o carregamento de coleções grandes.")
            if collection:
                available_symbols = get_norgate_symbols(universe_mode, collection)
                tickers = tuple(available_symbols[:maximum])
                st.caption(f"{len(tickers)} de {len(available_symbols)} símbolos selecionados.")
                if universe_mode == "Watchlist":
                    use_membership = st.checkbox("Constituintes ponto no tempo", value="Current & Past" in collection, help="Impede entradas antes da inclusão ou depois da exclusão do índice.")
                    inferred_index = collection.replace(" Current & Past", "").replace(" Current and Past", "").strip()
                    if use_membership:
                        point_in_time_index = st.text_input("Índice Norgate", inferred_index, help="Nome aceito por index_constituent_timeseries, por exemplo S&P 500.")
    date_key = source.lower().replace(" ", "_")
    end = st.date_input("Fim", date.today(), key=f"end_{date_key}")
    default_start = date(1990, 1, 1) if source == "Norgate Data" else end - timedelta(days=365 * 12)
    start = st.date_input("Início", default_start, key=f"start_{date_key}")
    upload = st.file_uploader("CSV OHLCV", type="csv", disabled=source != "CSV")
    st.header("Execução")
    capital = st.number_input("Capital inicial", 1_000.0, 100_000_000.0, 100_000.0, step=10_000.0)
    commission_model = st.selectbox("Custos IBKR Pro", ["IBKR Pro Tiered", "IBKR Pro Fixed", "Sem comissão"])
    third_party_bps = st.number_input("Taxas de terceiros (bps)", 0.0, 20.0, 0.10, 0.05, help="Estimativa de venue, clearing e taxas regulatórias; o valor real depende da execução.", disabled=commission_model == "Sem comissão")
    st.caption("Tiered usa a primeira faixa mensal (US$ 0,0035/ação; mín. US$ 0,35). Fixed: US$ 0,005/ação; mín. US$ 1. Ambos têm teto de 1% da ordem.")
    slippage = st.number_input("Slippage (bps)", 0.0, 100.0, 3.0, 0.5)

try:
    norgate_warnings: list[str] = []
    if source == "Yahoo Finance":
        with st.spinner("Baixando e ajustando dados..."):
            datasets = get_yahoo(tickers, start, end)
    elif source == "Norgate Data" and norgate_ready:
        with st.spinner(f"Carregando {len(tickers)} série(s) do Norgate local..."):
            datasets, norgate_warnings = get_norgate(tickers, start, end, norgate_adjustment, point_in_time_index)
    elif upload:
        datasets = read_uploaded_csv(upload.getvalue())
    else:
        datasets = {}
except Exception as exc:
    st.error(f"Não foi possível carregar os dados: {exc}")
    datasets = {}

if source == "Norgate Data" and norgate_warnings:
    with st.expander(f"Avisos do Norgate ({len(norgate_warnings)})"):
        st.write("\n".join(f"- {warning}" for warning in norgate_warnings[:100]))

if datasets:
    st.sidebar.caption(f"{len(datasets)} série(s) carregada(s) · {source}")

tab_backtest, tab_scanner, tab_paper, tab_rules, tab_risk = st.tabs(["Backtest", "Scanner", "Ordens paper", "Regras", "Risco e método"])

with tab_backtest:
    strategy = st.selectbox("Estratégia", list(STRATEGIES), format_func=lambda x: STRATEGIES[x]["name"])
    c1, c2, c3, c4 = st.columns(4)
    entry = c1.number_input("Nível de entrada", value=float({"rsi_powerzones": 30, "crash": 90, "vol_panics": 70, "trading_new_highs": 15, "tps_long": 25, "tps_short": 75, "terror_gaps": 5}.get(strategy, 0)), disabled=strategy == "vxx_trend")
    exit_level = c2.number_input("Nível de saída", value=float({"rsi_powerzones": 55, "crash": 30, "vol_panics": 20, "trading_new_highs": 70, "tps_long": 70, "tps_short": 30, "terror_gaps": 70}.get(strategy, 0)), disabled=strategy == "vxx_trend")
    limit_default = {"crash": 3, "trading_new_highs": 7, "terror_gaps": 1}.get(strategy, 0)
    limit_pct = c3.number_input("Limite (%)", value=float(limit_default), disabled=not bool(limit_default), help="Distância percentual da ordem limitada. A referência depende da estratégia; consulte a aba Regras.")
    scale = c4.selectbox("Escala", ["1/2/3/4", "2/3/5", "1/1", "sem escala"], disabled=strategy not in {"rsi_powerzones", "vol_panics", "tps_long", "tps_short"}, help="Divide a posição-alvo em parcelas. 1/2/3/4 equivale a 10%/20%/30%/40%.")
    add = st.number_input("Segundo nível (PowerZones)", value=25.0, disabled=strategy != "rsi_powerzones")
    ma_type = st.radio("Tipo de média", ["SMA", "EMA"], horizontal=True, disabled=strategy != "vxx_trend")
    execution_model = st.radio("Execução dos sinais de fechamento", ["Próxima abertura", "Rompimento da barra de sinal"], horizontal=True, disabled=strategy in {"crash", "trading_new_highs", "terror_gaps"}, help="Abertura usa ordem a mercado em D+1. Rompimento usa stop-limit DAY na máxima de D (long) ou mínima de D (short); em gaps, exige retorno ao preço-limite.")
    close_at_end = st.checkbox("Liquidar posições abertas no fim do período", value=False, help="Desativado por padrão: evita criar uma saída artificial apenas porque a amostra terminou.")
    exclude = st.checkbox("Excluir 10/10/2008 e 24/08/2015", value=True, disabled=strategy != "terror_gaps", help="O livro retirou esses dias da tabela publicada porque concentravam mais de 30% dos sinais.")
    selected_tickers = st.multiselect("Ativos do teste", list(datasets), default=list(datasets)[:1])
    portfolio_mode = st.radio("Capital do backtest", ["Carteira única", "Ativos independentes"], horizontal=True, help="Carteira única faz todos os ativos disputarem o mesmo capital. Ativos independentes serve apenas para diagnóstico do sinal por ativo.")
    p1, p2, p3, p4 = st.columns(4)
    position_size = p1.number_input("Posição-alvo (% do patrimônio)", 0.1, 100.0, 10.0, 0.5, disabled=portfolio_mode != "Carteira única")
    leverage = p2.number_input("Alavancagem (x)", 0.10, 5.00, 1.00, 0.10, disabled=portfolio_mode != "Carteira única", help="Multiplica o notional de cada posição e o teto de exposição. Ex.: alvo 25%, teto 100% e 2x = posição de 50% e teto efetivo de 200%.")
    max_gross = p3.number_input("Exposição bruta máxima (%)", 1.0, 500.0, 100.0, 5.0, disabled=portfolio_mode != "Carteira única", help="Limite antes da alavancagem. O teto efetivo é este percentual multiplicado pela alavancagem.")
    max_positions = p4.number_input("Máximo de posições", 1, 500, 10, 1, disabled=portfolio_mode != "Carteira única")
    if portfolio_mode == "Carteira única":
        st.caption(f"Notional-alvo efetivo: {position_size * leverage:.1f}% por posição · exposição bruta efetiva máxima: {max_gross * leverage:.1f}%.")
        if leverage > 1:
            st.warning("A alavancagem amplia o notional e o P&L. Juros de financiamento, chamadas de margem e borrow de shorts ainda não são modelados.")
    benchmark_options = ["Nenhum"] + list(datasets)
    benchmark_default = benchmark_options.index("SPY") if "SPY" in benchmark_options else 0
    benchmark_ticker = st.selectbox("Benchmark", benchmark_options, index=benchmark_default, disabled=portfolio_mode != "Carteira única", help="Compra e manutenção do ativo escolhido, normalizada para o mesmo capital inicial. Serve como referência, não como réplica de risco da estratégia.")
    run = st.button("Executar backtest", type="primary", disabled=not selected_tickers)

    if run:
        config = StrategyConfig(strategy=strategy, initial_capital=capital, commission_model=commission_model, third_party_bps=third_party_bps if commission_model != "Sem comissão" else 0.0, slippage_bps=slippage, execution_model=execution_model, close_open_positions_at_end=close_at_end, entry_level=None if strategy == "vxx_trend" else entry, add_level=add if strategy == "rsi_powerzones" else None, exit_level=None if strategy == "vxx_trend" else exit_level, limit_pct=limit_pct if limit_default else None, scale_scheme=scale, ma_type=ma_type, exclude_terror_outliers=exclude)
        if portfolio_mode == "Carteira única":
            portfolio = run_portfolio(
                {ticker: datasets[ticker] for ticker in selected_tickers},
                config,
                PortfolioConfig(initial_capital=capital, position_size_pct=position_size, max_gross_pct=max_gross, max_positions=int(max_positions), leverage=leverage),
            )
            all_trades = portfolio.trades
            analytics = analyze_portfolio(portfolio.equity, all_trades, capital)
            metrics = analytics.metrics

            benchmark = pd.Series(dtype=float)
            benchmark_analytics = None
            if benchmark_ticker != "Nenhum":
                benchmark = benchmark_curve(datasets[benchmark_ticker], portfolio.equity.index, capital)
                valid_benchmark = benchmark.dropna()
                if not valid_benchmark.empty:
                    benchmark_equity = pd.DataFrame({"equity": valid_benchmark, "costs": 0.0, "open_positions": 1, "gross_exposure_pct": 100.0, "configured_leverage": 1.0})
                    benchmark_analytics = analyze_portfolio(benchmark_equity, pd.DataFrame(), capital)

            overview_tab, risk_tab, trades_tab, periods_tab, exposure_tab = st.tabs(["Visão geral", "Risco", "Operações", "Meses e anos", "Exposição e auditoria"])

            with overview_tab:
                row1 = st.columns(5)
                row1[0].metric("Capital inicial", money(metrics["initial_capital"]))
                row1[1].metric("Patrimônio final", money(metrics["final_equity"]))
                row1[2].metric("Lucro líquido", money(metrics["net_profit"]))
                row1[3].metric("Retorno total", ratio_pct(metrics["total_return"]))
                row1[4].metric("CAGR", ratio_pct(metrics["cagr"]))
                row2 = st.columns(5)
                row2[0].metric("Drawdown máximo", ratio_pct(metrics["max_drawdown"]))
                row2[1].metric("Volatilidade anual", ratio_pct(metrics["annual_volatility"]))
                row2[2].metric("Sharpe (rf=0)", number(metrics["sharpe_0rf"]))
                row2[3].metric("Sortino (rf=0)", number(metrics["sortino_0rf"]))
                row2[4].metric("Tempo no mercado", ratio_pct(metrics["time_in_market"]))

                equity_figure = go.Figure()
                equity_figure.add_trace(go.Scatter(x=analytics.daily.index, y=analytics.daily.equity, name="Estratégia", mode="lines"))
                if not benchmark.empty:
                    equity_figure.add_trace(go.Scatter(x=benchmark.index, y=benchmark, name=f"Buy & hold {benchmark_ticker}", mode="lines", line={"dash": "dot"}))
                equity_figure.update_layout(title="Patrimônio diário marcado a mercado", yaxis_title="USD", hovermode="x unified", legend_title=None)
                st.plotly_chart(equity_figure, width="stretch")

                if benchmark_analytics is not None:
                    benchmark_metrics = benchmark_analytics.metrics
                    strategy_days = int((analytics.daily.get("open_positions", pd.Series(0, index=analytics.daily.index)) > 0).sum())
                    benchmark_days = int((benchmark_analytics.daily.get("open_positions", pd.Series(0, index=benchmark_analytics.daily.index)) > 0).sum())
                    total_days = len(analytics.daily)

                    def comparison_row(group: str, label: str, key: str, formatter=ratio_pct) -> dict[str, str]:
                        strategy_value = metrics[key]
                        benchmark_value = benchmark_metrics[key]
                        return {
                            "Grupo": group,
                            "Métrica": label,
                            "Estratégia": formatter(strategy_value),
                            f"Buy & hold {benchmark_ticker}": formatter(benchmark_value),
                            "Diferença": formatter(strategy_value - benchmark_value),
                        }

                    def integer(value: float) -> str:
                        return f"{int(round(value)):,}"

                    comparison = pd.DataFrame([
                        {
                            "Grupo": "Amostra",
                            "Métrica": "Período analisado",
                            "Estratégia": f"{analytics.daily.index[0]:%d/%m/%Y} a {analytics.daily.index[-1]:%d/%m/%Y}",
                            f"Buy & hold {benchmark_ticker}": f"{benchmark_analytics.daily.index[0]:%d/%m/%Y} a {benchmark_analytics.daily.index[-1]:%d/%m/%Y}",
                            "Diferença": "—",
                        },
                        comparison_row("Amostra", "Sessões analisadas", "sessions", integer),
                        comparison_row("Amostra", "Anos de histórico", "years", number),
                        comparison_row("Resultado", "Patrimônio final", "final_equity", money),
                        comparison_row("Resultado", "Lucro líquido", "net_profit", money),
                        comparison_row("Resultado", "Retorno total", "total_return"),
                        comparison_row("Resultado", "CAGR", "cagr"),
                        comparison_row("Eficiência", "CAGR / tempo posicionado", "cagr_per_time_in_market"),
                        comparison_row("Eficiência", "CAGR / exposição bruta média", "cagr_per_avg_exposure"),
                        comparison_row("Eficiência", "Retorno total / drawdown máximo", "return_over_max_drawdown", number),
                        comparison_row("Risco", "Volatilidade anual", "annual_volatility"),
                        comparison_row("Risco", "Desvio negativo anual", "annual_downside_deviation"),
                        comparison_row("Risco", "Drawdown máximo", "max_drawdown"),
                        comparison_row("Risco", "Maior período em drawdown (sessões)", "longest_drawdown_bars", integer),
                        comparison_row("Risco", "Sharpe (rf=0)", "sharpe_0rf", number),
                        comparison_row("Risco", "Sortino (rf=0)", "sortino_0rf", number),
                        comparison_row("Risco", "Calmar", "calmar", number),
                        comparison_row("Risco", "Ulcer Index", "ulcer_index"),
                        comparison_row("Risco", "VaR diário histórico 95%", "daily_var_95"),
                        comparison_row("Risco", "CVaR diário histórico 95%", "daily_cvar_95"),
                        comparison_row("Consistência", "Retorno diário médio", "avg_daily_return"),
                        comparison_row("Consistência", "Sessões positivas", "positive_days"),
                        comparison_row("Consistência", "Melhor sessão", "best_day"),
                        comparison_row("Consistência", "Pior sessão", "worst_day"),
                        comparison_row("Consistência", "Meses positivos", "positive_months"),
                        comparison_row("Consistência", "Melhor mês", "best_month"),
                        comparison_row("Consistência", "Pior mês", "worst_month"),
                        {
                            "Grupo": "Uso de capital",
                            "Métrica": "Dias posicionados",
                            "Estratégia": f"{strategy_days:,} de {total_days:,}",
                            f"Buy & hold {benchmark_ticker}": f"{benchmark_days:,} de {len(benchmark_analytics.daily):,}",
                            "Diferença": f"{strategy_days - benchmark_days:+,} dias",
                        },
                        comparison_row("Uso de capital", "Tempo posicionado", "time_in_market"),
                        comparison_row("Uso de capital", "Alavancagem configurada", "configured_leverage", number),
                        comparison_row("Uso de capital", "Exposição bruta média", "avg_gross_exposure"),
                        comparison_row("Uso de capital", "Exposição bruta máxima", "max_gross_exposure"),
                        comparison_row("Uso de capital", "Giro anual do capital", "annual_turnover", number),
                        comparison_row("Uso de capital", "Posições simultâneas médias", "avg_positions", number),
                        comparison_row("Uso de capital", "Máximo de posições simultâneas", "max_positions", number),
                    ])
                    st.markdown(f"**Comparação com buy & hold de {benchmark_ticker}**")
                    st.caption(
                        "Diferença = Estratégia − Buy & Hold. O buy-and-hold permanece posicionado e com "
                        "100% de exposição durante todo o período; a estratégia mantém caixa nos dias sem posições. "
                        "CAGR / tempo posicionado = CAGR ÷ percentual de sessões posicionadas; é uma medida de "
                        "eficiência temporal, não uma projeção de retorno composto realizável."
                    )
                    st.dataframe(comparison, width="stretch", height="content", hide_index=True)

            with risk_tab:
                risk1 = st.columns(5)
                risk1[0].metric("Calmar", number(metrics["calmar"]))
                risk1[1].metric("Ulcer Index", ratio_pct(metrics["ulcer_index"]))
                risk1[2].metric("VaR diário 95%", ratio_pct(metrics["daily_var_95"]))
                risk1[3].metric("CVaR diário 95%", ratio_pct(metrics["daily_cvar_95"]))
                risk1[4].metric("Pior mês", ratio_pct(metrics["worst_month"]))
                risk2 = st.columns(4)
                risk2[0].metric("Melhor mês", ratio_pct(metrics["best_month"]))
                risk2[1].metric("Meses positivos", ratio_pct(metrics["positive_months"]))
                risk2[2].metric("Maior exposição bruta", ratio_pct(metrics["max_gross_exposure"]))
                risk2[3].metric("Exposição bruta média", ratio_pct(metrics["avg_gross_exposure"]))

                left, right = st.columns(2)
                drawdown_figure = go.Figure(go.Scatter(x=analytics.daily.index, y=analytics.daily.drawdown * 100, fill="tozeroy", line={"color": "#dc2626"}, name="Drawdown"))
                drawdown_figure.update_layout(title="Curva underwater", yaxis_title="Drawdown (%)", hovermode="x unified")
                left.plotly_chart(drawdown_figure, width="stretch")
                returns_figure = px.histogram(analytics.daily.iloc[1:].reset_index(), x="daily_return", nbins=60, title="Distribuição dos retornos diários")
                returns_figure.update_xaxes(tickformat=".2%", title="Retorno diário")
                right.plotly_chart(returns_figure, width="stretch")
                if not analytics.drawdown_episodes.empty:
                    episodes = analytics.drawdown_episodes.copy()
                    episodes["drawdown_pct"] = episodes.drawdown * 100
                    st.markdown("**Principais episódios de drawdown**")
                    st.dataframe(episodes[["inicio", "fundo", "recuperacao", "drawdown_pct", "duracao_barras", "em_aberto"]].head(15), width="stretch", hide_index=True)

            with trades_tab:
                trade1 = st.columns(6)
                trade1[0].metric("Operações encerradas", int(metrics["trades"]))
                trade1[1].metric("Taxa de acerto", ratio_pct(metrics["win_rate"]))
                trade1[2].metric("Retorno médio", ratio_pct(metrics["avg_trade"]))
                trade1[3].metric("Mediana", ratio_pct(metrics["median_trade"]))
                trade1[4].metric("Profit factor", number(metrics["profit_factor"]))
                trade1[5].metric("Expectativa", money(metrics["expectancy_usd"]))
                trade2 = st.columns(6)
                trade2[0].metric("Ganho médio", ratio_pct(metrics["avg_win"]))
                trade2[1].metric("Perda média", ratio_pct(metrics["avg_loss"]))
                trade2[2].metric("Payoff", number(metrics["payoff_ratio"]))
                trade2[3].metric("Melhor operação", ratio_pct(metrics["best_trade"]))
                trade2[4].metric("Pior operação", ratio_pct(metrics["worst_trade"]))
                trade2[5].metric("Duração média", f"{metrics['avg_bars']:.1f} barras")
                trade3 = st.columns(4)
                trade3[0].metric("Maior sequência vencedora", int(metrics["max_win_streak"]))
                trade3[1].metric("Maior sequência perdedora", int(metrics["max_loss_streak"]))
                trade3[2].metric("Custos totais", money(metrics["costs"]))
                trade3[3].metric("Custos / capital inicial", ratio_pct(metrics["cost_drag"]))

                if all_trades.empty:
                    st.info("Nenhuma operação foi encerrada; posições abertas já aparecem na curva e no risco diário.")
                else:
                    trade_view = all_trades.copy()
                    trade_view["retorno_pct"] = trade_view.net_return * 100
                    charts_left, charts_right = st.columns(2)
                    distribution = px.histogram(trade_view, x="retorno_pct", nbins=40, color="direction", title="Distribuição dos retornos por operação")
                    distribution.update_xaxes(title="Retorno líquido (%)")
                    charts_left.plotly_chart(distribution, width="stretch")
                    scatter = px.scatter(trade_view, x="bars_held", y="retorno_pct", color="ticker", size=trade_view.pnl.abs().clip(lower=1), hover_data=["entry_date", "exit_date", "tranches"], title="Retorno × duração")
                    scatter.update_xaxes(title="Barras na posição")
                    scatter.update_yaxes(title="Retorno líquido (%)")
                    charts_right.plotly_chart(scatter, width="stretch")

                    pnl_time = trade_view.sort_values("exit_date").copy()
                    pnl_time["pnl_acumulado"] = pnl_time.pnl.cumsum()
                    st.plotly_chart(px.line(pnl_time, x="exit_date", y="pnl_acumulado", title="P&L realizado acumulado por data de saída"), width="stretch")
                    if not analytics.by_ticker.empty:
                        by_ticker_chart = px.bar(analytics.by_ticker, x="ticker", y="pnl", color="pnl", title="Contribuição de P&L por ativo", color_continuous_scale="RdYlGn")
                        st.plotly_chart(by_ticker_chart, width="stretch")
                        st.markdown("**Resumo por ativo**")
                        st.dataframe(analytics.by_ticker, width="stretch", hide_index=True)
                    st.markdown("**Livro de operações**")
                    st.dataframe(trade_view.sort_values("exit_date", ascending=False), width="stretch", hide_index=True)
                    st.download_button("Baixar operações da carteira", all_trades.to_csv(index=False).encode("utf-8"), "operacoes_carteira.csv", "text/csv")

            with periods_tab:
                if analytics.monthly_heatmap.empty:
                    st.info("Histórico insuficiente para retornos mensais.")
                else:
                    month_names = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]
                    heat = analytics.monthly_heatmap.reindex(columns=range(1, 13)) * 100
                    heatmap_figure = go.Figure(go.Heatmap(z=heat.values, x=month_names, y=heat.index.astype(str), text=heat.round(1).values, texttemplate="%{text}", colorscale="RdYlGn", zmid=0, colorbar={"title": "%"}, hovertemplate="Ano %{y}<br>%{x}: %{z:.2f}%<extra></extra>"))
                    heatmap_figure.update_layout(title="Mapa de retornos mensais")
                    st.plotly_chart(heatmap_figure, width="stretch")
                if not analytics.yearly.empty:
                    annual = analytics.yearly.reset_index()
                    annual["retorno_pct"] = annual.retorno * 100
                    annual["drawdown_pct"] = annual.drawdown_max * 100
                    annual_figure = go.Figure()
                    annual_figure.add_trace(go.Bar(x=annual.ano, y=annual.retorno_pct, name="Retorno", marker_color=["#16a34a" if value >= 0 else "#dc2626" for value in annual.retorno_pct]))
                    annual_figure.add_trace(go.Scatter(x=annual.ano, y=annual.drawdown_pct, name="Drawdown", mode="lines+markers", yaxis="y2"))
                    annual_figure.update_layout(title="Retorno e drawdown por ano", yaxis={"title": "Retorno (%)"}, yaxis2={"title": "Drawdown (%)", "overlaying": "y", "side": "right"}, hovermode="x unified")
                    st.plotly_chart(annual_figure, width="stretch")
                    st.dataframe(analytics.yearly, width="stretch")
                rolling = analytics.daily[["rolling_12m_return", "rolling_12m_volatility", "rolling_12m_sharpe"]].dropna(how="all")
                if not rolling.empty:
                    rolling_figure = make_subplots(specs=[[{"secondary_y": True}]])
                    rolling_figure.add_trace(go.Scatter(x=rolling.index, y=rolling.rolling_12m_return * 100, name="Retorno 12m (%)"), secondary_y=False)
                    rolling_figure.add_trace(go.Scatter(x=rolling.index, y=rolling.rolling_12m_volatility * 100, name="Volatilidade 12m (%)", line={"dash": "dot"}), secondary_y=False)
                    rolling_figure.add_trace(go.Scatter(x=rolling.index, y=rolling.rolling_12m_sharpe, name="Sharpe 12m", line={"color": "#7c3aed"}), secondary_y=True)
                    rolling_figure.update_layout(title="Métricas móveis de 252 sessões", hovermode="x unified")
                    rolling_figure.update_yaxes(title_text="Retorno / volatilidade (%)", secondary_y=False)
                    rolling_figure.update_yaxes(title_text="Sharpe", secondary_y=True)
                    st.plotly_chart(rolling_figure, width="stretch")

            with exposure_tab:
                exposure_figure = make_subplots(specs=[[{"secondary_y": True}]])
                exposure_figure.add_trace(go.Scatter(x=analytics.daily.index, y=analytics.daily.gross_exposure_pct, name="Exposição real (%)"), secondary_y=False)
                exposure_figure.add_trace(go.Scatter(x=analytics.daily.index, y=analytics.daily.reserved_exposure_pct, name="Exposição reservada (%)", line={"dash": "dot"}), secondary_y=False)
                exposure_figure.add_trace(go.Bar(x=analytics.daily.index, y=analytics.daily.open_positions, name="Posições abertas", opacity=0.25), secondary_y=True)
                exposure_figure.update_layout(title="Exposição e quantidade de posições", hovermode="x unified")
                exposure_figure.update_yaxes(title_text="Exposição (%)", secondary_y=False)
                exposure_figure.update_yaxes(title_text="Posições", secondary_y=True)
                st.plotly_chart(exposure_figure, width="stretch")
                operations1 = st.columns(5)
                operations1[0].metric("Exposição média", ratio_pct(metrics["avg_gross_exposure"]))
                operations1[1].metric("Exposição máxima", ratio_pct(metrics["max_gross_exposure"]))
                operations1[2].metric("Posições médias", number(metrics["avg_positions"]))
                operations1[3].metric("Máximo simultâneo", int(metrics["max_positions"]))
                operations1[4].metric("Turnover anual", f"{metrics['annual_turnover']:.2f}×")
                st.caption("O tamanho usa o patrimônio do fechamento anterior. A posição-alvo inteira é reservada na primeira parcela; saídas liberam espaço antes dos novos sinais. A exposição real pode exceder o teto por oscilação do mercado, sem liquidação artificial.")
                if portfolio.decisions.empty:
                    st.info("Nenhuma decisão de entrada ou scale-in foi gerada.")
                else:
                    decision_summary = portfolio.decisions.groupby(["decision", "reason"], dropna=False).size().rename("quantidade").reset_index().sort_values("quantidade", ascending=False)
                    total_candidates = int((portfolio.decisions.decision.isin(["executado", "rejeitado"])).sum())
                    rejected = int((portfolio.decisions.decision == "rejeitado").sum())
                    unfilled = int((portfolio.decisions.decision == "não executado").sum())
                    decision_cols = st.columns(3)
                    decision_cols[0].metric("Decisões de alocação", total_candidates)
                    decision_cols[1].metric("Rejeitadas por carteira", rejected)
                    decision_cols[2].metric("Ordens sem fill", unfilled)
                    st.markdown("**Resumo das decisões**")
                    st.dataframe(decision_summary, width="stretch", hide_index=True)
                    st.markdown("**Auditoria completa da disputa entre sinais**")
                    st.dataframe(portfolio.decisions, width="stretch", hide_index=True)
                    st.download_button("Baixar decisões", portfolio.decisions.to_csv(index=False).encode("utf-8"), "decisoes_carteira.csv", "text/csv")
                st.download_button("Baixar marcação diária", analytics.daily.to_csv().encode("utf-8"), "marcacao_diaria.csv", "text/csv")
        else:
            results = [run_backtest(datasets[t], t, config) for t in selected_tickers]
            all_trades = pd.concat([r.trades for r in results], ignore_index=True) if results else pd.DataFrame()
            if all_trades.empty:
                st.warning("Nenhuma operação foi encontrada com esses dados e parâmetros.")
            else:
                returns = all_trades.net_return
                m1, m2, m3, m4, m5, m6 = st.columns(6)
                m1.metric("Operações", len(all_trades))
                m2.metric("Acerto", pct((returns > 0).mean() * 100))
                m3.metric("Retorno médio", pct(returns.mean() * 100))
                m4.metric("Duração média", f"{all_trades.bars_held.mean():.1f} barras")
                m5.metric("Retorno mediano", pct(returns.median() * 100))
                m6.metric("Custos IBKR", f"US$ {all_trades.commission.sum():,.2f}")
                curves = pd.concat([r.equity.assign(ticker=r.ticker).reset_index(names="data") for r in results])
                st.plotly_chart(px.line(curves, x="data", y="equity", color="ticker", title="Curva de capital por ativo"), width="stretch")
                per_asset = pd.DataFrame([{"ticker": r.ticker, **r.metrics} for r in results])
                st.markdown("**Métricas independentes por ativo**")
                st.dataframe(per_asset, width="stretch", hide_index=True)
                diag_left, diag_right = st.columns(2)
                asset_return_chart = px.bar(per_asset, x="ticker", y="total_return", color="total_return", color_continuous_scale="RdYlGn", title="Retorno total independente por ativo (%)")
                diag_left.plotly_chart(asset_return_chart, width="stretch")
                diagnostic_trades = all_trades.copy()
                diagnostic_trades["retorno_pct"] = diagnostic_trades.net_return * 100
                diag_right.plotly_chart(px.box(diagnostic_trades, x="ticker", y="retorno_pct", points="outliers", title="Distribuição das operações por ativo"), width="stretch")
                st.plotly_chart(px.scatter(diagnostic_trades, x="bars_held", y="retorno_pct", color="ticker", hover_data=["entry_date", "exit_date", "commission"], title="Retorno × duração — diagnóstico independente"), width="stretch")
                st.dataframe(all_trades.sort_values("exit_date", ascending=False), width="stretch", hide_index=True)
                st.download_button("Baixar operações em CSV", all_trades.to_csv(index=False).encode("utf-8"), "operacoes.csv", "text/csv")
                st.info("Modo diagnóstico: os ativos não compartilham capital e seus retornos não formam uma carteira.")

with tab_scanner:
    st.subheader("Sinais na barra mais recente")
    choices = st.multiselect("Estratégias do scanner", list(STRATEGIES), default=list(STRATEGIES), format_func=lambda x: STRATEGIES[x]["name"])
    configs = [StrategyConfig(strategy=s, execution_model=execution_model, slippage_bps=slippage, scale_scheme=scale) for s in choices]
    rows = [row for ticker, frame in datasets.items() for row in screen_latest(frame, ticker, configs)]
    scan = pd.DataFrame(rows)
    if scan.empty:
        st.info("Nenhum gatilho recente nos dados carregados.")
    else:
        scan = scan.sort_values(["forca_sinal", "ticker"], ascending=[False, True], na_position="last").reset_index(drop=True)
        st.dataframe(scan, width="stretch", hide_index=True)
        long_count = int((scan.direcao == "long").sum())
        if long_count >= 3:
            st.warning(f"Risco de correlação: {long_count} sinais long simultâneos. Limite a exposição agregada e evite ETFs equivalentes.")
        st.download_button("Baixar scanner", scan.to_csv(index=False).encode("utf-8"), "scanner.csv", "text/csv")

with tab_paper:
    st.subheader("Ordens candidatas para IBKR Paper")
    st.write("O ledger registra sinais, ordens e fills sem reescrever o passado. Ordens podem ser colocadas no TWS Paper, mas permanecem não transmitidas para confirmação manual.")
    ledger_status = verify_ledger(PAPER_LEDGER)
    if ledger_status.valid:
        st.success(f"Ledger íntegro · {ledger_status.records} evento(s) · hash {ledger_status.last_hash[:12] if ledger_status.last_hash else 'inicial'}")
    else:
        st.error(f"Ledger bloqueado: {ledger_status.error}")
    if scan.empty:
        st.info("O scanner não encontrou ordens candidatas na última barra.")
    else:
        paper_columns = ["data_sinal", "ticker", "estrategia", "direcao", "tipo_ordem", "preco_stop", "preco_limite", "validade", "parcela_inicial", "forca_sinal", "acao"]
        paper = scan[[column for column in paper_columns if column in scan]].copy()
        paper["transmitir"] = False
        st.dataframe(paper, width="stretch", hide_index=True)
        st.download_button("Baixar candidatos IBKR Paper", paper.to_csv(index=False).encode("utf-8"), "ibkr_paper_candidates.csv", "text/csv")
        if st.button("Registrar sinais no ledger", disabled=not ledger_status.valid):
            added, duplicates = append_signal_rows(PAPER_LEDGER, paper.to_dict("records"))
            st.success(f"{added} sinal(is) acrescentado(s); {duplicates} duplicado(s) ignorado(s).")

        allocation = st.number_input("Posição-alvo por ativo (USD)", 1.0, 100_000_000.0, float(capital * position_size / 100), 100.0, help="A quantidade da primeira ordem respeita a parcela inicial da escala. A posição-alvo completa deve permanecer reservada.")
        all_specs = build_order_specs(paper.to_dict("records"), allocation)
        exposure_slots = int(max_gross // position_size) if position_size > 0 else 0
        batch_limit = max(0, min(int(max_positions), exposure_slots))
        specs = all_specs[:batch_limit]
        if len(all_specs) > len(specs):
            st.warning(f"{len(all_specs) - len(specs)} ordem(ns) ficou(aram) fora do lote pelo limite de posições/exposição. Exposição já existente na conta deve ser descontada manualmente.")
        if specs:
            st.markdown("**Ordens preparadas (`transmit=False`)**")
            st.dataframe(pd.DataFrame([vars(spec) if hasattr(spec, "__dict__") else {field: getattr(spec, field) for field in spec.__dataclass_fields__} for spec in specs]), width="stretch", hide_index=True)
        if any(paper.tipo_ordem.str.startswith("COND")):
            st.info("Terror Gaps depende da abertura futura e não é enviado antecipadamente; o ledger mantém o sinal para acompanhamento.")

        with st.expander("Conectar ao TWS / IB Gateway Paper"):
            host = st.text_input("Host", "127.0.0.1")
            ib1, ib2 = st.columns(2)
            port = ib1.number_input("Porta Paper", 1, 65535, 7497, 1, help="Padrão TWS Paper: 7497. Confira sua configuração local.")
            client_id = ib2.number_input("Client ID", 0, 9999, 71, 1)
            confirmation = st.checkbox("Confirmo que o TWS/IB Gateway está conectado à conta PAPER e revisarei cada ordem antes de transmiti-la.")
            if st.button("Colocar no TWS sem transmitir", disabled=not confirmation or not specs or not ledger_status.valid):
                try:
                    append_signal_rows(PAPER_LEDGER, paper.to_dict("records"))
                    staged = stage_untransmitted_orders(specs, host=host, port=int(port), client_id=int(client_id))
                    for order in staged:
                        key = f"order_staged:{order['client_id']}:{order['ibkr_order_id']}"
                        append_event(PAPER_LEDGER, "order_staged", order, event_key=key)
                    st.success(f"{len(staged)} ordem(ns) colocada(s) no TWS com transmit=False. Confirme manualmente no TWS.")
                except Exception as exc:
                    st.error(f"Não foi possível preparar as ordens no TWS: {exc}")
            if st.button("Sincronizar fills confirmados da IBKR", disabled=not confirmation or not ledger_status.valid):
                try:
                    executions = fetch_paper_executions(host=host, port=int(port), client_id=int(client_id))
                    added = duplicates = 0
                    for execution in executions:
                        _, created = append_event(PAPER_LEDGER, "fill", execution, event_key=f"fill:{execution['execution_id']}")
                        added += int(created)
                        duplicates += int(not created)
                    st.success(f"{added} fill(s) acrescentado(s); {duplicates} já registrado(s).")
                except Exception as exc:
                    st.error(f"Não foi possível consultar os fills: {exc}")
            st.caption("Ordens não transmitidas pertencem à sessão local do TWS e podem desaparecer quando ela reiniciar. O ledger preserva o registro da preparação, mas não representa confirmação da corretora.")

    with st.expander("Registrar fill confirmado manualmente"):
        with st.form("manual_fill"):
            f1, f2, f3, f4 = st.columns(4)
            fill_ticker = f1.text_input("Ticker")
            fill_side = f2.selectbox("Lado", ["BUY", "SELL"])
            fill_qty = f3.number_input("Quantidade", 1, 100_000_000, 1, 1)
            fill_price = f4.number_input("Preço", 0.0001, 10_000_000.0, 1.0, 0.01)
            fill_commission = st.number_input("Comissão efetiva", 0.0, 1_000_000.0, 0.0, 0.01)
            execution_id = st.text_input("Execution ID da IBKR", help="Usado como chave única para impedir o mesmo fill duas vezes.")
            submit_fill = st.form_submit_button("Acrescentar fill ao ledger", disabled=not ledger_status.valid)
        if submit_fill:
            if not fill_ticker.strip() or not execution_id.strip():
                st.error("Ticker e Execution ID são obrigatórios.")
            else:
                _, created = append_event(PAPER_LEDGER, "fill", {"ticker": fill_ticker.strip().upper(), "side": fill_side, "quantity": int(fill_qty), "price": float(fill_price), "commission": float(fill_commission), "execution_id": execution_id.strip()}, event_key=f"fill:{execution_id.strip()}")
                (st.success if created else st.info)("Fill acrescentado ao ledger." if created else "Esse Execution ID já estava registrado; nada foi alterado.")

    history = ledger_frame(PAPER_LEDGER) if ledger_status.valid else pd.DataFrame()
    if not history.empty:
        with st.expander("Histórico imutável do paper", expanded=True):
            st.dataframe(history.sort_values("recorded_at_utc", ascending=False), width="stretch", hide_index=True)
            st.download_button("Baixar ledger JSONL", PAPER_LEDGER.read_bytes(), "paper_ledger.jsonl", "application/x-ndjson")
    st.warning("Short availability, borrow fee e margem continuam temporariamente fora do modelo, conforme solicitado.")

with tab_rules:
    with st.expander("Como interpretar Limite (%) e Escala", expanded=True):
        st.markdown("""
        ### Limite (%)

        É a distância entre o preço de referência e a ordem que poderá executar a entrada. **Não é stop-loss nem limite de perda.** O campo só fica habilitado nas estratégias cuja entrada ocorre por ordem limitada:

        - **CRASH:** a referência é o fechamento do dia do setup. Limite de 3% significa tentar abrir o short no pregão seguinte a `fechamento × 1,03`. Exemplo: fechamento de US$ 100 → venda limitada a US$ 103. Só executa se a máxima alcançar US$ 103.
        - **Trading New Highs:** a referência também é o fechamento do setup. Limite de 7% significa comprar no pregão seguinte a `fechamento × 0,93`. Exemplo: fechamento de US$ 100 → compra limitada a US$ 93. Só executa se a mínima tocar US$ 93.
        - **Terror Gaps:** a referência é a abertura da sessão que apresentou o gap. Limite de 1% significa comprar a `abertura × 0,99`. Exemplo: abertura de US$ 90 → compra limitada a US$ 89,10.

        Quando o campo aparece em **0 e desabilitado**, a estratégia não usa esse parâmetro: a entrada é feita no fechamento da barra do sinal.

        ### Escala

        A escala divide a posição total planejada em parcelas. Os números são **proporções**, normalizadas para 100% da posição-alvo:

        | Seleção | Parcelas da posição-alvo | Exemplo para posição-alvo de US$ 10.000 |
        |---|---:|---:|
        | `1/2/3/4` | 10% + 20% + 30% + 40% | US$ 1.000 + 2.000 + 3.000 + 4.000 |
        | `2/3/5` | 20% + 30% + 50% | US$ 2.000 + 3.000 + 5.000 |
        | `1/1` | 50% + 50% | US$ 5.000 + 5.000 |
        | `sem escala` | 100% na primeira entrada | US$ 10.000 |

        As parcelas posteriores **não entram automaticamente no mesmo dia**. No TPS Long e RSI PowerZones, acrescenta-se somente quando uma barra posterior satisfaz as condições e oferece preço inferior à parcela anterior. No TPS Short e Vol Panics, acrescenta-se somente a preço superior. Se o mercado reverter antes, a posição pode sair parcialmente montada.

        A escala controla o ritmo de entrada, mas não limita a perda máxima. Comissão IBKR é cobrada separadamente em cada parcela executada e novamente na saída.

        ### Execução dos sinais de fechamento

        O indicador é confirmado apenas depois do fechamento de **D**, portanto nenhuma operação usa retroativamente o fechamento de D:

        - **Próxima abertura:** envia-se uma ordem a mercado para a abertura de D+1. O backtest usa a abertura de D+1 ajustada pelo slippage.
        - **Rompimento da barra de sinal:** para uma entrada long, o gatilho é a máxima de D; para uma entrada short, a mínima de D. Se D+1 cruzar o gatilho durante a sessão, o preenchimento aproximado é o gatilho mais o slippage. No long, se `abertura[D+1] > máxima[D]`, a entrada só é registrada quando `mínima[D+1] < máxima[D]`; caso contrário, o preço não recuou até a ordem. No short, a regra é espelhada: se `abertura[D+1] < mínima[D]`, exige-se `máxima[D+1] > mínima[D]`. Sem rompimento ou retorno exigido, a ordem DAY expira.

        O gatilho é de **stop**, mas a regra de não executar imediatamente num gap exige, na prática, uma **stop-limit**: na IBKR, configure o *stop price* na máxima/mínima de D e o *limit price* no preço de entrada com slippage tolerado, usando validade DAY. Uma stop-market comum seria acionada e executada na abertura do gap. Com OHLC diário não conhecemos a sequência intradiária; por isso o teste adota a convenção conservadora de exigir o retorno ao limite antes de registrar o fill.
        """)
    for key, item in STRATEGIES.items():
        with st.expander(f"{item['name']} · {item['direction']} · {item['assets']}"):
            details = RULE_DETAILS[key]
            st.markdown(f"**Ideia comportamental**  \n{details['logic']}")
            st.markdown(f"**Universo e dados**  \n{details['universe']}")
            left, right = st.columns(2)
            with left:
                st.markdown("**Condições do setup**")
                for rule in details["setup"]:
                    st.markdown(f"- {rule}")
                st.markdown(f"**Entrada**  \n{details['entry']}")
            with right:
                st.markdown("**Gestão da posição**")
                for rule in details["management"]:
                    st.markdown(f"- {rule}")
                st.markdown(f"**Saída**  \n{details['exit']}")
            st.warning(f"Riscos específicos: {details['risks']}")
    st.markdown("### Referências numéricas do estudo original")
    st.dataframe(pd.DataFrame(BOOK_BENCHMARKS).T, width="stretch")
    st.caption("Servem para conferência conceitual, não como promessa nem como teste de igualdade: universos, dados, ajustes, custos e datas podem divergir.")

with tab_risk:
    st.markdown("""
    ### O que o backtest não resolve

    - Stops não eliminam risco de gap. Uma ordem pode executar muito além do nível pretendido.
    - ETFs de volatilidade mudam, sofrem splits e carregam efeitos estruturais; use séries ajustadas e confirme a metodologia.
    - Em pânico, estratégias e ativos aparentemente distintos tornam-se correlacionados. Controle a exposição agregada por mercado e setor.
    - Short exige disponibilidade de aluguel e pode sofrer recall, squeeze e custo variável. Esses itens não estão simulados.
    - Sinais confirmados no fechamento só geram execução em D+1. Slippage e o preenchimento intradiário inferido de OHLC são aproximações.
    - O custo IBKR Pro Tiered usa a primeira faixa de volume mensal. Taxas de terceiros variam por venue, lado e liquidez; o campo em bps é uma aproximação conservadora.
    - Escolher parâmetros depois de olhar os resultados cria sobreajuste. Congele as regras antes do backtest; qualquer alteração posterior passa a ser uma nova hipótese para acompanhamento prospectivo.

    O apêndice do estudo sugere estruturas de opções de risco definido. Elas podem limitar a perda contratual, mas adicionam risco de liquidez, volatilidade implícita, exercício, vencimento e seleção de strikes; não estão modeladas neste aplicativo.

    ### Protocolo de validação adotado

    O aplicativo não treina modelos e não divide a série em treinamento/validação/teste. As regras são fixadas antes da execução, aplicadas uma única vez ao período histórico escolhido e depois encaminhadas para observação prospectiva em paper trading. Alterar parâmetros após ver o resultado cria uma nova hipótese e exige um novo período prospectivo.
    """)

if not datasets:
    st.sidebar.warning("Carregue dados para habilitar o laboratório.")
