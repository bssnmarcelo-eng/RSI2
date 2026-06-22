"""Interactive Plotly chart builders for the results dashboard."""
from __future__ import annotations

import calendar

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .performance_metrics import drawdown_series, monthly_returns_table, yearly_returns


def price_chart(
    data: pd.DataFrame,
    trades: pd.DataFrame,
    ticker: str = "",
    rsi_entry: float = 10.0,
    rsi_exit: float = 70.0,
) -> go.Figure:
    """Candlestick price chart with Volume, SMA(200) and RSI(2) sub-panels.

    * Price pane: log-scale candlestick + SMA 200 + entry/exit markers.
    * Volume pane (shown when volume data is present): coloured bars.
    * RSI(2) pane (shown when RSI has been calculated): line + thresholds.

    Log-scale keeps multi-decade datasets (e.g. AAPL 1990-present) legible
    across the full price range.  Range-selector buttons rescale both axes.
    """
    has_vol = "volume" in data.columns and data["volume"].fillna(0).gt(0).any()
    has_rsi = "rsi" in data.columns

    # ── subplot layout ────────────────────────────────────────────────────
    n_extra = int(has_vol) + int(has_rsi)
    if n_extra == 0:
        row_heights = [1.0]
        total_height = 520
    elif n_extra == 1:
        row_heights = [0.72, 0.28]
        total_height = 640
    else:
        row_heights = [0.58, 0.14, 0.28]
        total_height = 720

    n_rows   = 1 + n_extra
    vol_row  = 2 if has_vol else None
    rsi_row  = (2 + int(has_vol)) if has_rsi else None

    fig = make_subplots(
        rows=n_rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=row_heights,
    )

    # ── price pane ────────────────────────────────────────────────────────
    fig.add_trace(
        go.Candlestick(
            x=data.index,
            open=data["open"], high=data["high"],
            low=data["low"],   close=data["close"],
            name="Preço",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        ),
        row=1, col=1,
    )

    # SMA 200 — only display once we have at least 200 bars of data
    sma200 = data["close"].rolling(200, min_periods=200).mean()
    if sma200.notna().any():
        fig.add_trace(
            go.Scatter(
                x=data.index, y=sma200,
                name="SMA 200",
                line=dict(color="#fb8c00", width=1.5, dash="solid"),
                opacity=0.9,
            ),
            row=1, col=1,
        )

    if not trades.empty:
        fig.add_trace(
            go.Scatter(
                x=trades["entry_date"], y=trades["entry_price"], mode="markers",
                name="Entrada",
                marker=dict(symbol="triangle-up", size=11, color="#2e7d32",
                            line=dict(width=1, color="white")),
            ),
            row=1, col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=trades["exit_date"], y=trades["exit_price"], mode="markers",
                name="Saída",
                marker=dict(symbol="triangle-down", size=11, color="#c62828",
                            line=dict(width=1, color="white")),
            ),
            row=1, col=1,
        )

    # ── volume pane ───────────────────────────────────────────────────────
    if has_vol:
        bar_colors = np.where(
            data["close"].values >= data["open"].values,
            "#26a69a", "#ef5350",
        )
        fig.add_trace(
            go.Bar(
                x=data.index,
                y=data["volume"].values,
                name="Volume",
                marker_color=bar_colors,
                opacity=0.7,
                showlegend=False,
            ),
            row=vol_row, col=1,
        )
        fig.update_yaxes(
            title_text="Volume",
            tickformat=".2s",
            fixedrange=False,
            row=vol_row, col=1,
        )

    # ── RSI pane ──────────────────────────────────────────────────────────
    if has_rsi:
        fig.add_trace(
            go.Scatter(
                x=data.index, y=data["rsi"].values,
                name="RSI(2)",
                line=dict(color="#5c6bc0", width=1.5),
            ),
            row=rsi_row, col=1,
        )
        # Entry threshold
        fig.add_hline(
            y=rsi_entry,
            line_dash="dash", line_color="#2e7d32", line_width=1,
            annotation_text=f"Entrada <{rsi_entry:g}",
            annotation_position="bottom right",
            row=rsi_row, col=1,
        )
        # Exit threshold
        fig.add_hline(
            y=rsi_exit,
            line_dash="dash", line_color="#c62828", line_width=1,
            annotation_text=f"Saída >{rsi_exit:g}",
            annotation_position="top right",
            row=rsi_row, col=1,
        )
        fig.update_yaxes(
            title_text="RSI",
            range=[0, 100],
            fixedrange=True,
            row=rsi_row, col=1,
        )

    # ── range buttons ─────────────────────────────────────────────────────
    # Plotly's built-in rangeselector updates only the X axis when clicked;
    # the Y axis stays fixed at the full-dataset range.  We replace it with
    # updatemenus buttons that set BOTH xaxis.range and yaxis.range.
    #
    # With make_subplots(shared_xaxes=True), Plotly creates xaxis, xaxis2,
    # xaxis3 … for each row. Setting only "xaxis.range" may not propagate
    # to the visible bottom axis (xaxis{n_rows}).  We therefore set all
    # possible x-axis keys so the update is guaranteed to take effect.
    last_dt  = data.index.max()
    first_dt = data.index.min()

    def _range_btn(label: str, start) -> dict:
        start_ts = pd.Timestamp(start)
        if start_ts < first_dt:
            start_ts = first_dt
        sub = data[data.index >= start_ts] if (data.index >= start_ts).any() else data
        lo = max(float(sub["low"].min())  * 0.97, 1e-9)
        hi = float(sub["high"].max()) * 1.03
        s = start_ts.strftime("%Y-%m-%d")
        e = last_dt.strftime("%Y-%m-%d")
        args: dict = {
            "yaxis.range":    [np.log10(lo), np.log10(hi)],
            "yaxis.autorange": False,
        }
        # Set every possible shared x-axis key (extra keys are silently ignored).
        for ax in ("xaxis", "xaxis2", "xaxis3"):
            args[f"{ax}.range"]    = [s, e]
            args[f"{ax}.autorange"] = False
        return dict(label=label, method="relayout", args=[args])

    range_buttons = [
        _range_btn("3M",  last_dt - pd.DateOffset(months=3)),
        _range_btn("6M",  last_dt - pd.DateOffset(months=6)),
        _range_btn("1A",  last_dt - pd.DateOffset(years=1)),
        _range_btn("3A",  last_dt - pd.DateOffset(years=3)),
        _range_btn("5A",  last_dt - pd.DateOffset(years=5)),
        _range_btn("Tudo", first_dt),
    ]

    # ── global layout ─────────────────────────────────────────────────────
    fig.update_layout(
        title=f"Preço & Operações{f' — {ticker}' if ticker else ''}",
        height=total_height,
        margin=dict(l=50, r=20, t=70, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.06, xanchor="right", x=1),
        # Log scale on price pane keeps multi-decade ranges legible.
        yaxis=dict(
            type="log",
            autorange=True,
            fixedrange=False,
            title_text="Preço",
        ),
        updatemenus=[dict(
            type="buttons",
            direction="left",
            buttons=range_buttons,
            x=0.0,   xanchor="left",
            y=1.0,   yanchor="bottom",
            bgcolor="#262730",
            bordercolor="#444",
            font=dict(size=12, color="#ffffff"),
            # active=5 → "Tudo" highlighted on load (no args applied).
            # Avoids the first-button quirk where active=-1 in Plotly.js
            # can be treated as index 0 ("3M") and apply its args before
            # the full-data autorange has settled.
            active=5,
            pad=dict(r=6, t=2, b=2),
        )],
    )
    # Disable rangeslider on ALL x-axes produced by make_subplots.
    fig.update_xaxes(rangeslider_visible=False, type="date")
    return fig


def rsi_chart(data: pd.DataFrame, entry_threshold: float, exit_threshold: float) -> go.Figure:
    """RSI line with the entry/exit threshold guides."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data.index, y=data["rsi"], name="RSI", line=dict(color="#5c6bc0")))
    fig.add_hline(y=entry_threshold, line_dash="dash", line_color="#2e7d32",
                  annotation_text=f"Entry < {entry_threshold:g}", annotation_position="bottom right")
    fig.add_hline(y=exit_threshold, line_dash="dash", line_color="#c62828",
                  annotation_text=f"Exit > {exit_threshold:g}", annotation_position="top right")
    fig.update_layout(title="RSI", height=260, margin=dict(l=40, r=20, t=40, b=30),
                      yaxis=dict(range=[0, 100]))
    return fig


def equity_chart(equity: pd.Series, initial_capital: float) -> go.Figure:
    """Equity curve with a dashed baseline at the starting capital."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=equity.index, y=equity.values, name="Equity",
                             line=dict(color="#1e88e5"), fill="tozeroy",
                             fillcolor="rgba(30,136,229,0.10)"))
    fig.add_hline(y=initial_capital, line_dash="dot", line_color="gray",
                  annotation_text="Initial capital", annotation_position="bottom right")
    fig.update_layout(title="Equity Curve", height=320, margin=dict(l=40, r=20, t=40, b=30))
    return fig


def drawdown_chart(equity: pd.Series) -> go.Figure:
    """Underwater (drawdown) curve as a filled area."""
    dd = drawdown_series(equity) * 100.0
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dd.index, y=dd.values, name="Drawdown", fill="tozeroy",
                             line=dict(color="#c62828"), fillcolor="rgba(198,40,40,0.20)"))
    fig.update_layout(title="Drawdown (%)", height=260, margin=dict(l=40, r=20, t=40, b=30))
    return fig


def returns_histogram(trades: pd.DataFrame) -> go.Figure:
    """Histogram of per-trade net returns (%)."""
    fig = go.Figure()
    if not trades.empty:
        fig.add_trace(go.Histogram(x=trades["net_return"] * 100.0, nbinsx=30,
                                   marker_color="#5c6bc0", name="Net return"))
        fig.add_vline(x=0, line_dash="dash", line_color="black")
    fig.update_layout(title="Distribution of Trade Returns (%)", height=300,
                      margin=dict(l=40, r=20, t=40, b=30), bargap=0.05)
    return fig


def monthly_heatmap(equity: pd.Series) -> go.Figure:
    """Heatmap of monthly returns (rows = year, columns = month)."""
    table = monthly_returns_table(equity)
    fig = go.Figure()
    if not table.empty:
        month_labels = [calendar.month_abbr[m] for m in table.columns]
        z = table.values * 100.0
        fig.add_trace(go.Heatmap(
            z=z, x=month_labels, y=table.index.astype(str),
            colorscale="RdYlGn", zmid=0, colorbar=dict(title="%"),
            text=np.round(z, 1), texttemplate="%{text}", hoverongaps=False,
        ))
    fig.update_layout(title="Monthly Returns Heatmap (%)", height=320,
                      margin=dict(l=40, r=20, t=40, b=30))
    return fig


def positions_over_time(positions_open: pd.Series) -> go.Figure:
    """Step-area chart of the number of open positions over time (portfolio mode)."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=positions_open.index, y=positions_open.values, name="Open positions",
        mode="lines", line_shape="hv", fill="tozeroy",
        line=dict(color="#6a1b9a"), fillcolor="rgba(106,27,154,0.15)",
    ))
    fig.update_layout(title="Open Positions Over Time", height=260,
                      margin=dict(l=40, r=20, t=40, b=30))
    return fig


def ticker_contribution(trades: pd.DataFrame) -> go.Figure:
    """Bar chart of net P&L contribution per ticker (portfolio mode)."""
    fig = go.Figure()
    n_tickers = 1
    if not trades.empty:
        grp = trades.groupby("ticker")["pnl"].sum().sort_values()
        n_tickers = len(grp)
        colors = ["#2e7d32" if v >= 0 else "#c62828" for v in grp.values]
        fig.add_trace(go.Bar(x=grp.values, y=grp.index.astype(str), orientation="h",
                             marker_color=colors, name="P&L"))
    fig.update_layout(title="Net P&L Contribution by Ticker",
                      height=max(260, 30 * n_tickers + 80),
                      margin=dict(l=60, r=20, t=40, b=30))
    return fig


def optimizer_heatmap(results: pd.DataFrame, x_param: str, y_param: str,
                      value_col: str, title: str) -> go.Figure:
    """Heatmap of an objective metric over a 2-parameter grid."""
    fig = go.Figure()
    if not results.empty and x_param in results and y_param in results:
        pivot = results.pivot_table(index=y_param, columns=x_param, values=value_col, aggfunc="mean")
        z = pivot.values.astype(float)
        fig.add_trace(go.Heatmap(
            z=z, x=[str(c) for c in pivot.columns], y=[str(i) for i in pivot.index],
            colorscale="Viridis", colorbar=dict(title=value_col),
            text=np.round(z, 3), texttemplate="%{text}", hoverongaps=False,
        ))
        fig.update_xaxes(title_text=x_param)
        fig.update_yaxes(title_text=y_param)
    fig.update_layout(title=title, height=420, margin=dict(l=60, r=20, t=50, b=40))
    return fig


def yearly_bar(equity: pd.Series) -> go.Figure:
    """Bar chart of calendar-year returns (%)."""
    yearly = yearly_returns(equity) * 100.0
    fig = go.Figure()
    if not yearly.empty:
        colors = ["#2e7d32" if v >= 0 else "#c62828" for v in yearly.values]
        fig.add_trace(go.Bar(x=yearly.index.astype(str), y=yearly.values, marker_color=colors,
                             name="Yearly return"))
    fig.update_layout(title="Yearly Returns (%)", height=300, margin=dict(l=40, r=20, t=40, b=30))
    return fig
