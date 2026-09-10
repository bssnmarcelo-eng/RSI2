"""Indicadores causais usados pelas estratégias do estudo."""
from __future__ import annotations

import numpy as np
import pandas as pd


def wilder_rsi(values: pd.Series, period: int) -> pd.Series:
    """RSI de Wilder com média inicial simples e suavização recursiva."""
    if period < 1:
        raise ValueError("O período do RSI deve ser positivo.")
    series = pd.to_numeric(values, errors="coerce").astype(float)
    delta = series.diff()
    gains = delta.clip(lower=0.0).to_numpy()
    losses = (-delta.clip(upper=0.0)).to_numpy()
    result = np.full(len(series), np.nan, dtype=float)
    if len(series) <= period:
        return pd.Series(result, index=series.index, name=f"rsi_{period}")

    avg_gain = float(np.nanmean(gains[1 : period + 1]))
    avg_loss = float(np.nanmean(losses[1 : period + 1]))

    def value(gain: float, loss: float) -> float:
        if gain == 0 and loss == 0:
            return 50.0
        if loss == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + gain / loss)

    result[period] = value(avg_gain, avg_loss)
    for i in range(period + 1, len(series)):
        avg_gain = ((period - 1) * avg_gain + gains[i]) / period
        avg_loss = ((period - 1) * avg_loss + losses[i]) / period
        result[i] = value(avg_gain, avg_loss)
    return pd.Series(result, index=series.index, name=f"rsi_{period}")


def streak(close: pd.Series) -> pd.Series:
    """Duração assinada da sequência de altas/baixas de fechamento."""
    values = pd.to_numeric(close, errors="coerce").astype(float).to_numpy()
    result = np.zeros(len(values), dtype=float)
    for i in range(1, len(values)):
        if values[i] > values[i - 1]:
            result[i] = result[i - 1] + 1 if result[i - 1] > 0 else 1
        elif values[i] < values[i - 1]:
            result[i] = result[i - 1] - 1 if result[i - 1] < 0 else -1
    return pd.Series(result, index=close.index, name="streak")


def percent_rank(returns: pd.Series, period: int = 100) -> pd.Series:
    """Percentual dos *period* retornos anteriores estritamente abaixo do atual."""
    if period < 1:
        raise ValueError("O período do PercentRank deve ser positivo.")
    values = pd.to_numeric(returns, errors="coerce").astype(float).to_numpy()
    result = np.full(len(values), np.nan, dtype=float)
    for i in range(period + 1, len(values)):
        current = values[i]
        history = values[i - period : i]
        if np.isfinite(current) and np.isfinite(history).all():
            result[i] = 100.0 * float(np.count_nonzero(history < current)) / period
    return pd.Series(result, index=returns.index, name=f"percent_rank_{period}")


def connors_rsi(
    close: pd.Series,
    price_period: int = 3,
    streak_period: int = 2,
    rank_period: int = 100,
) -> pd.Series:
    """ConnorsRSI padrão: média de RSI(3), RSI da sequência(2) e PercentRank(100)."""
    price_rsi = wilder_rsi(close, price_period)
    streak_rsi = wilder_rsi(streak(close), streak_period)
    rank = percent_rank(pd.to_numeric(close, errors="coerce").pct_change(), rank_period)
    result = (price_rsi + streak_rsi + rank) / 3.0
    result.name = "connors_rsi"
    return result


def historical_volatility(close: pd.Series, period: int = 100) -> pd.Series:
    """Volatilidade histórica anualizada, em percentual."""
    returns = np.log(pd.to_numeric(close, errors="coerce")).diff()
    result = returns.rolling(period, min_periods=period).std(ddof=1) * np.sqrt(252.0) * 100.0
    result.name = f"hv_{period}"
    return result
