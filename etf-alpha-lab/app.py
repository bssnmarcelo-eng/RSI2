from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from etf_alpha.backtest import run_backtest  # noqa: E402
from etf_alpha.candidates import CANDIDATES, STRATEGY_CATALOG, get_candidate  # noqa: E402
from etf_alpha.config import UNIVERSE_GROUPS, CostConfig, LabConfig  # noqa: E402
from etf_alpha.data import (  # noqa: E402
    configure_norgate_root,
    load_leading_indicators,
    load_norgate,
    merge_macro_sources,
    norgate_status,
    validate_etfs,
)
from etf_alpha.external_macro import load_external_macro  # noqa: E402
from etf_alpha.orders import target_orders  # noqa: E402

configure_norgate_root(ROOT / ".norgate")

st.set_page_config(page_title="ETF Alpha Lab", page_icon="◒", layout="wide")
st.title("ETF Alpha Lab")
st.caption("Pesquisa causal, ETF-only, sem alavancagem · Norgate local · execução IBKR paper")


@st.cache_data(show_spinner=False, ttl=3600)
def fetch(symbols: tuple[str, ...], start: str, end: str | None):
    frames, price_errors = load_norgate(symbols, start, end)
    norgate_macro, norgate_errors = load_leading_indicators(start, end)
    external_macro, external_errors = load_external_macro(start, end)
    indicators = merge_macro_sources(norgate_macro, external_macro)
    return frames, price_errors, indicators, {**norgate_errors, **external_errors}


def correlation_cell_style(value: float) -> str:
    if pd.isna(value):
        return ""
    intensity = min(abs(float(value)), 1.0)
    color = "34, 197, 94" if value >= 0 else "239, 68, 68"
    return f"background-color: rgba({color}, {0.08 + 0.30 * intensity:.3f})"


with st.sidebar:
    st.header("Experimento")
    status = norgate_status()
    if status:
        st.success("Norgate conectado")
    else:
        st.error("Abra o Norgate Data Updater")
    defaults = LabConfig()
    candidate_key = st.selectbox(
        "Portfólio-candidato",
        options=list(CANDIDATES),
        format_func=lambda key: CANDIDATES[key].name,
        index=list(CANDIDATES).index(defaults.candidate),
    )
    candidate_preview = get_candidate(candidate_key)
    st.caption(candidate_preview.objective)
    with st.expander("Mandato e pesos do candidato"):
        st.write(candidate_preview.expected_tradeoff)
        st.dataframe(
            pd.Series(candidate_preview.weights, name="peso").to_frame().style.format("{:.0%}"),
            use_container_width=True,
        )
    with st.expander(f"Universo diversificado · {len(defaults.symbols)} ETFs"):
        for group, symbols in UNIVERSE_GROUPS.items():
            st.markdown(f"**{group}** · {len(symbols)}")
            st.caption(", ".join(symbols))
    symbols_text = st.text_area(
        "ETFs (símbolos Norgate)",
        ", ".join(defaults.symbols),
        height=220,
        help="Curadoria baseada na taxonomia do ETFdb; edite livremente. Produtos alavancados e inversos foram excluídos.",
        key="universe_symbols_v2",
    )
    start = st.date_input("Início", pd.Timestamp(defaults.start_date)).isoformat()
    end_enabled = st.checkbox("Fixar data final", value=False)
    end = st.date_input("Fim", pd.Timestamp.today()).isoformat() if end_enabled else None
    capital = st.number_input("Capital inicial (USD)", 10_000.0, 100_000_000.0, defaults.initial_capital)
    st.subheader("Risco")
    target_vol = st.slider("Volatilidade alvo (só reduz exposição)", 0.08, 0.30, defaults.risk.target_volatility, 0.01)
    max_symbol = st.slider("Máximo por ETF", 0.10, 1.00, defaults.risk.max_symbol_weight, 0.05)
    st.subheader("Custos IBKR Pro")
    pricing = st.selectbox("Plano", ["Tiered", "Fixed"])
    slippage = st.number_input("Slippage (bps/lado)", 0.0, 25.0, defaults.costs.slippage_bps, 0.5)
    borrow = st.number_input("Borrow short anual", 0.0, 0.50, defaults.costs.short_borrow_rate, 0.005)
    excess_hurdle = st.number_input(
        "Excesso CAGR mínimo sobre SPY",
        0.0,
        0.10,
        0.02,
        0.005,
        help="Critério para considerar a superação significativa; padrão de 2 pontos percentuais ao ano.",
    )
    run = st.button("Executar backtest", type="primary", use_container_width=True)

if run:
    requested = tuple(item.strip().upper() for item in symbols_text.replace("\n", ",").split(",") if item.strip())
    with st.spinner("Validando ETFs na Norgate…"):
        valid, rejected = validate_etfs(requested)
    if rejected:
        st.warning("Símbolos rejeitados (não são ETFs): " + ", ".join(f"{key} [{value}]" for key, value in rejected.items()))
    if defaults.benchmark not in valid:
        st.error("SPY precisa estar no universo para servir de benchmark.")
        st.stop()
    costs = CostConfig(
        pricing=pricing.lower(),
        commission_per_share=0.0035 if pricing == "Tiered" else 0.005,
        minimum_per_order=0.35 if pricing == "Tiered" else 1.0,
        slippage_bps=slippage,
        short_borrow_rate=borrow,
    )
    risk = replace(defaults.risk, target_volatility=target_vol, max_symbol_weight=max_symbol)
    config = replace(
        defaults,
        symbols=tuple(valid),
        start_date=start,
        end_date=end,
        initial_capital=capital,
        candidate=candidate_key,
        costs=costs,
        risk=risk,
    )
    with st.spinner("Carregando preços e simulando no próximo open…"):
        frames, errors, indicators, indicator_errors = fetch(config.symbols, config.start_date, config.end_date)
        result = run_backtest(frames, config, indicators)
    st.session_state["result"] = result
    st.session_state["frames"] = frames
    st.session_state["config"] = config
    st.session_state["errors"] = errors
    st.session_state["indicator_errors"] = indicator_errors

result = st.session_state.get("result")
if result is not None and not hasattr(result, "candidate_comparison"):
    for key in ("result", "frames", "config", "errors", "indicator_errors", "orders"):
        st.session_state.pop(key, None)
    result = None
if result is None:
    st.info("Configure o experimento e execute o primeiro backtest. Nenhum resultado fictício é mostrado.")
    st.stop()

config = st.session_state["config"]
selected_candidate = get_candidate(config.candidate)
errors = st.session_state.get("errors", {})
if errors:
    st.warning(f"{len(errors)} série(s) ignorada(s): " + ", ".join(errors))
indicator_errors = st.session_state.get("indicator_errors", {})
if indicator_errors:
    st.warning("Indicadores antecedentes indisponíveis: " + ", ".join(indicator_errors))

strategy = result.metrics
benchmark = result.benchmark_metrics
cols = st.columns(6)
for column, label, value, delta in (
    (cols[0], "CAGR líquido", strategy["cagr"], strategy["cagr"] - benchmark["cagr"]),
    (cols[1], "Drawdown máximo", strategy["max_drawdown"], strategy["max_drawdown"] - benchmark["max_drawdown"]),
    (cols[2], "Sharpe (rf=0)", strategy["sharpe_0rf"], strategy["sharpe_0rf"] - benchmark["sharpe_0rf"]),
    (cols[3], "Volatilidade anual", strategy["annual_volatility"], strategy["annual_volatility"] - benchmark["annual_volatility"]),
    (cols[4], "Custo total", result.costs.sum() / config.initial_capital, None),
    (cols[5], "Exposição bruta atual", result.executed_weights.iloc[-1].abs().sum(), None),
):
    column.metric(label, f"{value:.2%}" if label not in {"Sharpe (rf=0)"} else f"{value:.2f}", None if delta is None else f"{delta:+.2%}")

goal_met = (
    strategy["cagr"] >= benchmark["cagr"] + excess_hurdle
    and strategy["annual_volatility"] < benchmark["annual_volatility"]
    and strategy["max_drawdown"] > benchmark["max_drawdown"]
)
if goal_met:
    st.success("O candidato venceu os três critérios no recorte: excesso de retorno, volatilidade menor e drawdown menor. Ainda requer walk-forward e paper trading.")
else:
    st.warning("O candidato não venceu simultaneamente excesso de retorno, volatilidade e drawdown. O sistema não promove este resultado para execução.")

tab_curve, tab_candidates, tab_sleeves, tab_positions, tab_validation, tab_orders = st.tabs(
    ["Patrimônio", "Candidatos", "Estratégias", "Posições", "Validação", "Ordens IBKR"]
)
with tab_curve:
    chart = go.Figure()
    chart.add_trace(go.Scatter(x=result.equity.index, y=result.equity, name="ETF Alpha líquido"))
    chart.add_trace(go.Scatter(x=result.benchmark.index, y=result.benchmark, name="SPY buy & hold"))
    chart.update_layout(height=480, yaxis_title="USD", hovermode="x unified")
    st.plotly_chart(chart, use_container_width=True)
with tab_candidates:
    st.subheader("Comparação líquida dos candidatos")
    comparison = result.candidate_comparison.copy()
    comparison["excess_cagr"] = comparison["cagr"] - benchmark["cagr"]
    comparison["meets_return_hurdle"] = comparison["excess_cagr"] >= excess_hurdle
    comparison["passes_all"] = (
        comparison["meets_return_hurdle"]
        & comparison["lower_vol_than_spy"]
        & comparison["lower_drawdown_than_spy"]
    )
    comparison_view = comparison.set_index("candidate")[[
        "cagr", "excess_cagr", "annual_volatility", "max_drawdown", "sharpe_0rf",
        "annual_turnover", "costs_usd", "passes_all",
    ]].sort_values("cagr", ascending=False)
    st.dataframe(
        comparison_view.style.format({
            "cagr": "{:.2%}", "excess_cagr": "{:+.2%}", "annual_volatility": "{:.2%}",
            "max_drawdown": "{:.2%}", "sharpe_0rf": "{:.2f}",
            "annual_turnover": "{:.1f}x", "costs_usd": "${:,.0f}",
        }),
        use_container_width=True,
    )
    risk_return = go.Figure()
    for _, row in comparison.reset_index().iterrows():
        risk_return.add_trace(go.Scatter(
            x=[row["annual_volatility"]], y=[row["cagr"]], mode="markers+text",
            text=[row["candidate"]], textposition="top center", name=row["candidate"],
            marker={"size": 13},
            hovertemplate=(
                "%{text}<br>CAGR %{y:.2%}<br>Vol %{x:.2%}"
                f"<br>DD {row['max_drawdown']:.2%}<extra></extra>"
            ),
        ))
    risk_return.add_trace(go.Scatter(
        x=[benchmark["annual_volatility"]], y=[benchmark["cagr"]], mode="markers+text",
        text=["SPY"], textposition="top center", name="SPY",
        marker={"size": 16, "symbol": "diamond", "color": "black"},
    ))
    risk_return.update_layout(height=440, xaxis_title="Volatilidade anual", yaxis_title="CAGR")
    risk_return.update_xaxes(tickformat=".0%")
    risk_return.update_yaxes(tickformat=".0%")
    st.plotly_chart(risk_return, use_container_width=True)

    st.subheader(f"{selected_candidate.name}: o que executa")
    st.write(selected_candidate.objective)
    st.caption(selected_candidate.expected_tradeoff)
    detail_rows = []
    for name, weight in selected_candidate.weights.items():
        definition = STRATEGY_CATALOG[name]
        detail_rows.append({
            "Estratégia": name, "Peso": weight, "Objetivo": definition.objective,
            "Universo": definition.universe, "Sinal": definition.signal,
            "Regime": definition.regime, "Frequência": definition.frequency,
            "Compra": definition.long_rule, "Short": definition.short_rule,
            "Saída": definition.exit_rule, "Papel": definition.portfolio_role,
        })
    st.dataframe(
        pd.DataFrame(detail_rows).set_index("Estratégia").style.format({"Peso": "{:.0%}"}),
        use_container_width=True,
        height=390,
    )
    st.subheader("Mapa de pesos: todos os candidatos")
    weight_map = pd.DataFrame({profile.name: profile.weights for profile in CANDIDATES.values()}).fillna(0.0)
    st.dataframe(weight_map.style.format("{:.0%}"), use_container_width=True)
with tab_sleeves:
    st.subheader("Resultados individuais líquidos")
    sleeve_columns = ["cagr", "annual_volatility", "max_drawdown", "sharpe_0rf", "annual_turnover", "rebalance_days", "short_days"]
    sleeve_table = result.strategy_metrics[sleeve_columns].copy()
    st.dataframe(
        sleeve_table.style.format(
            {
                "cagr": "{:.2%}",
                "annual_volatility": "{:.2%}",
                "max_drawdown": "{:.2%}",
                "sharpe_0rf": "{:.2f}",
                "annual_turnover": "{:.1f}x",
                "rebalance_days": "{:.0f}",
                "short_days": "{:.0f}",
            }
        ),
        use_container_width=True,
    )
    sleeve_chart = go.Figure()
    for name in result.strategy_equity:
        sleeve_chart.add_trace(go.Scatter(x=result.strategy_equity.index, y=result.strategy_equity[name], name=name))
    sleeve_chart.update_layout(height=460, yaxis_title="USD", hovermode="x unified")
    st.plotly_chart(sleeve_chart, use_container_width=True)
    st.subheader("Correlação das estratégias")
    correlation = result.strategy_returns.corr()
    correlation_style = correlation.style.format("{:.2f}").map(correlation_cell_style)
    st.dataframe(correlation_style, use_container_width=True)
    st.subheader("Pesos fixos e transparentes do candidato")
    st.dataframe(result.strategy_budgets.tail(1).T.rename(columns={result.strategy_budgets.index[-1]: "peso"}).style.format("{:.0%}"), use_container_width=True)
    st.subheader("Regime de mercado")
    st.caption("FRED: juros reais, curva 10Y–2Y, M2 e spreads. Norgate: ISM Manufacturing PMI e demais séries licenciadas. Services PMI só entra quando houver feed automático autorizado.")
    regime_view = result.regime[["score", "risk_on", "risk_off"]].tail(252)
    regime_chart = go.Figure(go.Scatter(x=regime_view.index, y=regime_view["score"], name="Score de regime"))
    regime_chart.add_hline(y=0.60, line_dash="dash", line_color="green")
    regime_chart.add_hline(y=0.40, line_dash="dash", line_color="red")
    regime_chart.update_layout(height=320, yaxis_range=[0, 1])
    st.plotly_chart(regime_chart, use_container_width=True)
with tab_positions:
    current = result.executed_weights.iloc[-1].sort_values()
    position_chart = go.Figure(go.Bar(x=current.index, y=current.values))
    position_chart.update_layout(height=420, xaxis_title="ETF", yaxis_title="Peso")
    st.plotly_chart(position_chart, use_container_width=True)
    st.dataframe(current.rename("peso").to_frame().style.format("{:.2%}"), use_container_width=True)
with tab_validation:
    score = result.scorecard
    if score.empty:
        st.info("O histórico ainda não cobre uma janela móvel de três anos.")
    else:
        both = (score["return_win"] & score["drawdown_win"]).mean()
        st.metric("Janelas móveis de 3 anos vencendo nos dois critérios", f"{both:.1%}")
        st.dataframe(score.tail(24), use_container_width=True)
    st.caption("Próxima etapa de pesquisa: split temporal congelado e walk-forward; não selecione parâmetros pelo período completo.")
with tab_orders:
    st.warning("A geração abaixo é para revisão. Envio live está deliberadamente bloqueado; use primeiro uma conta paper.")
    net_liq = st.number_input("Net liquidation IBKR (USD)", 1_000.0, 1_000_000_000.0, config.initial_capital)
    positions_text = st.text_area("Posições atuais (SYMBOL=SHARES, uma por linha)", "")
    if st.button("Gerar ordens"):
        positions: dict[str, float] = {}
        try:
            for line in positions_text.splitlines():
                if line.strip():
                    symbol, quantity = line.split("=", 1)
                    positions[symbol.strip().upper()] = float(quantity)
            latest_prices = pd.Series({symbol: frame["close"].iloc[-1] for symbol, frame in st.session_state["frames"].items()})
            orders = target_orders(positions, result.target_weights.iloc[-1], latest_prices, net_liq)
            st.session_state["orders"] = orders
        except Exception as exc:
            st.error(f"Não foi possível gerar ordens: {exc}")
    if "orders" in st.session_state:
        orders = st.session_state["orders"]
        st.dataframe(orders, use_container_width=True)
        st.download_button("Baixar CSV para revisão", orders.to_csv(index=False), "ibkr_orders.csv", "text/csv")
