"""Streamlit front-end for the RSI(2) + bullish-candlestick mean-reversion strategy.

Two modes:
  * Single asset   -> backtest one ticker (full per-trade detail).
  * Portfolio      -> backtest many tickers sharing ONE capital pool, IBKR-style
                      buying power (equity * leverage), %-of-equity sizing.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd
import streamlit as st

from src import charts, data_loader, logger, optimizer, screener
from src.backtest_engine import BacktestEngine
from src.portfolio_engine import PortfolioEngine
from src.performance_metrics import compute_metrics
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
from src.utils import fmt_money, fmt_num, fmt_pct

st.set_page_config(page_title="RSI(2) + Candlestick Backtester", page_icon="📈", layout="wide")

STRATEGY_DESCRIPTION = """
**Long-only mean-reversion strategy.** A long *setup* is confirmed at a candle's
**close** when **both**:

1. **RSI(2)** is below the entry threshold (default **10**), and
2. the candle is a **bullish reversal pattern** (default: **Hammer**).

Because the signal is only known once the candle closes, the realistic default is
to **enter at the next candle's open** and **exit at the next candle's open** —
this avoids look-ahead bias.
"""

DISCLAIMER = """
⚠️ **Backtest results are hypothetical.** Past performance does not guarantee
future results. Signals are generated at candle close; default entries and exits
occur at the next candle's open to avoid look-ahead bias. Test any strategy
**out-of-sample** before considering real use. This tool is for research and
education only and is **not** investment advice.
"""


# =====================================================================
# Sidebar — shared strategy parameters
# =====================================================================
def build_strategy_params() -> StrategyConfig:
    """Build the parts of StrategyConfig shared by both modes (no sizing)."""
    st.sidebar.header("⚙️ Strategy Parameters")
    rsi_period = st.sidebar.number_input("RSI period", min_value=1, max_value=100, value=2, step=1)
    rsi_entry = st.sidebar.number_input("RSI entry threshold (buy when below)",
                                        min_value=0.0, max_value=100.0, value=10.0, step=1.0)

    st.sidebar.subheader("Price filter")
    use_price = st.sidebar.checkbox("Only trade within a price band", value=False,
                                    help="Skip entry signals whose signal-candle close is outside "
                                         "the band. Prices are in the data's units (use adjusted "
                                         "prices for split-adjusted data).")
    min_price = max_price = 0.0
    if use_price:
        c_lo, c_hi = st.sidebar.columns(2)
        min_price = c_lo.number_input("Min price (0 = none)", min_value=0.0, value=5.0, step=1.0)
        max_price = c_hi.number_input("Max price (0 = none)", min_value=0.0, value=0.0, step=1.0)
        if min_price > 0 and max_price > 0 and min_price > max_price:
            st.sidebar.warning("Min price > Max price — no trades will pass the filter.")

    st.sidebar.subheader("Execution timing")
    entry_exec = st.sidebar.radio(
        "Entry execution",
        ["Next open (realistic)", "Limit at signal close (next bar)", "Signal close (less realistic)"],
        index=0,
        help="Limit: a buy limit at the signal candle's close, valid only the next bar — "
             "fills at the open if it gaps below the limit, at the limit if price retraces down "
             "to it, otherwise no trade.")
    exit_exec = st.sidebar.radio(
        "Exit execution", ["Next open (realistic)", "Signal close (less realistic)"], index=0)

    st.sidebar.header("🕯️ Candlestick Pattern (Hammer)")
    use_hammer = st.sidebar.checkbox("Hammer", value=True)
    with st.sidebar.expander("Hammer parameters", expanded=False):
        percentile = st.slider(
            "Body percentile (open & close above High − Percentile × Range)",
            min_value=0.05, max_value=1.0, value=0.33, step=0.01,
            help="Both open and close must sit in the top `percentile` fraction of the "
                 "candle range (near the high). 0.33 ≈ classic 'body in the upper third'.")
        require_bull = st.checkbox("Require bullish close (close >= open)", value=False)
        st.markdown("**ATR range filter**")
        use_atr = st.checkbox("Require candle range (high − low) > N × ATR", value=True)
        atr_mult = st.number_input("ATR multiple (N)", min_value=0.0, value=1.0, step=0.25)
        atr_period = st.number_input("ATR period", min_value=1, max_value=200, value=14, step=1)

    st.sidebar.header("🚪 Exit Rules")
    st.sidebar.caption("When several are enabled, the first triggered exit wins.")
    use_rsi_exit = st.sidebar.checkbox("Exit when RSI closes above threshold", value=True)
    rsi_exit = st.sidebar.number_input("RSI exit threshold", min_value=0.0, max_value=100.0, value=70.0, step=1.0)
    use_max_bars = st.sidebar.checkbox("Exit after N bars (time stop)", value=True)
    max_bars = st.sidebar.number_input("Max bars held", min_value=1, max_value=1000, value=5, step=1)
    use_pt = st.sidebar.checkbox("Exit at profit target", value=False)
    pt_pct = st.sidebar.number_input("Profit target (%)", min_value=0.0, value=5.0, step=0.5)
    use_sl = st.sidebar.checkbox("Exit at stop loss", value=False)
    sl_pct = st.sidebar.number_input("Stop loss (%)", min_value=0.0, value=3.0, step=0.5)
    use_sma = st.sidebar.checkbox("Exit when close > SMA(n)", value=False)
    sma_period = st.sidebar.number_input("SMA period (exit)", min_value=1, max_value=200, value=5, step=1)
    use_signal_low_stop = st.sidebar.checkbox(
        "Stop loss at signal candle's low", value=False,
        help="Intrabar hard stop: if a bar's low pierces the signal (pattern) candle's "
             "low, exit within that bar at the stop level (or at the open if it gaps below).")

    st.sidebar.header("🧾 Transaction Costs")
    st.sidebar.caption("Applied on every fill — entry and exit each count as one order.")
    cost_model = st.sidebar.selectbox(
        "Commission model", ["IBKR Pro — Fixed (US stocks)", "Generic (fixed + %)"], index=0)
    if cost_model.startswith("IBKR"):
        with st.sidebar.expander("IBKR Fixed parameters", expanded=False):
            per_share = st.number_input("USD per share", min_value=0.0, value=0.005, step=0.001, format="%.4f")
            min_order = st.number_input("Minimum per order (USD)", min_value=0.0, value=1.0, step=0.5)
            max_pct = st.number_input("Max % of trade value", min_value=0.0, max_value=100.0,
                                      value=1.0, step=0.5) / 100.0
        st.sidebar.caption("IBKR Pro · Fixed: USD 0.005/share, min USD 1.00/order, max 1% of trade "
                           "value (includes exchange & regulatory fees).")
        costs = CostConfig(model=CommissionModel.IBKR_FIXED, ibkr_per_share=float(per_share),
                           ibkr_min_per_order=float(min_order), ibkr_max_pct=float(max_pct))
    else:
        comm_fixed = st.sidebar.number_input("Fixed commission per fill", min_value=0.0, value=0.0, step=0.5)
        comm_pct = st.sidebar.number_input("Commission (% of notional)", min_value=0.0, value=0.0, step=0.01,
                                           format="%.4f") / 100.0
        costs = CostConfig(model=CommissionModel.GENERIC, commission_fixed=float(comm_fixed),
                           commission_pct=float(comm_pct))
    costs.slippage_bps = float(st.sidebar.number_input("Slippage (basis points)", min_value=0.0,
                                                       value=0.0, step=1.0))

    return StrategyConfig(
        rsi_period=int(rsi_period),
        rsi_entry_threshold=float(rsi_entry),
        min_price=float(min_price),
        max_price=float(max_price),
        patterns=PatternConfig(
            use_hammer=use_hammer,
            hammer=HammerParams(
                percentile=float(percentile),
                require_bullish_close=bool(require_bull),
                use_atr_filter=bool(use_atr),
                atr_period=int(atr_period),
                atr_multiple=float(atr_mult),
            ),
        ),
        entry_execution=(
            Execution.NEXT_OPEN if entry_exec.startswith("Next")
            else Execution.LIMIT_AT_CLOSE if entry_exec.startswith("Limit")
            else Execution.SIGNAL_CLOSE),
        exit_execution=Execution.NEXT_OPEN if exit_exec.startswith("Next") else Execution.SIGNAL_CLOSE,
        exits=ExitConfig(
            use_rsi_exit=use_rsi_exit, rsi_exit_threshold=float(rsi_exit),
            use_max_bars=use_max_bars, max_bars=int(max_bars),
            use_profit_target=use_pt, profit_target_pct=float(pt_pct),
            use_stop_loss=use_sl, stop_loss_pct=float(sl_pct),
            use_sma_exit=use_sma, sma_period=int(sma_period),
            use_signal_low_stop=use_signal_low_stop,
        ),
        costs=costs,
    )


def build_single_sizing(cfg: StrategyConfig) -> StrategyConfig:
    """Add single-asset capital & position-sizing widgets to ``cfg``."""
    st.sidebar.header("💰 Position Sizing")
    cfg.initial_capital = float(st.sidebar.number_input(
        "Initial capital", min_value=1.0, value=100_000.0, step=1000.0))
    label = st.sidebar.selectbox(
        "Sizing method", ["Full equity", "Fixed capital per trade", "Percentage of equity"], index=0)
    fixed_capital = st.sidebar.number_input("Fixed capital per trade", min_value=1.0, value=10_000.0, step=1000.0)
    percent = st.sidebar.number_input("Percent of equity (%)", min_value=0.0, max_value=100.0, value=100.0, step=5.0)
    allow_fractional = st.sidebar.checkbox("Allow fractional shares", value=True)
    method = {"Full equity": SizingMethod.FULL, "Fixed capital per trade": SizingMethod.FIXED,
              "Percentage of equity": SizingMethod.PERCENT}[label]
    cfg.sizing = SizingConfig(method=method, fixed_capital=float(fixed_capital),
                              percent=float(percent), allow_fractional=bool(allow_fractional))
    return cfg


def build_portfolio_config() -> PortfolioConfig:
    """Portfolio (shared capital) sizing widgets."""
    st.sidebar.header("💰 Portfolio & Buying Power")
    initial_capital = st.sidebar.number_input("Initial capital (shared pool)", min_value=1.0,
                                               value=100_000.0, step=1000.0)
    sizing_label = st.sidebar.radio(
        "Position sizing",
        ["% of equity per trade", "Full equity per trade (unlimited margin)"],
        index=0,
        help="'% of equity' caps exposure at equity × leverage. 'Full equity' puts 100% of "
             "the account into every signal with no buying-power limit (fully leveraged).")
    allow_fractional = st.sidebar.checkbox("Allow fractional shares", value=True)

    if sizing_label.startswith("Full equity"):
        st.sidebar.warning(
            "⚠️ Margem ilimitada: cada sinal aloca **100% do patrimônio**. A exposição "
            "pode passar de 100% (200%, 300%+) e o caixa pode ficar muito negativo. "
            "Resultado alavancado e mais arriscado.")
        return PortfolioConfig(
            initial_capital=float(initial_capital),
            sizing_mode=PortfolioSizing.FULL_EQUITY,
            allow_fractional=bool(allow_fractional))

    pct_per_trade = st.sidebar.number_input("% of equity per trade (notional)", min_value=0.1,
                                            max_value=100.0, value=10.0, step=1.0)
    leverage = st.sidebar.number_input("Leverage (buying power = equity × this)", min_value=1.0,
                                       max_value=10.0, value=1.0, step=0.5,
                                       help="1.0 = cash account. IBKR Reg-T overnight ≈ 2×, intraday ≈ 4×.")
    cap = st.sidebar.number_input("Max simultaneous positions (0 = unlimited)", min_value=0,
                                  max_value=500, value=0, step=1)
    st.sidebar.caption(
        f"Up to ~{int((leverage * 100) // pct_per_trade) if pct_per_trade else 0} positions fit at "
        f"{pct_per_trade:g}% each with {leverage:g}× leverage. Ties broken by most oversold (lowest RSI).")
    return PortfolioConfig(
        initial_capital=float(initial_capital), sizing_mode=PortfolioSizing.PERCENT,
        pct_per_trade=float(pct_per_trade), leverage=float(leverage),
        max_positions=int(cap), allow_fractional=bool(allow_fractional))


# =====================================================================
# Rendering — single asset
# =====================================================================
def render_metrics(metrics: dict) -> None:
    st.subheader("📊 Performance Summary")
    r1 = st.columns(4)
    r1[0].metric("Final equity", fmt_money(metrics["final_equity"]))
    r1[1].metric("Total return", fmt_pct(metrics["total_return"]))
    r1[2].metric("CAGR", fmt_pct(metrics["cagr"]))
    r1[3].metric("Max drawdown", fmt_pct(metrics["max_drawdown"]))
    r2 = st.columns(4)
    r2[0].metric("Trades", f"{metrics['num_trades']}")
    r2[1].metric("Win rate", fmt_pct(metrics["win_rate"]))
    pf = metrics["profit_factor"]
    r2[2].metric("Profit factor", "∞" if pf == float("inf") else fmt_num(pf))
    r2[3].metric("Expectancy / trade", fmt_money(metrics["expectancy"]))
    r3 = st.columns(4)
    r3[0].metric("Sharpe", fmt_num(metrics["sharpe"]))
    r3[1].metric("Sortino", fmt_num(metrics["sortino"]))
    r3[2].metric("Avg gain", fmt_pct(metrics["avg_gain"]))
    r3[3].metric("Avg loss", fmt_pct(metrics["avg_loss"]))
    r4 = st.columns(4)
    r4[0].metric("Best trade", fmt_pct(metrics["best_trade"]))
    r4[1].metric("Worst trade", fmt_pct(metrics["worst_trade"]))
    r4[2].metric("Avg holding (bars)", fmt_num(metrics["avg_holding"], 1))
    r4[3].metric("Exposure", fmt_pct(metrics["exposure"]))


def render_charts(result) -> None:
    cfg = result.config
    st.subheader("📈 Charts")
    st.plotly_chart(charts.price_chart(result.data, result.trades, cfg.ticker), use_container_width=True)
    st.plotly_chart(charts.rsi_chart(result.data, cfg.rsi_entry_threshold,
                                     cfg.exits.rsi_exit_threshold), use_container_width=True)
    c1, c2 = st.columns(2)
    c1.plotly_chart(charts.equity_chart(result.equity_curve, cfg.initial_capital), use_container_width=True)
    c2.plotly_chart(charts.drawdown_chart(result.equity_curve), use_container_width=True)
    c3, c4 = st.columns(2)
    c3.plotly_chart(charts.returns_histogram(result.trades), use_container_width=True)
    c4.plotly_chart(charts.yearly_bar(result.equity_curve), use_container_width=True)
    st.plotly_chart(charts.monthly_heatmap(result.equity_curve), use_container_width=True)


def render_trade_log(trades: pd.DataFrame, equity: pd.Series, key: str) -> None:
    st.subheader("📒 Trade Log")
    if trades.empty:
        st.info("No trades were generated with the current parameters.")
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
    st.dataframe(display, use_container_width=True, hide_index=True)
    cols = st.columns(2)
    cols[0].download_button("⬇️ Download trade log (CSV)", data=trades.to_csv(index=False).encode("utf-8"),
                            file_name="trade_log.csv", mime="text/csv", key=f"{key}_trades")
    eq = equity.rename("equity").to_frame()
    eq.index.name = "date"
    cols[1].download_button("⬇️ Download equity curve (CSV)", data=eq.to_csv().encode("utf-8"),
                            file_name="equity_curve.csv", mime="text/csv", key=f"{key}_equity")


# =====================================================================
# Rendering — portfolio
# =====================================================================
def render_portfolio_metrics(metrics: dict, result) -> None:
    st.subheader("📊 Portfolio Performance")
    r1 = st.columns(4)
    r1[0].metric("Final equity", fmt_money(metrics["final_equity"]))
    r1[1].metric("Total return", fmt_pct(metrics["total_return"]))
    r1[2].metric("CAGR", fmt_pct(metrics["cagr"]))
    r1[3].metric("Max drawdown", fmt_pct(metrics["max_drawdown"]))
    r2 = st.columns(4)
    r2[0].metric("Trades", f"{metrics['num_trades']}")
    r2[1].metric("Win rate", fmt_pct(metrics["win_rate"]))
    pf = metrics["profit_factor"]
    r2[2].metric("Profit factor", "∞" if pf == float("inf") else fmt_num(pf))
    r2[3].metric("Expectancy / trade", fmt_money(metrics["expectancy"]))
    r3 = st.columns(4)
    r3[0].metric("Sharpe", fmt_num(metrics["sharpe"]))
    r3[1].metric("Sortino", fmt_num(metrics["sortino"]))
    r3[2].metric("Time in market", fmt_pct(result.time_in_market))
    r3[3].metric("Avg positions", fmt_num(result.avg_positions, 2))
    r4 = st.columns(4)
    r4[0].metric("Peak concurrent", f"{result.max_concurrent}")
    r4[1].metric("Max gross exposure", fmt_pct(result.exposure.max()))
    r4[2].metric("Best trade", fmt_pct(metrics["best_trade"]))
    r4[3].metric("Worst trade", fmt_pct(metrics["worst_trade"]))


def per_ticker_table(trades: pd.DataFrame) -> pd.DataFrame:
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
    return out.reset_index().rename(columns={"ticker": "Ticker"})


def render_portfolio(result) -> None:
    cfg = result.config
    st.subheader("📈 Portfolio Charts")
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

    st.subheader("🏷️ Per-Ticker Breakdown")
    if result.trades.empty:
        st.info("No trades were generated with the current parameters.")
    else:
        st.dataframe(per_ticker_table(result.trades), use_container_width=True, hide_index=True)

    # Drill-down: inspect one asset's price + signals.
    st.subheader("🔍 Inspect an Asset")
    tickers = sorted(result.frames.keys())
    sel = st.selectbox("Ticker", tickers)
    frame = result.frames[sel]
    tr = result.trades[result.trades["ticker"] == sel] if not result.trades.empty else result.trades
    st.plotly_chart(charts.price_chart(frame, tr, sel), use_container_width=True)
    st.plotly_chart(charts.rsi_chart(frame, cfg.rsi_entry_threshold, cfg.exits.rsi_exit_threshold),
                    use_container_width=True)

    render_trade_log(result.trades, result.equity_curve, key="pf")


# =====================================================================
# Data loading helpers (shared)
# =====================================================================
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


# =====================================================================
# Mode flows
# =====================================================================
def run_single_mode(cfg: StrategyConfig, note: str = ""):
    st.header("1 · Load data")
    uploaded = st.file_uploader(
        "Upload an OHLCV CSV (columns: date, ticker/symbol, open, high, low, close, "
        "adj/adjusted close, volume). Decimal commas, ; separators and DD/MM/YYYY dates are handled.",
        type=["csv"], accept_multiple_files=False)
    if uploaded is None:
        st.info("⬆️ Upload a CSV to begin. All processing is local — no external APIs are used.")
        return
    combined = load_combined(uploaded)
    if combined.empty:
        return

    st.header("2 · Select ticker & date range")
    tickers = data_loader.get_tickers(combined)
    selected = tickers[0] if len(tickers) == 1 else st.selectbox("Ticker", tickers) if tickers else None
    if tickers and len(tickers) == 1:
        st.caption(f"Single ticker detected: **{selected}**")
    start, end = date_range_picker(combined)
    if start is None:
        return

    data, warns = data_loader.prepare(combined, ticker=selected, start=start, end=end)
    for w in warns:
        st.warning(w)
    if data.empty:
        st.error("No data in the selected range.")
        return
    cfg.ticker = selected or ""
    if not cfg.patterns.any_enabled():
        st.error("Enable at least one candlestick pattern in the sidebar.")
        return

    st.header("3 · Run backtest")
    st.caption(f"Loaded **{len(data)}** candles ({data.index.min().date()} → {data.index.max().date()}).")
    if not st.button("▶️ Run Backtest", type="primary"):
        return
    with st.spinner("Running candle-by-candle backtest…"):
        result = BacktestEngine(data, cfg).run()
        metrics = compute_metrics(result.equity_curve, result.trades, cfg.initial_capital, len(data))
    for w in result.warnings:
        st.warning(w)
    render_metrics(metrics)
    render_charts(result)
    render_trade_log(result.trades, result.equity_curve, key="single")

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


def collect_multi_asset_data(cfg: StrategyConfig, select_label: str):
    """Shared steps 1–2 for the multi-asset modes: upload, pick tickers, date range.

    Returns a dict ``{ticker: cleaned_ohlc}`` ready for backtesting, or ``None`` if
    the user has not supplied enough to proceed yet.
    """
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
        st.error("Enable at least one candlestick pattern in the sidebar.")
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


def run_portfolio_mode(cfg: StrategyConfig, pconf: PortfolioConfig, note: str = ""):
    data_by_ticker = collect_multi_asset_data(cfg, "Tickers in the portfolio")
    if data_by_ticker is None:
        return

    st.header("3 · Run backtest")
    total_bars = sum(len(d) for d in data_by_ticker.values())
    if pconf.sizing_mode == PortfolioSizing.FULL_EQUITY:
        sizing_txt = "**100%**/trade · **unlimited** buying power"
    else:
        sizing_txt = f"**{pconf.pct_per_trade:g}%**/trade · **{pconf.leverage:g}×** leverage"
    st.caption(f"Portfolio of **{len(data_by_ticker)}** assets · "
               f"capital **{fmt_money(pconf.initial_capital, 0)}** · {sizing_txt} · "
               f"{total_bars:,} candle-rows.")
    if not st.button("▶️ Run Portfolio Backtest", type="primary"):
        return
    with st.spinner(f"Running portfolio backtest across {len(data_by_ticker)} assets…"):
        result = PortfolioEngine(data_by_ticker, cfg, pconf).run()
        metrics = compute_metrics(result.equity_curve, result.trades, pconf.initial_capital,
                                  len(result.equity_curve))
        metrics["exposure"] = result.time_in_market  # portfolio-appropriate exposure
    for w in result.warnings:
        st.warning(w)
    render_portfolio_metrics(metrics, result)
    render_portfolio(result)

    tickers = sorted(result.frames.keys())
    eq = result.equity_curve
    positions = pd.concat([result.positions_open, result.exposure], axis=1)
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


# =====================================================================
# Per-asset (independent) mode
# =====================================================================
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


def render_trades_overview(trades: pd.DataFrame, n_assets: int) -> None:
    """Aggregate trades panorama + table of every operation (per-asset mode)."""
    st.subheader("📊 Trades Overview")
    if trades.empty:
        st.info("No trades were generated with the current parameters.")
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

    # Distribution of all trade returns.
    st.plotly_chart(charts.returns_histogram(trades), use_container_width=True)

    # Table with every operation (all assets), most recent first.
    st.subheader("📒 All Operations")
    cols_order = ["ticker", "signal_date", "rsi_at_signal", "signal_range",
                  "signal_body_percentile", "signal_atr_mult", "pattern", "entry_date",
                  "entry_price", "exit_date", "exit_price", "exit_reason", "bars_held",
                  "gross_return", "net_return", "pnl"]
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
    st.dataframe(disp, use_container_width=True, hide_index=True)

    st.download_button("⬇️ Download all operations (CSV)",
                       data=trades.sort_values("entry_date").to_csv(index=False).encode("utf-8"),
                       file_name="all_operations.csv", mime="text/csv", key="all_ops_csv")


def run_per_asset_mode(cfg: StrategyConfig, note: str = ""):
    data_by_ticker = collect_multi_asset_data(cfg, "Tickers to test independently")
    if data_by_ticker is None:
        return

    st.header("3 · Run backtest")
    st.caption(f"Testing **{len(data_by_ticker)}** assets independently · "
               f"**{fmt_money(cfg.initial_capital, 0)}** capital applied to each · "
               f"trade stats pooled across all assets.")
    if not st.button("▶️ Run Per-Asset Backtests", type="primary"):
        return

    all_trades = []
    with st.spinner(f"Backtesting {len(data_by_ticker)} assets independently…"):
        for t, d in data_by_ticker.items():
            res = BacktestEngine(d, replace(cfg, ticker=t)).run()
            if not res.trades.empty:
                all_trades.append(res.trades)
    combined = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame(
        columns=["ticker", "signal_date", "rsi_at_signal", "pattern", "entry_date",
                 "entry_price", "exit_date", "exit_price", "exit_reason", "bars_held",
                 "gross_return", "net_return", "pnl"])
    render_trades_overview(combined, len(data_by_ticker))

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
              "config": logger.config_dict(cfg), "metrics": stats})


# =====================================================================
# Backtest logging
# =====================================================================
def save_to_log(mode: str, summary: dict, tables: dict, full: dict) -> None:
    """Persist a run to the backtest log; never let a logging error break the app."""
    try:
        run_id = logger.log_run(mode, summary, tables, full)
        st.success(f"💾 Saved to backtest log: **{run_id}** (see the *Backtest Log* mode).")
    except Exception as exc:
        st.warning(f"Could not write to the backtest log: {exc}")


def _equity_frame(equity: pd.Series) -> pd.DataFrame:
    eq = equity.rename("equity").to_frame()
    eq.index.name = "date"
    return eq


# =====================================================================
# Optimizer mode (per-asset grid search, in/out-of-sample)
# =====================================================================
MAX_COMBOS = 4000


def build_param_ranges() -> dict:
    """UI to pick which parameters to sweep and their min/max/step ranges."""
    st.subheader("Parameters to optimize")
    labels = {k: v[0] for k, v in optimizer.PARAM_SPECS.items()}
    chosen = st.multiselect(
        "Variables to sweep (grid = all combinations)",
        options=list(optimizer.PARAM_SPECS.keys()),
        default=["rsi_entry_threshold", "max_bars"],
        format_func=lambda k: labels[k])
    ranges = {}
    for key in chosen:
        label, is_int, dmin, dmax, dstep = optimizer.PARAM_SPECS[key]
        st.markdown(f"**{label}**")
        c1, c2, c3 = st.columns(3)
        step_fmt = "%d" if is_int else "%.4f"
        lo = c1.number_input(f"{label} — min", value=float(dmin), key=f"opt_{key}_min", format=step_fmt)
        hi = c2.number_input(f"{label} — max", value=float(dmax), key=f"opt_{key}_max", format=step_fmt)
        step = c3.number_input(f"{label} — step", value=float(dstep), min_value=0.0001,
                               key=f"opt_{key}_step", format=step_fmt)
        vals = optimizer.param_values(lo, hi, step, is_int)
        ranges[key] = vals
        st.caption(f"{len(vals)} value(s): {vals if len(vals) <= 12 else str(vals[:12]) + ' …'}")
    return ranges


def render_optimizer_results(results: pd.DataFrame, ranges: dict, objective: str,
                             split_dt, min_trades: int) -> None:
    obj_label = optimizer.OBJECTIVES[objective]
    train_col = f"train_{objective}"
    valid = results[results["valid"]].copy()
    if valid.empty:
        st.error(f"No parameter combination produced at least {min_trades} in-sample trades. "
                 "Widen the ranges, lower 'min trades', or extend the date range.")
        return None

    ranked = valid.sort_values(train_col, ascending=False).reset_index(drop=True)
    best = ranked.iloc[0]
    param_keys = list(ranges.keys())

    st.subheader("🏆 Best parameters (by in-sample objective)")
    st.success(" · ".join(f"**{optimizer.PARAM_SPECS[k][0]}** = "
                          f"{int(best[k]) if optimizer.PARAM_SPECS[k][1] else best[k]:g}"
                          for k in param_keys) or "(no parameters swept)")
    m = st.columns(4)
    test_col = f"test_{objective}"
    m[0].metric(f"In-sample {obj_label}", fmt_num(best[train_col], 3))
    m[1].metric(f"Out-of-sample {obj_label}", fmt_num(best[test_col], 3))
    m[2].metric("In-sample trades", f"{int(best['train_trades'])}")
    m[3].metric("Out-of-sample trades", f"{int(best['test_trades'])}")
    if split_dt is not None:
        st.caption(f"Train/test split at **{pd.Timestamp(split_dt).date()}** "
                   f"(trades with entry on/before = in-sample). A big gap between in-sample and "
                   f"out-of-sample {obj_label} is a sign of overfitting.")

    # Heatmap when exactly two parameters were swept.
    if len(param_keys) == 2:
        st.plotly_chart(
            charts.optimizer_heatmap(ranked, param_keys[0], param_keys[1], train_col,
                                     f"In-sample {obj_label}"),
            use_container_width=True)

    # Results table.
    st.subheader("📋 All combinations")
    show_cols = param_keys + [
        "train_trades", train_col, "train_profit_factor", "train_win_rate",
        "test_trades", test_col, "test_profit_factor",
    ]
    show_cols = [c for c in show_cols if c in ranked.columns]
    disp = ranked[show_cols].copy()
    rename = {f"train_{objective}": f"IS {obj_label}", f"test_{objective}": f"OOS {obj_label}",
              "train_trades": "IS trades", "test_trades": "OOS trades",
              "train_profit_factor": "IS profit factor", "test_profit_factor": "OOS profit factor",
              "train_win_rate": "IS win rate"}
    for k in param_keys:
        rename[k] = optimizer.PARAM_SPECS[k][0]
    for col in ["train_profit_factor", "test_profit_factor"]:
        if col in disp:
            disp[col] = disp[col].map(lambda v: "∞" if v == float("inf") else fmt_num(v))
    if "train_win_rate" in disp:
        disp["train_win_rate"] = disp["train_win_rate"].map(fmt_pct)
    for col in [train_col, test_col]:
        disp[col] = disp[col].map(lambda v: fmt_num(v, 3))
    disp = disp.rename(columns=rename)
    st.dataframe(disp, use_container_width=True, hide_index=True)

    st.download_button("⬇️ Download optimization results (CSV)",
                       data=ranked.to_csv(index=False).encode("utf-8"),
                       file_name="optimization_results.csv", mime="text/csv", key="opt_csv")
    return ranked


def run_optimizer_mode(cfg: StrategyConfig, note: str = ""):
    data_by_ticker = collect_multi_asset_data(cfg, "Tickers in the optimization universe")
    if data_by_ticker is None:
        return

    st.header("3 · Optimization setup")
    ranges = build_param_ranges()
    if not ranges:
        st.info("Select at least one parameter to sweep.")
        return

    c1, c2, c3 = st.columns(3)
    obj_key = c1.selectbox("Objective (maximize)", list(optimizer.OBJECTIVES.keys()),
                           format_func=lambda k: optimizer.OBJECTIVES[k], index=0)
    train_frac = c2.slider("In-sample fraction (train)", min_value=0.3, max_value=0.9,
                           value=0.7, step=0.05)
    min_trades = c3.number_input("Min in-sample trades (to rank a combo)", min_value=1,
                                 value=10, step=1)

    n_combos = 1
    for vals in ranges.values():
        n_combos *= len(vals)
    n_runs = n_combos * len(data_by_ticker)
    st.caption(f"**{n_combos}** parameter combinations × **{len(data_by_ticker)}** assets "
               f"= **{n_runs:,}** backtests · objective: **{optimizer.OBJECTIVES[obj_key]}** · "
               f"train **{train_frac:.0%}** / test **{1 - train_frac:.0%}**.")
    if n_combos > MAX_COMBOS:
        st.error(f"{n_combos} combinations exceeds the cap of {MAX_COMBOS}. Reduce ranges or step count.")
        return

    if not st.button("▶️ Run Optimization", type="primary"):
        return

    bar = st.progress(0.0, text="Running grid search…")
    results, split_dt = optimizer.run_grid(
        data_by_ticker, cfg, ranges, train_frac=float(train_frac),
        min_trades=int(min_trades), progress=lambda p: bar.progress(p, text="Running grid search…"))
    bar.empty()
    ranked = render_optimizer_results(results, ranges, obj_key, split_dt, int(min_trades))

    if ranked is not None and not ranked.empty:
        param_keys = list(ranges.keys())
        best = ranked.iloc[0]
        best_params = {k: (int(best[k]) if optimizer.PARAM_SPECS[k][1] else float(best[k]))
                       for k in param_keys}
        starts = [d.index.min() for d in data_by_ticker.values()]
        ends = [d.index.max() for d in data_by_ticker.values()]
        save_to_log(
            "Optimizer",
            summary={"note": note, "tickers": ", ".join(sorted(data_by_ticker.keys())),
                     "n_assets": len(data_by_ticker), "n_combos": len(results),
                     "objective": optimizer.OBJECTIVES[obj_key],
                     "start": str(min(starts).date()), "end": str(max(ends).date()),
                     "best_params": json.dumps(best_params),
                     "best_is": float(best[f"train_{obj_key}"]),
                     "best_oos": float(best[f"test_{obj_key}"]),
                     "best_is_trades": int(best["train_trades"]),
                     "train_frac": float(train_frac)},
            tables={"optimization_results": ranked},
            full={"meta": {"tickers": sorted(data_by_ticker.keys()),
                           "n_assets": len(data_by_ticker), "n_combos": len(results),
                           "objective": obj_key, "train_frac": float(train_frac),
                           "min_trades": int(min_trades),
                           "split_date": str(split_dt.date()) if split_dt is not None else None,
                           "ranges": {k: list(map(float, v)) for k, v in ranges.items()}},
                  "config": logger.config_dict(cfg), "metrics": {"best_params": best_params}})


# =====================================================================
# Market Screening mode
# =====================================================================
@st.cache_data(ttl=86_400, show_spinner=False)
def _cached_constituents(index: str):
    return screener.get_constituents(index)


def run_screening_mode(cfg: StrategyConfig) -> None:
    st.header("🔎 Market Screening")
    st.markdown(
        "Scan an index for tickers **currently firing the entry signal** on the chosen "
        "timeframe. The conditions are exactly the sidebar entry rules — RSI(period) below "
        "threshold **and** a percentile hammer (plus the optional ATR and price filters). "
        "Exits, sizing and costs are ignored here. Data: Yahoo Finance via `yfinance`.")

    if not cfg.patterns.any_enabled():
        st.error("Enable the Hammer pattern in the sidebar to screen.")
        return

    c1, c2, c3 = st.columns(3)
    index = c1.selectbox("Index", screener.INDICES, index=1)
    timeframe = c2.selectbox("Timeframe", list(screener.TIMEFRAMES.keys()), index=1)
    max_tickers = c3.number_input("Max tickers (0 = all)", min_value=0, max_value=5000, value=0, step=50)
    ignore_last = st.checkbox("Evaluate the last fully-closed candle (ignore the in-progress one)",
                              value=True)
    st.caption("Entry condition recap: "
               f"RSI({cfg.rsi_period}) < {cfg.rsi_entry_threshold:g} · hammer percentile "
               f"{cfg.patterns.hammer.percentile:g}"
               + (f" · range > {cfg.patterns.hammer.atr_multiple:g}×ATR({cfg.patterns.hammer.atr_period})"
                  if cfg.patterns.hammer.use_atr_filter else "")
               + ((f" · price ≥ {cfg.min_price:g}" if cfg.min_price > 0 else "")
                  + (f" · price ≤ {cfg.max_price:g}" if cfg.max_price > 0 else "")))

    if not st.button("▶️ Run Screening", type="primary"):
        return

    # Constituents (cached for a day).
    try:
        with st.spinner(f"Fetching {index} constituents…"):
            tickers = _cached_constituents(index)
    except Exception as exc:
        st.error(f"Could not fetch constituents for {index}: {exc}")
        return
    if not tickers:
        st.error("No constituents found.")
        return
    if max_tickers > 0:
        tickers = tickers[:int(max_tickers)]
    st.caption(f"Scanning **{len(tickers)}** tickers on **{timeframe}**…")

    bar = st.progress(0.0, text="Downloading data & screening…")
    try:
        hits, scanned, errors = screener.run_screen(
            tickers, timeframe, cfg, ignore_last=ignore_last,
            progress=lambda p: bar.progress(min(p, 1.0), text="Downloading data & screening…"))
    except ImportError:
        bar.empty()
        st.error("`yfinance` is not installed. Run: `pip install yfinance lxml requests`.")
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
    disp["date"] = pd.to_datetime(disp["date"]).dt.strftime("%Y-%m-%d %H:%M")
    disp["close"] = hits["close"].map(fmt_money)
    disp["rsi"] = hits["rsi"].map(lambda v: fmt_num(v, 2))
    disp["body_percentile"] = hits["body_percentile"].map(lambda v: fmt_num(v, 3))
    disp["range"] = hits["range"].map(lambda v: fmt_num(v, 2))
    st.dataframe(disp, use_container_width=True, hide_index=True)
    st.download_button("⬇️ Download screening hits (CSV)",
                       data=hits.to_csv(index=False).encode("utf-8"),
                       file_name=f"screening_{index.replace(' ', '_')}_{timeframe.replace(' ', '')}.csv",
                       mime="text/csv", key="screen_csv")
    st.caption(f"Sorted by RSI (most oversold first). 'date' is the evaluated candle. "
               f"'body_percentile' = (high − body bottom) ÷ range — always ≤ your percentile "
               f"setting ({cfg.patterns.hammer.percentile:g}); lower = body closer to the high "
               f"(stronger hammer).")


# =====================================================================
# Backtest Log viewer mode
# =====================================================================
def run_log_mode() -> None:
    st.header("📁 Backtest Log")
    runs = logger.load_runs_index()
    if runs.empty:
        st.info("No runs logged yet. Run a backtest in any mode — each run is saved here "
                "automatically (results, metrics and tables).")
        return

    runs_sorted = runs.sort_values("timestamp", ascending=False).reset_index(drop=True)
    st.caption(f"**{len(runs_sorted)}** run(s) saved at `{logger.LOG_DIR}`.")
    st.dataframe(runs_sorted, use_container_width=True, hide_index=True)
    st.download_button("⬇️ Download runs index (CSV)", data=runs.to_csv(index=False).encode("utf-8"),
                       file_name="runs.csv", mime="text/csv", key="runs_index_csv")

    st.subheader("🔎 Inspect a run")
    sel = st.selectbox("Run", runs_sorted["run_id"].astype(str).tolist())
    summ = logger.load_summary(sel)
    if summ:
        with st.expander("Config + metrics (summary.json)", expanded=False):
            st.json(summ)
    for name, path in logger.list_run_tables(sel).items():
        st.markdown(f"**{name}**")
        try:
            df = pd.read_csv(path)
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.download_button(f"⬇️ Download {name}.csv",
                               data=df.to_csv(index=False).encode("utf-8"),
                               file_name=f"{sel}_{name}.csv", mime="text/csv",
                               key=f"dl_{sel}_{name}")
        except Exception as exc:
            st.warning(f"Could not read {name}.csv: {exc}")

    st.subheader("🗑️ Clear log")
    confirm = st.checkbox("I understand this permanently deletes ALL saved runs")
    if st.button("Delete entire backtest log", disabled=not confirm):
        logger.clear_log()
        st.success("Backtest log cleared. Reload the page to refresh.")


# =====================================================================
# Main
# =====================================================================
def main() -> None:
    st.title("📈 RSI(2) + Candlestick Mean-Reversion Backtester")
    st.markdown(STRATEGY_DESCRIPTION)
    with st.expander("Important assumptions & disclaimer", expanded=False):
        st.markdown(DISCLAIMER)

    st.sidebar.header("🧭 Mode")
    mode = st.sidebar.radio(
        "Backtest mode",
        ["Portfolio (shared capital)", "Per-asset (independent)", "Single asset",
         "Optimizer (per-asset grid)", "🔎 Market Screening", "📁 Backtest Log"],
        index=0,
        help="Portfolio = one shared capital pool with aggregated results. "
             "Per-asset = every asset tested independently with the full capital. "
             "Single = one ticker. Optimizer = grid-search parameters on the per-asset "
             "pooled trades with an in/out-of-sample split. Market Screening = scan an "
             "index for tickers firing the signal now. Backtest Log = saved-run history.")

    if mode.startswith("📁"):
        run_log_mode()
        st.markdown("---")
        st.caption(DISCLAIMER)
        return

    if mode.startswith("🔎"):
        cfg = build_strategy_params()
        run_screening_mode(cfg)
        st.markdown("---")
        st.caption(DISCLAIMER)
        return

    note = st.sidebar.text_input(
        "Run label / note (optional)",
        help="Saved with the run in the backtest log to help you find it later "
             "(e.g. 'IBKR 2x leverage test').")

    cfg = build_strategy_params()
    if mode.startswith("Portfolio"):
        pconf = build_portfolio_config()
        run_portfolio_mode(cfg, pconf, note)
    elif mode.startswith("Per-asset"):
        cfg = build_single_sizing(cfg)
        run_per_asset_mode(cfg, note)
    elif mode.startswith("Optimizer"):
        cfg = build_single_sizing(cfg)
        run_optimizer_mode(cfg, note)
    else:
        cfg = build_single_sizing(cfg)
        run_single_mode(cfg, note)

    st.markdown("---")
    st.caption(DISCLAIMER)


if __name__ == "__main__":
    main()
