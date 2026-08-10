"""Strategy/sizing parameter form (main area), rendered inside one st.form.

NOTE: widgets inside an st.form do not re-render conditionally until the form
is submitted, so dynamic show/hide is replaced by always-visible fields
(0 = "no limit" for prices; both commission models shown; rules gated by their
own checkboxes). The form batches all edits behind a single submit button."""
from __future__ import annotations

import streamlit as st

from src.types import (
    CommissionModel,
    CostConfig,
    Execution,
    ExitConfig,
    HammerParams,
    PatternConfig,
    PortfolioConfig,
    PortfolioSizing,
    SizingConfig,
    SizingMethod,
    StrategyConfig,
)


def _entry_tab() -> dict:
    """Render entry/indicator/pattern widgets; return their raw values."""
    c1, c2 = st.columns(2)
    rsi_period = c1.number_input("RSI period", min_value=1, max_value=100, value=2, step=1,
                                 key="p_rsi_period")
    rsi_entry = c2.number_input("RSI entry threshold (buy when below)", min_value=0.0,
                                max_value=100.0, value=10.0, step=1.0, key="p_rsi_entry")

    st.markdown("**Filtro de preço** — 0 = sem limite")
    c3, c4 = st.columns(2)
    min_price = c3.number_input("Min price", min_value=0.0, value=0.0, step=1.0, key="p_min_price",
                                help="Só opera quando o close do candle de sinal ≥ este valor.")
    max_price = c4.number_input("Max price", min_value=0.0, value=0.0, step=1.0, key="p_max_price",
                                help="Só opera quando o close do candle de sinal ≤ este valor.")

    st.markdown("**Execution timing**")
    entry_exec = st.radio(
        "Execução da entrada",
        ["Próxima abertura (realista)", "Limite no fechamento do sinal (próximo candle)", "Fechamento do sinal (menos realista)"],
        index=0, key="p_entry_exec",
        help="Limit: a buy limit at the signal candle's close, valid only the next bar — "
             "fills at the open if it gaps below the limit, at the limit if price retraces down "
             "to it, otherwise no trade.")
    exit_exec = st.radio(
        "Execução da saída", ["Próxima abertura (realista)", "Fechamento do sinal (menos realista)"], index=0,
        key="p_exit_exec")

    st.markdown("**🕯️ Candlestick Pattern (Hammer)**")
    use_hammer = st.checkbox("Hammer", value=True, key="p_use_hammer")
    with st.expander("Hammer parameters", expanded=False):
        percentile = st.slider(
            "Body percentile (open & close above High − Percentile × Range)",
            min_value=0.05, max_value=1.0, value=0.33, step=0.01, key="p_hammer_pct",
            help="Both open and close must sit in the top `percentile` fraction of the "
                 "candle range (near the high). 0.33 ≈ classic 'body in the upper third'.")
        require_bull = st.checkbox("Require bullish close (close >= open)", value=False,
                                   key="p_require_bull")
        st.markdown("**ATR range filter**")
        use_atr = st.checkbox("Require candle range (high − low) > N × ATR", value=True,
                              key="p_use_atr")
        atr_mult = st.number_input("ATR multiple (N)", min_value=0.0, value=1.0, step=0.25,
                                   key="p_atr_mult")
        atr_period = st.number_input("ATR period", min_value=1, max_value=200, value=14, step=1,
                                     key="p_atr_period")
    apply_actions = st.checkbox(
        "Aplicar dividendos e desdobramentos das colunas do CSV",
        value=False,
        key="p_corporate_actions",
        help="Ative somente para preços não ajustados com colunas dividend e/ou split; "
             "não ative para séries Total Return ou já ajustadas.",
    )
    return {
        "rsi_period": rsi_period, "rsi_entry": rsi_entry,
        "min_price": min_price, "max_price": max_price,
        "entry_exec": entry_exec, "exit_exec": exit_exec,
        "use_hammer": use_hammer, "percentile": percentile, "require_bull": require_bull,
        "use_atr": use_atr, "atr_mult": atr_mult, "atr_period": atr_period,
        "apply_actions": apply_actions,
    }


def _exits_tab() -> ExitConfig:
    """Render exit-rule widgets; return an ExitConfig."""
    st.caption("Quando várias regras estão ativas, prevalece a primeira acionada.")
    use_rsi_exit = st.checkbox("Sair quando o RSI fechar acima do limite", value=True, key="p_use_rsi_exit")
    rsi_exit = st.number_input("Limite de RSI para saída", min_value=0.0, max_value=100.0, value=70.0,
                               step=1.0, key="p_rsi_exit")
    use_max_bars = st.checkbox("Sair após N candles", value=True, key="p_use_max_bars")
    max_bars = st.number_input("Máximo de candles na posição", min_value=1, max_value=1000, value=5, step=1,
                               key="p_max_bars")
    use_pt = st.checkbox("Sair no alvo de lucro", value=False, key="p_use_pt")
    pt_pct = st.number_input("Alvo de lucro (%)", min_value=0.0, value=5.0, step=0.5, key="p_pt_pct")
    use_sl = st.checkbox("Sair no stop loss", value=False, key="p_use_sl")
    sl_pct = st.number_input("Stop loss (%)", min_value=0.0, value=3.0, step=0.5, key="p_sl_pct")
    use_sma = st.checkbox("Sair quando fechamento > SMA(n)", value=False, key="p_use_sma")
    sma_period = st.number_input("Período da SMA de saída", min_value=1, max_value=200, value=5, step=1,
                                 key="p_sma_period")
    use_signal_low_stop = st.checkbox(
        "Stop loss at signal candle's low", value=False, key="p_use_sls",
        help="Intrabar hard stop: if a bar's low pierces the signal (pattern) candle's "
             "low, exit within that bar at the stop level (or at the open if it gaps below).")
    use_rsi_cum_exit = st.checkbox(
        "Sair quando RSI(n) acumulado > X", value=False, key="p_use_rsi_cum",
        help="Soma do RSI dos últimos N períodos. Captura exaustão da reversão mesmo quando "
             "o RSI individual ainda não atingiu o threshold padrão.")
    col_rc1, col_rc2 = st.columns(2)
    rsi_cum_periods = col_rc1.number_input("Períodos (N)", min_value=1, max_value=50,
                                           value=2, step=1, key="p_rsi_cum_n")
    rsi_cum_threshold = col_rc2.number_input("Threshold (X)", min_value=0.0, max_value=1000.0,
                                             value=100.0, step=5.0, key="p_rsi_cum_x")
    return ExitConfig(
        use_rsi_exit=use_rsi_exit, rsi_exit_threshold=float(rsi_exit),
        use_max_bars=use_max_bars, max_bars=int(max_bars),
        use_profit_target=use_pt, profit_target_pct=float(pt_pct),
        use_stop_loss=use_sl, stop_loss_pct=float(sl_pct),
        use_sma_exit=use_sma, sma_period=int(sma_period),
        use_signal_low_stop=use_signal_low_stop,
        use_rsi_cum_exit=use_rsi_cum_exit,
        rsi_cum_periods=int(rsi_cum_periods),
        rsi_cum_threshold=float(rsi_cum_threshold),
    )


def _costs_tab() -> CostConfig:
    """Render transaction-cost widgets; return a CostConfig.

    Both commission models are shown (forms can't reveal them conditionally); the
    selectbox decides which one is used.
    """
    st.caption("Applied on every fill — entry and exit each count as one order.")
    cost_model = st.selectbox(
        "Modelo de comissão", ["IBKR Pro — Fixa (ações dos EUA)", "Genérica (fixa + %)"], index=0,
        key="p_cost_model")
    with st.expander("IBKR Pro — Fixed parameters", expanded=cost_model.startswith("IBKR")):
        per_share = st.number_input("USD per share", min_value=0.0, value=0.005, step=0.001,
                                    format="%.4f", key="p_ibkr_ps")
        min_order = st.number_input("Minimum per order (USD)", min_value=0.0, value=1.0, step=0.5,
                                    key="p_ibkr_min")
        max_pct = st.number_input("Max % of trade value", min_value=0.0, max_value=100.0,
                                  value=1.0, step=0.5, key="p_ibkr_maxpct") / 100.0
        st.caption("IBKR Pro · Fixed: USD 0.005/share, min USD 1.00/order, max 1% of trade "
                   "value (includes exchange & regulatory fees).")
    with st.expander("Parâmetros da comissão genérica", expanded=cost_model.startswith("Genérica")):
        comm_fixed = st.number_input("Fixed commission per fill", min_value=0.0, value=0.0, step=0.5,
                                     key="p_gen_fixed")
        comm_pct = st.number_input("Comissão (% do notional)", min_value=0.0, value=0.0, step=0.01,
                                   format="%.4f", key="p_gen_pct") / 100.0
    slippage = st.number_input("Slippage (pontos-base)", min_value=0.0, value=0.0, step=1.0,
                               key="p_slippage")
    margin_rate = st.number_input("Juros anuais de margem (%)", min_value=0.0, value=0.0,
                                  step=0.5, key="p_margin_rate") / 100.0
    borrow_fee = st.number_input("Taxa anual de aluguel para posições vendidas (%)", min_value=0.0,
                                 value=0.0, step=0.5, key="p_borrow_fee",
                                 help="A estratégia atual é somente comprada; o campo fica preparado para suporte futuro a shorts.") / 100.0
    if cost_model.startswith("IBKR"):
        costs = CostConfig(model=CommissionModel.IBKR_FIXED, ibkr_per_share=float(per_share),
                           ibkr_min_per_order=float(min_order), ibkr_max_pct=float(max_pct))
    else:
        costs = CostConfig(model=CommissionModel.GENERIC, commission_fixed=float(comm_fixed),
                           commission_pct=float(comm_pct))
    costs.slippage_bps = float(slippage)
    costs.annual_margin_rate = float(margin_rate)
    costs.annual_borrow_fee = float(borrow_fee)
    return costs


def _single_sizing_tab() -> tuple[float, SizingConfig]:
    """Single-asset capital & position-sizing widgets; return (initial_capital, SizingConfig)."""
    initial_capital = st.number_input("Capital inicial", min_value=1.0, value=100_000.0,
                                      step=1000.0, key="p_init_cap")
    label = st.selectbox(
        "Método de dimensionamento", ["Capital integral", "Capital fixo por operação", "Percentual do patrimônio"],
        index=0, key="p_sizing_method")
    c1, c2 = st.columns(2)
    fixed_capital = c1.number_input("Capital fixo por operação", min_value=1.0, value=10_000.0,
                                    step=1000.0, key="p_fixed_cap")
    percent = c2.number_input("Percent of equity (%)", min_value=0.0, max_value=100.0,
                              value=100.0, step=5.0, key="p_percent")
    allow_fractional = st.checkbox("Allow fractional shares", value=True, key="p_frac_single")
    method = {"Capital integral": SizingMethod.FULL, "Capital fixo por operação": SizingMethod.FIXED,
              "Percentual do patrimônio": SizingMethod.PERCENT}[label]
    return float(initial_capital), SizingConfig(
        method=method, fixed_capital=float(fixed_capital),
        percent=float(percent), allow_fractional=bool(allow_fractional))


def _portfolio_tab() -> PortfolioConfig:
    """Portfolio (shared capital) sizing widgets; return a PortfolioConfig."""
    initial_capital = st.number_input("Capital inicial compartilhado", min_value=1.0,
                                      value=100_000.0, step=1000.0, key="p_pf_cap")
    sizing_label = st.radio(
        "Dimensionamento das posições",
        ["% do patrimônio por operação", "Capital integral por operação (margem ilimitada)"],
        index=0, key="p_pf_sizing",
        help="O modo percentual limita a exposição pelo patrimônio × alavancagem. O modo integral "
             "aloca 100% da conta em cada sinal sem limite de poder de compra.")
    allow_fractional = st.checkbox("Allow fractional shares", value=True, key="p_pf_frac")
    c1, c2 = st.columns(2)
    pct_per_trade = c1.number_input("% of equity per trade (notional)", min_value=0.1,
                                    max_value=100.0, value=10.0, step=1.0, key="p_pf_pct")
    leverage = c2.number_input("Leverage (buying power = equity × this)", min_value=1.0,
                               max_value=10.0, value=1.0, step=0.5, key="p_pf_lev",
                               help="1.0 = cash account. IBKR Reg-T overnight ≈ 2×, intraday ≈ 4×.")
    cap = st.number_input("Max simultaneous positions (0 = unlimited)", min_value=0,
                          max_value=500, value=0, step=1, key="p_pf_maxpos")

    if sizing_label.startswith("Capital integral"):
        st.warning(
            "⚠️ Margem ilimitada: cada sinal aloca **100% do patrimônio**. A exposição "
            "pode passar de 100% (200%, 300%+) e o caixa pode ficar muito negativo. "
            "Resultado alavancado e mais arriscado.")
        return PortfolioConfig(
            initial_capital=float(initial_capital),
            sizing_mode=PortfolioSizing.FULL_EQUITY,
            allow_fractional=bool(allow_fractional))

    st.caption(
        f"Up to ~{int((leverage * 100) // pct_per_trade) if pct_per_trade else 0} positions fit at "
        f"{pct_per_trade:g}% each with {leverage:g}× leverage. Ties broken by most oversold (lowest RSI).")
    return PortfolioConfig(
        initial_capital=float(initial_capital), sizing_mode=PortfolioSizing.PERCENT,
        pct_per_trade=float(pct_per_trade), leverage=float(leverage),
        max_positions=int(cap), allow_fractional=bool(allow_fractional))


def configuration_form(mode: str, *, with_run: bool):
    """Render all strategy (and sizing) parameters inside one st.form with tabs.

    ``mode`` is one of: ``single``, ``per_asset``, ``optimizer``, ``portfolio``,
    ``screening``. Returns ``(cfg, pconf, submitted)`` where ``pconf`` is a
    PortfolioConfig only in portfolio mode (else ``None``). ``submitted`` is True
    on the rerun where the form's button was clicked. With ``with_run`` the button
    runs the backtest ("Aplicar e rodar"); otherwise it just applies parameters.
    """
    pconf = None
    sizing = None
    init_cap = None
    ex = ExitConfig()
    costs = CostConfig()
    submit_label = "Aplicar e rodar ▶" if with_run else "Aplicar parâmetros ▶"

    with st.form(f"config_form_{mode}"):
        st.subheader("⚙️ Parâmetros da estratégia")
        if mode == "screening":
            (tab_e,) = st.tabs(["📥 Entrada"])
            with tab_e:
                e = _entry_tab()
        else:
            tab_e, tab_x, tab_c, tab_s = st.tabs(
                ["📥 Entrada", "🚪 Saídas", "🧾 Custos", "💰 Sizing"])
            with tab_e:
                e = _entry_tab()
            with tab_x:
                ex = _exits_tab()
            with tab_c:
                costs = _costs_tab()
            with tab_s:
                if mode == "portfolio":
                    pconf = _portfolio_tab()
                else:
                    init_cap, sizing = _single_sizing_tab()
        submitted = st.form_submit_button(submit_label, type="primary")

    cfg = StrategyConfig(
        rsi_period=int(e["rsi_period"]),
        rsi_entry_threshold=float(e["rsi_entry"]),
        min_price=float(e["min_price"]),
        max_price=float(e["max_price"]),
        patterns=PatternConfig(
            use_hammer=e["use_hammer"],
            hammer=HammerParams(
                percentile=float(e["percentile"]),
                require_bullish_close=bool(e["require_bull"]),
                use_atr_filter=bool(e["use_atr"]),
                atr_period=int(e["atr_period"]),
                atr_multiple=float(e["atr_mult"]),
            ),
        ),
        entry_execution=(
            Execution.NEXT_OPEN if e["entry_exec"].startswith("Próxima")
            else Execution.LIMIT_AT_CLOSE if e["entry_exec"].startswith("Limite")
            else Execution.SIGNAL_CLOSE),
        exit_execution=Execution.NEXT_OPEN if e["exit_exec"].startswith("Próxima") else Execution.SIGNAL_CLOSE,
        exits=ex,
        costs=costs,
        apply_corporate_actions=bool(e["apply_actions"]),
    )
    if sizing is not None:
        cfg.sizing = sizing
        cfg.initial_capital = init_cap
    return cfg, pconf, submitted
