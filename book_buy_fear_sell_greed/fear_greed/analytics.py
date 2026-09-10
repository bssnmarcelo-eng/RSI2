"""Métricas e tabelas de diagnóstico baseadas na curva diária da carteira."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(slots=True)
class PortfolioAnalytics:
    metrics: dict[str, float]
    daily: pd.DataFrame
    monthly: pd.DataFrame
    monthly_heatmap: pd.DataFrame
    yearly: pd.DataFrame
    by_ticker: pd.DataFrame
    drawdown_episodes: pd.DataFrame


def _safe_div(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator and np.isfinite(denominator) else 0.0


def _profit_factor(gains: float, losses: float) -> float:
    if losses:
        return float(gains / abs(losses))
    return float("inf") if gains > 0 else 0.0


def _streak(values: pd.Series, positive: bool) -> int:
    best = current = 0
    for value in values.fillna(0):
        matches = value > 0 if positive else value < 0
        current = current + 1 if matches else 0
        best = max(best, current)
    return best


def _drawdown_episodes(drawdown: pd.Series) -> pd.DataFrame:
    rows: list[dict] = []
    active_start = trough_date = None
    trough = 0.0
    for date, value in drawdown.items():
        if value < 0 and active_start is None:
            active_start = date
            trough_date = date
            trough = float(value)
        elif active_start is not None and value < trough:
            trough = float(value)
            trough_date = date
        if active_start is not None and value >= -1e-12:
            rows.append({"inicio": active_start, "fundo": trough_date, "recuperacao": date, "drawdown": trough, "duracao_barras": int(drawdown.loc[active_start:date].size - 1), "em_aberto": False})
            active_start = trough_date = None
            trough = 0.0
    if active_start is not None:
        rows.append({"inicio": active_start, "fundo": trough_date, "recuperacao": pd.NaT, "drawdown": trough, "duracao_barras": int(drawdown.loc[active_start:].size - 1), "em_aberto": True})
    result = pd.DataFrame(rows)
    return result.sort_values("drawdown").reset_index(drop=True) if not result.empty else result


def _period_returns(equity: pd.Series, frequency: str) -> pd.Series:
    sampled = equity.resample(frequency).last().dropna()
    if sampled.empty:
        return pd.Series(dtype=float)
    returns = sampled.pct_change()
    returns.iloc[0] = sampled.iloc[0] / equity.iloc[0] - 1
    return returns


def analyze_portfolio(equity: pd.DataFrame, trades: pd.DataFrame, initial_capital: float) -> PortfolioAnalytics:
    if equity.empty:
        empty = pd.DataFrame()
        return PortfolioAnalytics({}, empty, empty, empty, empty, empty, empty)
    daily = equity.copy().sort_index()
    curve = daily.equity.astype(float)
    daily["daily_return"] = curve.pct_change().fillna(0.0)
    daily["running_peak"] = curve.cummax()
    daily["drawdown"] = curve / daily.running_peak - 1.0
    daily["rolling_12m_return"] = curve / curve.shift(252) - 1.0
    daily["rolling_12m_volatility"] = daily.daily_return.rolling(252).std(ddof=1) * np.sqrt(252)
    rolling_std = daily.daily_return.rolling(252).std(ddof=1)
    daily["rolling_12m_sharpe"] = (daily.daily_return.rolling(252).mean() / rolling_std.replace(0, np.nan)) * np.sqrt(252)
    returns = daily.daily_return
    nonzero_returns = returns.iloc[1:]
    years = max((curve.index[-1] - curve.index[0]).days / 365.25, 1 / 365.25)
    annual_return = (curve.iloc[-1] / initial_capital) ** (1 / years) - 1 if curve.iloc[-1] > 0 else -1.0
    volatility = float(nonzero_returns.std(ddof=1) * np.sqrt(252)) if len(nonzero_returns) > 1 else 0.0
    sharpe = _safe_div(float(nonzero_returns.mean() * 252), volatility)
    downside = nonzero_returns[nonzero_returns < 0]
    downside_deviation = float(downside.std(ddof=1) * np.sqrt(252)) if len(downside) > 1 else 0.0
    sortino = _safe_div(float(nonzero_returns.mean() * 252), downside_deviation)
    max_drawdown = float(daily.drawdown.min())
    ulcer = float(np.sqrt(np.mean(np.square(daily.drawdown.clip(upper=0)))))
    open_positions = daily.get("open_positions", pd.Series(0, index=daily.index))
    gross_exposure = daily.get("gross_exposure_pct", pd.Series(0.0, index=daily.index))
    time_in_market = float((open_positions > 0).mean())
    avg_gross_exposure = float(gross_exposure.mean() / 100)
    max_gross_exposure = float(gross_exposure.max() / 100)
    drawdown_episodes = _drawdown_episodes(daily.drawdown)
    longest_drawdown = float(drawdown_episodes.duracao_barras.max()) if not drawdown_episodes.empty else 0.0

    monthly_returns = _period_returns(curve, "ME")
    monthly = pd.DataFrame({"retorno": monthly_returns})
    if not monthly.empty:
        monthly["ano"] = monthly.index.year
        monthly["mes"] = monthly.index.month
    heatmap = monthly.pivot(index="ano", columns="mes", values="retorno") if not monthly.empty else pd.DataFrame()
    yearly_returns = _period_returns(curve, "YE")
    yearly_rows: list[dict] = []
    for year, group in daily.groupby(daily.index.year):
        year_returns = group.daily_return
        year_dd = group.equity / group.equity.cummax() - 1
        yearly_rows.append({
            "ano": int(year),
            "retorno": float(yearly_returns.get(pd.Timestamp(f"{year}-12-31"), np.nan)),
            "volatilidade": float(year_returns.std(ddof=1) * np.sqrt(252)) if len(year_returns) > 1 else 0.0,
            "drawdown_max": float(year_dd.min()),
            "dias_exposto": int((group.get("open_positions", pd.Series(0, index=group.index)) > 0).sum()),
            "exposicao_media": float(group.get("gross_exposure_pct", pd.Series(0, index=group.index)).mean() / 100),
        })
    yearly = pd.DataFrame(yearly_rows).set_index("ano") if yearly_rows else pd.DataFrame()

    trade_returns = trades.net_return.astype(float) if not trades.empty else pd.Series(dtype=float)
    pnl = trades.pnl.astype(float) if not trades.empty else pd.Series(dtype=float)
    winners, losers = trade_returns[trade_returns > 0], trade_returns[trade_returns < 0]
    total_costs = float(daily.costs.iloc[-1]) if "costs" in daily else float(trades.commission.sum()) if not trades.empty else 0.0
    traded_notional = float(daily.cumulative_traded_notional.iloc[-1]) if "cumulative_traded_notional" in daily else 0.0
    turnover = _safe_div(traded_notional, float(curve.mean()) * years)
    var95 = float(nonzero_returns.quantile(0.05)) if len(nonzero_returns) else 0.0
    tail = nonzero_returns[nonzero_returns <= var95]
    metrics = {
        "initial_capital": float(initial_capital),
        "final_equity": float(curve.iloc[-1]),
        "net_profit": float(curve.iloc[-1] - initial_capital),
        "total_return": float(curve.iloc[-1] / initial_capital - 1),
        "cagr": float(annual_return),
        "annual_volatility": volatility,
        "annual_downside_deviation": downside_deviation,
        "sharpe_0rf": sharpe,
        "sortino_0rf": sortino,
        "max_drawdown": max_drawdown,
        "calmar": _safe_div(annual_return, abs(max_drawdown)),
        "return_over_max_drawdown": _safe_div(float(curve.iloc[-1] / initial_capital - 1), abs(max_drawdown)),
        "ulcer_index": ulcer,
        "longest_drawdown_bars": longest_drawdown,
        "daily_var_95": var95,
        "daily_cvar_95": float(tail.mean()) if len(tail) else 0.0,
        "avg_daily_return": float(nonzero_returns.mean()) if len(nonzero_returns) else 0.0,
        "positive_days": float((nonzero_returns > 0).mean()) if len(nonzero_returns) else 0.0,
        "best_day": float(nonzero_returns.max()) if len(nonzero_returns) else 0.0,
        "worst_day": float(nonzero_returns.min()) if len(nonzero_returns) else 0.0,
        "positive_months": float((monthly_returns > 0).mean()) if len(monthly_returns) else 0.0,
        "best_month": float(monthly_returns.max()) if len(monthly_returns) else 0.0,
        "worst_month": float(monthly_returns.min()) if len(monthly_returns) else 0.0,
        "trades": float(len(trades)),
        "win_rate": float((trade_returns > 0).mean()) if len(trade_returns) else 0.0,
        "avg_trade": float(trade_returns.mean()) if len(trade_returns) else 0.0,
        "median_trade": float(trade_returns.median()) if len(trade_returns) else 0.0,
        "avg_win": float(winners.mean()) if len(winners) else 0.0,
        "avg_loss": float(losers.mean()) if len(losers) else 0.0,
        "payoff_ratio": _safe_div(float(winners.mean()) if len(winners) else 0.0, abs(float(losers.mean())) if len(losers) else 0.0),
        "profit_factor": _profit_factor(float(pnl[pnl > 0].sum()), float(pnl[pnl < 0].sum())),
        "expectancy_usd": float(pnl.mean()) if len(pnl) else 0.0,
        "best_trade": float(trade_returns.max()) if len(trade_returns) else 0.0,
        "worst_trade": float(trade_returns.min()) if len(trade_returns) else 0.0,
        "avg_bars": float(trades.bars_held.mean()) if not trades.empty else 0.0,
        "max_win_streak": float(_streak(trade_returns, True)),
        "max_loss_streak": float(_streak(trade_returns, False)),
        "costs": total_costs,
        "cost_drag": total_costs / initial_capital,
        "annual_turnover": turnover,
        "sessions": float(len(daily)),
        "years": float(years),
        "time_in_market": time_in_market,
        "cagr_per_time_in_market": _safe_div(annual_return, time_in_market),
        "cagr_per_avg_exposure": _safe_div(annual_return, avg_gross_exposure),
        "avg_positions": float(open_positions.mean()),
        "max_positions": float(open_positions.max()),
        "configured_leverage": float(daily.get("configured_leverage", pd.Series(1.0, index=daily.index)).iloc[-1]),
        "avg_gross_exposure": avg_gross_exposure,
        "max_gross_exposure": max_gross_exposure,
    }

    by_ticker_rows: list[dict] = []
    if not trades.empty:
        for ticker, group in trades.groupby("ticker"):
            ret = group.net_return.astype(float)
            gp = group.pnl.astype(float)
            by_ticker_rows.append({
                "ticker": ticker,
                "operacoes": len(group),
                "acerto": float((ret > 0).mean()),
                "retorno_medio": float(ret.mean()),
                "retorno_mediano": float(ret.median()),
                "pnl": float(gp.sum()),
                "contribuicao_pnl": _safe_div(float(gp.sum()), float(pnl.sum())),
                "profit_factor": _profit_factor(float(gp[gp > 0].sum()), float(gp[gp < 0].sum())),
                "custos": float(group.commission.sum()),
                "barras_media": float(group.bars_held.mean()),
            })
    by_ticker = pd.DataFrame(by_ticker_rows).sort_values("pnl", ascending=False) if by_ticker_rows else pd.DataFrame()
    return PortfolioAnalytics(metrics, daily, monthly, heatmap, yearly, by_ticker, drawdown_episodes)


def benchmark_curve(data: pd.DataFrame, index: pd.DatetimeIndex, initial_capital: float) -> pd.Series:
    close = data.Close.reindex(index).ffill().dropna()
    if close.empty:
        return pd.Series(dtype=float)
    curve = close / close.iloc[0] * initial_capital
    return curve.reindex(index).ffill()
