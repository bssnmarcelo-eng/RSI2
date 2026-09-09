from __future__ import annotations

import pandas as pd

from src.charts import price_chart


def _weekly_prices() -> pd.DataFrame:
    index = pd.date_range("2024-01-05", periods=120, freq="7D")
    close = pd.Series(range(100, 220), index=index, dtype=float)
    return pd.DataFrame({
        "open": close - 1.0,
        "high": close + 2.0,
        "low": close - 2.0,
        "close": close,
        "rsi": 50.0,
    })


def test_price_chart_can_open_on_one_year_by_default():
    data = _weekly_prices()
    figure = price_chart(
        data,
        pd.DataFrame(),
        "XYZ",
        default_lookback_years=1,
    )

    expected_start = data.index.max() - pd.DateOffset(years=1)
    assert tuple(figure.layout.xaxis.range) == (
        expected_start.strftime("%Y-%m-%d"),
        data.index.max().strftime("%Y-%m-%d"),
    )
    assert figure.layout.updatemenus[0].active == 2


def test_price_chart_keeps_full_history_without_default_lookback():
    data = _weekly_prices()
    figure = price_chart(data, pd.DataFrame(), "XYZ")

    assert tuple(figure.layout.xaxis.range) == (
        data.index.min().strftime("%Y-%m-%d"),
        data.index.max().strftime("%Y-%m-%d"),
    )
