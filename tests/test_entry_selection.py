from types import SimpleNamespace

import pandas as pd

from src.entry_selection import select_trades_per_entry_date
from src.types import EntrySelectionConfig, PortfolioEntryRanking


def _result(dates, closes, volumes):
    return SimpleNamespace(
        data=pd.DataFrame(
            {"close": closes, "volume": volumes},
            index=pd.DatetimeIndex(dates),
        )
    )


def _trades(dates):
    return pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "signal_date": dates[1],
                "entry_date": dates[2],
                "rsi_at_signal": 7.0,
                "signal_atr_mult": 3.0,
            },
            {
                "ticker": "BBB",
                "signal_date": dates[1],
                "entry_date": dates[2],
                "rsi_at_signal": 2.0,
                "signal_atr_mult": 1.5,
            },
        ]
    )


def test_per_asset_selection_keeps_only_lowest_rsi_on_entry_date():
    dates = pd.date_range("2024-01-05", periods=3, freq="W-FRI")
    results = {
        "AAA": _result(dates, [100, 99, 100], [100, 100, 100]),
        "BBB": _result(dates, [100, 98, 100], [100, 100, 100]),
    }

    selected = select_trades_per_entry_date(
        _trades(dates), results, EntrySelectionConfig()
    )

    assert selected["ticker"].tolist() == ["BBB"]


def test_per_asset_selection_supports_hammer_atr_ranking():
    dates = pd.date_range("2024-01-05", periods=3, freq="W-FRI")
    results = {
        "AAA": _result(dates, [100, 99, 100], [100, 100, 100]),
        "BBB": _result(dates, [100, 98, 100], [100, 100, 100]),
    }
    selection = EntrySelectionConfig(
        entry_ranking=PortfolioEntryRanking.LARGEST_HAMMER_ATR
    )

    selected = select_trades_per_entry_date(_trades(dates), results, selection)

    assert selected["ticker"].tolist() == ["AAA"]


def test_per_asset_relative_volume_ranking_uses_signal_close_only():
    dates = pd.date_range("2024-01-05", periods=3, freq="W-FRI")
    results = {
        "AAA": _result(dates, [100, 99, 100], [100, 110, 10_000]),
        "BBB": _result(dates, [100, 98, 100], [100, 300, 1]),
    }
    selection = EntrySelectionConfig(
        entry_ranking=PortfolioEntryRanking.HIGHEST_RELATIVE_VOLUME,
        ranking_lookback=2,
    )

    selected = select_trades_per_entry_date(_trades(dates), results, selection)

    assert selected["ticker"].tolist() == ["BBB"]
