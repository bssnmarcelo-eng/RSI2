"""Interactive Plotly chart builders for the results dashboard."""
from __future__ import annotations

import calendar

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .performance_metrics import drawdown_series, monthly_returns_table, yearly_returns


def price_chart(data: pd.DataFrame, trades: pd.DataFrame, ticker: str = "") -> go.Figure:
    """Candlestick price chart with entry (▲) and exit (▼) markers."""
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=data.index,
            open=data["open"], high=data["high"], low=data["low"], close=data["close"],
            name="Price", increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        )
    )
    if not trades.empty:
        fig.add_trace(
            go.Scatter(
                x=trades["entry_date"], y=trades["entry_price"], mode="markers",
                name="Entry", marker=dict(symbol="triangle-up", size=11, color="#2e7d32",
                                          line=dict(width=1, color="white")),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=trades["exit_date"], y=trades["exit_price"], mode="markers",
                name="Exit", marker=dict(symbol="triangle-down", size=11, color="#c62828",
                                         line=dict(width=1, color="white")),
            )
        )
    fig.update_layout(
        title=f"Price & Trades{f' — {ticker}' if ticker else ''}",
        xaxis_rangeslider_visible=False, height=520, margin=dict(l=40, r=20, t=50, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
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
