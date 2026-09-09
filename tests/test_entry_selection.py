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


def test_trade_quality_filter_keeps_lowest_range_decile_above_short_trend_floor():
    dates = pd.date_range("2024-01-05", periods=12, freq="W-FRI")
    results = {}
    rows = []
    for number in range(1, 11):
        ticker = f"T{number:02d}"
        results[ticker] = _result(dates, [100.0] * 12, [100.0] * 12)
        rows.append({
            "ticker": ticker,
            "signal_date": dates[10],
            "entry_date": dates[11],
            "signal_close": 100.0,
            "signal_range": float(number),
            "rsi_at_signal": float(number),
            "signal_atr_mult": 1.0,
        })
    selection = EntrySelectionConfig(
        max_entries_per_date=100,
        use_trade_quality_filter=True,
        quality_trend_period=10,
        quality_min_trend_pct=-3.0,
        quality_max_range_rank_pct=10.0,
    )

    selected = select_trades_per_entry_date(pd.DataFrame(rows), results, selection)

    assert selected["ticker"].tolist() == ["T01"]


def test_trade_quality_filter_does_not_promote_next_range_after_trend_rejection():
    dates = pd.date_range("2024-01-05", periods=12, freq="W-FRI")
    results = {}
    rows = []
    for number in range(1, 11):
        ticker = f"T{number:02d}"
        closes = [100.0] * 10 + ([80.0, 80.0] if number == 1 else [100.0, 100.0])
        results[ticker] = _result(dates, closes, [100.0] * 12)
        rows.append({
            "ticker": ticker,
            "signal_date": dates[10],
            "entry_date": dates[11],
            "signal_close": closes[10],
            "signal_range": float(number),
            "rsi_at_signal": float(number),
            "signal_atr_mult": 1.0,
        })
    selection = EntrySelectionConfig(
        max_entries_per_date=100,
        use_trade_quality_filter=True,
        quality_trend_period=10,
        quality_min_trend_pct=-3.0,
        quality_max_range_rank_pct=10.0,
    )

    selected = select_trades_per_entry_date(pd.DataFrame(rows), results, selection)

    assert selected.empty


def test_minimum_candidates_rejects_sparse_entry_dates():
    dates = pd.date_range("2024-01-05", periods=12, freq="W-FRI")
    rows = []
    results = {}
    for number in range(1, 4):
        ticker = f"T{number:02d}"
        results[ticker] = _result(dates, [100.0] * 12, [100.0] * 12)
        rows.append({
            "ticker": ticker,
            "signal_date": dates[10],
            "entry_date": dates[11],
            "signal_close": 100.0,
            "signal_range": 1.0,
            "rsi_at_signal": float(number),
            "signal_atr_mult": 1.0,
        })

    rejected = select_trades_per_entry_date(
        pd.DataFrame(rows),
        results,
        EntrySelectionConfig(max_entries_per_date=10, minimum_candidates_per_date=4),
    )
    admitted = select_trades_per_entry_date(
        pd.DataFrame(rows),
        results,
        EntrySelectionConfig(max_entries_per_date=10, minimum_candidates_per_date=3),
    )

    assert rejected.empty
    assert admitted["ticker"].tolist() == ["T01", "T02", "T03"]


def test_historical_win_rate_filter_is_causal_and_strictly_above_threshold():
    dates = pd.date_range("2024-01-05", periods=12, freq="W-FRI")
    rows = []
    results = {}
    returns = {
        "AAA": [0.10, 0.10, 0.10, -0.05, 0.10],  # 3/4 = 75% before final signal
        "BBB": [0.10, 0.10, 0.10, 0.10, -0.05],  # 4/4 = 100% before final signal
    }
    for ticker, ticker_returns in returns.items():
        results[ticker] = _result(dates, [100.0] * len(dates), [100.0] * len(dates))
        for number, net_return in enumerate(ticker_returns):
            rows.append({
                "ticker": ticker,
                "signal_date": dates[number * 2],
                "entry_date": dates[number * 2 + 1],
                "exit_date": dates[number * 2 + 1],
                "signal_close": 100.0,
                "signal_range": 1.0,
                "rsi_at_signal": 5.0,
                "signal_atr_mult": 1.0,
                "net_return": net_return,
            })
    selection = EntrySelectionConfig(
        max_entries_per_date=10,
        use_historical_win_rate_filter=True,
        historical_win_rate_threshold_pct=75.0,
        historical_win_rate_min_trades=4,
    )

    selected = select_trades_per_entry_date(pd.DataFrame(rows), results, selection)

    assert selected["ticker"].tolist() == ["BBB"]
    assert selected.iloc[0]["net_return"] == -0.05
