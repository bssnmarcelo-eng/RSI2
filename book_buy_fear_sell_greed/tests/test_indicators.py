import numpy as np
import pandas as pd

from fear_greed.indicators import connors_rsi, percent_rank, streak, wilder_rsi


def test_streak_resets_and_changes_sign():
    s = pd.Series([20, 20.5, 20.75, 19.75, 19.5, 19.35, 19.35, 19.4])
    assert streak(s).tolist() == [0, 1, 2, -1, -2, -3, 0, 1]


def test_percent_rank_uses_only_previous_values():
    returns = pd.Series([np.nan, 0.01, 0.02, -0.01, 0.03])
    rank = percent_rank(returns, 3)
    assert rank.iloc[-1] == 100.0


def test_rsi_bounds_and_connors_shape():
    close = pd.Series(np.linspace(100, 150, 150) + np.sin(np.arange(150)))
    assert wilder_rsi(close, 3).dropna().between(0, 100).all()
    crsi = connors_rsi(close)
    assert len(crsi) == len(close)
    assert crsi.dropna().between(0, 100).all()
