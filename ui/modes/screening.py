"""Market screening mode (scan a Norgate watchlist/database for live entry signals)."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd
import streamlit as st

from src import charts, norgate_loader, screener
from src.backtest_engine import BacktestEngine
from src.options.yahoo_diagonal import DiagonalProposal, fetch_yahoo_diagonals
from src.performance_metrics import compute_metrics
from src.utils import fmt_money, fmt_num, fmt_pct
from ui.data_source import (
    _ng_database_symbols,
    _ng_databases,
    _ng_watchlist_symbols,
    _ng_watchlists,
)
from ui.params_form import configuration_form
from ui.render import render_trade_log


@st.cache_data(ttl=300, show_spinner=False)
def _cached_yahoo_diagonal(
    ticker: str,
    mfe_20d: float,
    mfe_60d: float,
    capital: float,
    risk_pct: float,
    min_reward_risk: float,
    commission_per_contract: float,
) -> tuple[DiagonalProposal, DiagonalProposal]:
    return fetch_yahoo_diagonals(
        ticker,
        mfe_20d=mfe_20d,
        mfe_60d=mfe_60d,
        capital=capital,
        risk_pct=risk_pct,
        min_reward_risk=min_reward_risk,
        commission_per_contract=commission_per_contract,
    )


def _historical_mfe(trades: pd.DataFrame, column: str) -> float | None:
    if trades.empty or column not in trades:
        return None
    values = pd.to_numeric(trades[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def _render_yahoo_diagonal(ticker: str, result, cfg) -> None:
    st.subheader(f"Estrutura com opções — {ticker}")
    st.caption(
        "Duas alternativas de call diagonal (2:1 e 1:1): compra ATM com aproximadamente 60 pregões e venda "
        "no alvo do MFE20 com aproximadamente 20 pregões. Somente vencimentos mensais "
        "e preços médios de bid/ask. Fonte das cotações: Yahoo Finance."
    )
    mfe_20d = _historical_mfe(result.trades, "mfe_4w")
    mfe_60d = _historical_mfe(result.trades, "mfe_12w")
    if mfe_20d is None or mfe_60d is None:
        st.warning("Não há operações históricas suficientes para calcular MFE20 e MFE60.")
        return

    controls = st.columns(4)
    capital = controls[0].number_input(
        "Patrimônio (USD)", min_value=1.0, value=float(cfg.initial_capital), step=1_000.0,
        key=f"screen_option_capital_{ticker}",
    )
    risk_pct = controls[1].number_input(
        "Risco máximo (%)", min_value=0.1, max_value=100.0, value=6.0, step=0.5,
        key=f"screen_option_risk_{ticker}",
    )
    min_rr = controls[2].number_input(
        "Reward/Risk mínimo", min_value=0.0, value=3.0, step=0.25,
        key=f"screen_option_rr_{ticker}",
    )
    commission = controls[3].number_input(
        "Comissão/contrato (USD)", min_value=0.0, value=0.65, step=0.05,
        key=f"screen_option_commission_{ticker}",
    )

    try:
        with st.spinner(f"Buscando cadeia de opções de {ticker} no Yahoo Finance…"):
            proposals = _cached_yahoo_diagonal(
                ticker,
                mfe_20d,
                mfe_60d,
                float(capital),
                float(risk_pct),
                float(min_rr),
                float(commission),
            )
    except Exception as exc:
        st.warning(f"Não foi possível montar a estrutura com dados do Yahoo Finance: {exc}")
        return

    comparison = pd.DataFrame([
        {
            "Estrutura": f"Ratio {item.longs_per_short}:1",
            "Comprar": item.long_quantity,
            "Vender": item.short_quantity,
            "Débito total": fmt_money(item.total_debit),
            f"Alvo para {item.min_reward_risk:.2f}×": fmt_money(item.required_target),
            "Alta necessária": fmt_pct(item.required_move),
            "Alvo MFE60": fmt_money(item.target_60d),
            "Lucro no alvo": fmt_money(item.target_profit),
            "Reward/Risk": f"{item.reward_risk:.2f}×",
            "Status": "Aprovada" if item.qualifies else "Rejeitada",
        }
        for item in proposals
    ])
    st.markdown("##### Comparação das estruturas")
    st.dataframe(comparison, use_container_width=True, hide_index=True)
    selected_ratio = st.radio(
        "Detalhar estrutura",
        ["Ratio 2:1", "Ratio 1:1"],
        horizontal=True,
        key=f"screen_option_ratio_{ticker}",
    )
    proposal = proposals[0] if selected_ratio == "Ratio 2:1" else proposals[1]

    def _leg_row(action: str, quantity: int, expiration, dte: int, quote: dict) -> dict:
        execution = quote["mid"]
        cash_flow = quantity * execution * 100 * (1 if action == "Comprar" else -1)
        last_trade = quote.get("lastTradeDate")
        return {
            "Ação": action,
            "Quantidade": quantity,
            "Vencimento": pd.Timestamp(expiration).strftime("%d/%m/%Y"),
            "DTE úteis": dte,
            "Strike": fmt_money(quote["strike"]),
            "Bid": fmt_money(quote["bid"]),
            "Ask": fmt_money(quote["ask"]),
            "Preço médio": fmt_money(execution),
            "Open interest": (
                int(quote["openInterest"])
                if pd.notna(quote.get("openInterest"))
                else "—"
            ),
            "IV": (
                fmt_pct(quote["impliedVolatility"])
                if pd.notna(quote.get("impliedVolatility"))
                else "—"
            ),
            "Último negócio": (
                pd.Timestamp(last_trade).strftime("%d/%m/%Y %H:%M")
                if pd.notna(last_trade)
                else "—"
            ),
            "Custo / crédito": fmt_money(cash_flow),
            "Contrato": quote.get("contractSymbol", "—"),
        }

    legs = pd.DataFrame([
        _leg_row(
            "Comprar", proposal.long_quantity, proposal.long_expiration,
            proposal.long_dte_business, proposal.long_call,
        ),
        _leg_row(
            "Vender", proposal.short_quantity, proposal.short_expiration,
            proposal.short_dte_business, proposal.short_call,
        ),
    ])
    st.dataframe(legs, use_container_width=True, hide_index=True)

    first = st.columns(6)
    first[0].metric("Preço atual", fmt_money(proposal.spot))
    first[1].metric("MFE20 médio", fmt_pct(proposal.mfe_20d))
    first[2].metric("Strike-alvo venda", fmt_money(proposal.short_target))
    first[3].metric("MFE60 médio", fmt_pct(proposal.mfe_60d))
    first[4].metric("Alvo da estrutura", fmt_money(proposal.target_60d))
    first[5].metric(
        f"Alvo para {proposal.min_reward_risk:.2f}×",
        fmt_money(proposal.required_target),
        f"{proposal.required_move * 100:.2f}%",
    )
    second = st.columns(5)
    second[0].metric(f"Pacotes {proposal.longs_per_short}:1", f"{proposal.packages}")
    second[1].metric("Orçamento de risco", fmt_money(proposal.risk_budget))
    second[2].metric("Débito total", fmt_money(proposal.total_debit))
    second[3].metric("Lucro no alvo", fmt_money(proposal.target_profit))
    second[4].metric("Reward/Risk", f"{proposal.reward_risk:.2f}×")

    long_expiry = proposal.long_expiration.strftime("%d/%m/%Y")
    short_expiry = proposal.short_expiration.strftime("%d/%m/%Y")
    calculation = "\n".join([
        f"Assumindo um patrimônio de {fmt_money(capital)}:",
        "",
        f'P = "Posição Ratio {proposal.longs_per_short}:1"',
        "",
        (
            f"P1: Comprar {proposal.long_quantity}x Calls {long_expiry} "
            f"Strike {fmt_money(proposal.long_call['strike'])} @ preço médio "
            f"{fmt_money(proposal.long_call['mid'])} = {fmt_money(proposal.long_cost)}"
        ),
        (
            f"P2: Vender {proposal.short_quantity}x Calls {short_expiry} "
            f"Strike {fmt_money(proposal.short_call['strike'])} @ preço médio "
            f"{fmt_money(proposal.short_call['mid'])} = -{fmt_money(proposal.short_credit)}"
        ),
        f"Comissões de entrada = {fmt_money(proposal.entry_commissions)}",
        f"Custo total = {fmt_money(proposal.total_debit)}",
        "",
        (
            f"Alvo para RR {proposal.min_reward_risk:.2f}× = "
            f"{fmt_money(proposal.long_call['strike'])} + "
            f"({fmt_money(proposal.debit_per_package)} × "
            f"({proposal.min_reward_risk:.2f} + 1)) / "
            f"({proposal.longs_per_short} × 100) = "
            f"{fmt_money(proposal.required_target)} "
            f"({proposal.required_move * 100:.2f}% acima do preço atual)"
        ),
        "",
        (
            f"Cenário-alvo: ativo < {fmt_money(proposal.short_call['strike'])} até "
            f"{short_expiry}; {fmt_money(proposal.target_60d)} até {long_expiry}."
        ),
        "",
        (
            f"P1: Lucro = (max({fmt_money(proposal.target_60d)} - "
            f"{fmt_money(proposal.long_call['strike'])}, 0) - "
            f"{fmt_money(proposal.long_call['mid'])}) × {proposal.long_quantity} × 100 "
            f"= {fmt_money(proposal.long_target_profit)}"
        ),
        (
            f"P2: Lucro = ({fmt_money(proposal.short_call['strike'])} - "
            f"{fmt_money(proposal.short_call['strike'])} + "
            f"{fmt_money(proposal.short_call['mid'])}) × {proposal.short_quantity} × 100 "
            f"= {fmt_money(proposal.short_target_profit)}"
        ),
        f"Comissões = -{fmt_money(proposal.entry_commissions)}",
        f"Lucro total = {fmt_money(proposal.target_profit)}",
        (
            f"Reward/Risk = {fmt_money(proposal.target_profit)} / "
            f"{fmt_money(proposal.total_debit)} = {proposal.reward_risk:.2f}× "
            f"({proposal.reward_risk * 100:.0f}%)"
        ),
    ])
    st.markdown("##### Memória de cálculo")
    st.code(calculation, language="text")

    if proposal.qualifies:
        st.success(
            f"Estrutura Ratio {proposal.longs_per_short}:1 aprovada: "
            f"Reward/Risk de {proposal.reward_risk:.2f}× "
            f"é igual ou superior ao mínimo de {proposal.min_reward_risk:.2f}×."
        )
    elif proposal.packages == 0:
        st.warning(
            f"Estrutura Ratio {proposal.longs_per_short}:1 rejeitada: "
            "o orçamento não comporta um pacote."
        )
    else:
        st.warning(
            f"Estrutura rejeitada: Reward/Risk de {proposal.reward_risk:.2f}× abaixo "
            f"do mínimo de {proposal.min_reward_risk:.2f}×."
        )
    quote_label = (
        proposal.quote_time.tz_convert("America/Sao_Paulo").strftime("%d/%m/%Y %H:%M %Z")
        if proposal.quote_time is not None and proposal.quote_time.tzinfo is not None
        else "horário não informado"
    )
    st.caption(
        f"Cotação Yahoo: {quote_label}. O lucro projetado pressupõe a call curta expirando "
        "sem valor e a call longa valendo seu intrínseco no alvo; créditos de rolagens futuras "
        "não estão incluídos. Dados Yahoo/yfinance podem ser atrasados e são para pesquisa."
    )


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
    st.header("Screening de mercado")
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
    ma1, ma2 = st.columns(2)
    sma_price_label = ma1.selectbox(
        "Preço em relação à MM200",
        list(screener.SMA_PRICE_FILTERS),
        help="Compara o fechamento da barra avaliada com a média móvel simples de 200 barras do mesmo timeframe.",
    )
    sma_slope_label = ma2.selectbox(
        "Inclinação da MM200",
        list(screener.SMA_SLOPE_FILTERS),
        help="Ascendente quando a MM200 atual é maior que a MM200 da barra anterior; descendente quando é menor.",
    )
    sma_price_filter = screener.SMA_PRICE_FILTERS[sma_price_label]
    sma_slope_filter = screener.SMA_SLOPE_FILTERS[sma_slope_label]
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
                  + (f" · price ≤ {cfg.max_price:g}" if cfg.max_price > 0 else ""))
               + (f" · {sma_price_label}" if sma_price_filter != "any" else "")
               + (f" · {sma_slope_label}" if sma_slope_filter != "any" else ""))

    tickers = symbols if max_tickers == 0 else symbols[:int(max_tickers)]
    context = (
        tuple(tickers), timeframe, adjustment, bool(ignore_last), repr(cfg),
        sma_price_filter, sma_slope_filter,
    )
    if st.button("Executar screening", type="primary"):
        st.caption(f"Scanning **{len(tickers)}** tickers on **{timeframe}**…")
        bar = st.progress(0.0, text="Baixando dados do Norgate & screening…")
        try:
            hits, scanned, errors = screener.run_screen_norgate(
                tickers, timeframe, cfg, adjustment_label=adjustment, ignore_last=ignore_last,
                sma_price_filter=sma_price_filter, sma_slope_filter=sma_slope_filter,
                progress=lambda p: bar.progress(
                    min(p, 1.0), text="Baixando dados do Norgate & screening…"
                ),
            )
        except ImportError:
            bar.empty()
            st.error("Pacote `norgatedata` não instalado. `pip install norgatedata`.")
            return
        except Exception as exc:
            bar.empty()
            st.error(f"Falha no screening: {exc}")
            return
        bar.empty()
        asset_details = {}
        history_errors = []
        if not hits.empty:
            history_bar = st.progress(
                0.0, text="Calculando histórico dos ativos encontrados…"
            )
            hits, asset_details, history_errors = screener.add_historical_trade_stats(
                hits,
                timeframe,
                cfg,
                adjustment_label=adjustment,
                progress=lambda p: history_bar.progress(
                    min(p, 1.0), text="Calculando histórico dos ativos encontrados…"
                ),
            )
            history_bar.empty()
        st.session_state["_screening_result"] = {
            "context": context,
            "hits": hits,
            "scanned": scanned,
            "errors": errors,
            "asset_details": asset_details,
            "history_errors": history_errors,
        }
    else:
        saved = st.session_state.get("_screening_result")
        if not saved or saved.get("context") != context:
            return
        hits = saved["hits"]
        scanned = saved["scanned"]
        errors = saved["errors"]
        asset_details = saved.get("asset_details", {})
        history_errors = saved.get("history_errors", [])

    st.success(f"**{len(hits)}** hit(s) out of **{scanned}** scanned "
               f"({errors} ticker(s) had no/insufficient data).")
    if hits.empty:
        st.info("No tickers currently satisfy the entry conditions.")
        return
    if history_errors:
        st.warning(
            f"Não foi possível calcular o histórico de {len(history_errors)} ativo(s): "
            + "; ".join(history_errors)
        )

    disp = hits.copy()
    disp["date"] = pd.to_datetime(disp["date"]).dt.strftime("%Y-%m-%d")
    disp["close"] = hits["close"].map(fmt_money)
    disp["rsi"] = hits["rsi"].map(lambda v: fmt_num(v, 2))
    disp["body_percentile"] = hits["body_percentile"].map(lambda v: fmt_num(v, 3))
    disp["range"] = hits["range"].map(lambda v: fmt_num(v, 2))
    disp["atr_multiple"] = hits["atr_multiple"].map(lambda v: fmt_num(v, 3))
    disp["atr_period"] = hits["atr_period"].astype(int)
    disp["sma_200"] = hits["sma_200"].map(
        lambda value: fmt_money(value) if pd.notna(value) else "—"
    )
    disp["distance_sma_200"] = hits["distance_sma_200"].map(
        lambda value: fmt_pct(value) if pd.notna(value) else "—"
    )
    disp["sma_200_slope"] = hits["sma_200_slope"].map(
        lambda value: fmt_pct(value) if pd.notna(value) else "—"
    )
    disp["price_vs_sma_200"] = hits["price_vs_sma_200"].map({
        "above": "Acima",
        "below": "Abaixo",
        "equal_or_unavailable": "Igual/indisponível",
    })
    disp["trade_count"] = hits["trade_count"].map(
        lambda value: int(value) if pd.notna(value) else "—"
    )
    disp["win_rate"] = hits["win_rate"].map(
        lambda value: fmt_pct(value) if pd.notna(value) else "—"
    )
    disp["avg_gain"] = hits["avg_gain"].map(
        lambda value: fmt_pct(value) if pd.notna(value) else "—"
    )
    disp["avg_loss"] = hits["avg_loss"].map(
        lambda value: fmt_pct(value) if pd.notna(value) else "—"
    )
    disp["mfe_12w"] = hits["mfe_12w"].map(
        lambda value: fmt_pct(value) if pd.notna(value) else "—"
    )
    disp = disp.rename(columns={
        "atr_multiple": "ATR Multiple",
        "atr_period": "ATR Period",
        "trade_count": "Operações",
        "win_rate": "Taxa de acerto",
        "avg_gain": "Ganho médio",
        "avg_loss": "Perda média",
        "mfe_12w": "MFE médio 60d / 12sem",
        "sma_200": "MM200",
        "distance_sma_200": "Distância da MM200",
        "sma_200_slope": "Inclinação da MM200",
        "price_vs_sma_200": "Posição vs. MM200",
    })
    st.caption("Clique em uma linha para abrir o gráfico semanal do ativo, inicialmente em 1 ano.")
    event = st.dataframe(
        disp,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="screening_hits_table",
    )
    st.download_button("Baixar sinais encontrados (CSV)",
                       data=hits.to_csv(index=False).encode("utf-8"),
                       file_name=f"screening_{timeframe}.csv",
                       mime="text/csv", key="screen_csv")
    st.caption(f"MFE médio 60d / 12sem = máxima alta média alcançada nas 12 semanas "
               f"após cada entrada, independentemente da saída. Sorted by RSI "
               f"(most oversold first). 'date' is the evaluated candle. "
               f"'body_percentile' = (high − body bottom) ÷ range — always ≤ your percentile "
               f"setting ({cfg.patterns.hammer.percentile:g}); lower = body closer to the high "
               f"(stronger hammer).")

    selected_rows = (
        event.selection.rows
        if event and hasattr(event, "selection") and event.selection.rows
        else []
    )
    if selected_rows:
        ticker = str(hits.iloc[selected_rows[0]]["ticker"])
        st.subheader(f"{ticker} — Semanal com RSI({cfg.rsi_period})")
        detail_key = (ticker, timeframe, adjustment, repr(cfg))
        table_detail = asset_details.get(ticker)
        cached_detail = st.session_state.get("_screening_asset_detail")
        if table_detail is not None:
            result, chart_warnings = table_detail
        elif cached_detail and cached_detail.get("key") == detail_key:
            result = cached_detail["result"]
            chart_warnings = cached_detail["warnings"]
        else:
            try:
                with st.spinner(f"Carregando histórico e testando {ticker}…"):
                    chart_data, chart_warnings = screener.fetch_screen_chart(
                        ticker,
                        timeframe,
                        cfg,
                        adjustment_label=adjustment,
                    )
                    if chart_data.empty:
                        st.warning(f"O Norgate não retornou histórico para {ticker}.")
                        return
                    result = BacktestEngine(
                        chart_data, replace(cfg, ticker=ticker)
                    ).run()
                    st.session_state["_screening_asset_detail"] = {
                        "key": detail_key,
                        "result": result,
                        "warnings": chart_warnings,
                    }
            except Exception as exc:
                st.error(f"Não foi possível testar {ticker}: {exc}")
                return
        for warning in chart_warnings:
            st.warning(warning)
        for warning in result.warnings:
            st.warning(warning)
        weekly_chart_data = result.data if timeframe == "Weekly" else pd.DataFrame()
        if timeframe != "Weekly":
            weekly_key = (ticker, adjustment, repr(cfg))
            cached_weekly = st.session_state.get("_screening_weekly_chart")
            if cached_weekly and cached_weekly.get("key") == weekly_key:
                weekly_chart_data = cached_weekly["data"]
                weekly_warnings = cached_weekly["warnings"]
            else:
                try:
                    with st.spinner(f"Carregando gráfico semanal de {ticker}…"):
                        weekly_chart_data, weekly_warnings = screener.fetch_screen_chart(
                            ticker,
                            "Weekly",
                            cfg,
                            adjustment_label=adjustment,
                        )
                    st.session_state["_screening_weekly_chart"] = {
                        "key": weekly_key,
                        "data": weekly_chart_data,
                        "warnings": weekly_warnings,
                    }
                except Exception as exc:
                    weekly_warnings = [f"Não foi possível carregar o gráfico semanal: {exc}"]
            for warning in weekly_warnings:
                st.warning(warning)
        if weekly_chart_data.empty:
            st.warning(f"O Norgate não retornou dados semanais para o gráfico de {ticker}.")
        else:
            st.plotly_chart(
                charts.price_chart(
                    weekly_chart_data,
                    result.trades,
                    ticker,
                    rsi_entry=cfg.rsi_entry_threshold,
                    rsi_exit=cfg.exits.rsi_exit_threshold,
                    rsi_period=cfg.rsi_period,
                    default_lookback_years=1,
                ),
                use_container_width=True,
            )

        _render_yahoo_diagonal(ticker, result, cfg)

        st.subheader(f"Histórico completo das operações — {ticker}")
        st.caption(
            f"Backtest individual em {len(result.data):,} barras de "
            f"{result.data.index.min():%d/%m/%Y} a {result.data.index.max():%d/%m/%Y}, "
            f"usando os parâmetros de entrada e saída definidos acima."
        )
        metrics = compute_metrics(
            result.equity_curve,
            result.trades,
            cfg.initial_capital,
            len(result.data),
        )
        first_row = st.columns(4)
        first_row[0].metric("Operações", f"{metrics['num_trades']}")
        first_row[1].metric("Taxa de acerto", fmt_pct(metrics["win_rate"]))
        profit_factor = metrics["profit_factor"]
        first_row[2].metric(
            "Fator de lucro",
            "∞" if profit_factor == float("inf") else fmt_num(profit_factor),
        )
        first_row[3].metric(
            "Expectativa por operação",
            fmt_pct(metrics.get("expectancy_return", 0.0)),
        )

        second_row = st.columns(4)
        second_row[0].metric("Patrimônio final", fmt_money(metrics["final_equity"]))
        second_row[1].metric("Retorno total", fmt_pct(metrics["total_return"]))
        second_row[2].metric("CAGR", fmt_pct(metrics["cagr"]))
        second_row[3].metric("Drawdown máximo", fmt_pct(metrics["max_drawdown"]))

        third_row = st.columns(4)
        third_row[0].metric("Ganho médio", fmt_pct(metrics["avg_gain"]))
        third_row[1].metric("Perda média", fmt_pct(metrics["avg_loss"]))
        third_row[2].metric("Melhor operação", fmt_pct(metrics["best_trade"]))
        third_row[3].metric("Pior operação", fmt_pct(metrics["worst_trade"]))

        fourth_row = st.columns(4)
        fourth_row[0].metric("Permanência média", f"{metrics['avg_holding']:.1f} barras")
        fourth_row[1].metric("Sharpe", fmt_num(metrics["sharpe"]))
        fourth_row[2].metric("Sortino", fmt_num(metrics["sortino"]))
        fourth_row[3].metric("Tempo no mercado", fmt_pct(metrics["exposure"]))

        equity_col, drawdown_col = st.columns(2)
        equity_col.plotly_chart(
            charts.equity_chart(result.equity_curve, cfg.initial_capital),
            use_container_width=True,
        )
        drawdown_col.plotly_chart(
            charts.drawdown_chart(result.equity_curve),
            use_container_width=True,
        )

        recent_first = result.trades.sort_values("entry_date", ascending=False)
        render_trade_log(
            recent_first,
            result.equity_curve,
            key=f"screening_{ticker}",
        )
