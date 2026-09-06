"""Causal cross-sectional selection for independently simulated trades."""
from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

from .types import EntrySelectionConfig, PortfolioEntryRanking


def select_trades_per_entry_date(
    trades: pd.DataFrame,
    results_by_ticker: Mapping[str, object],
    selection: EntrySelectionConfig,
) -> pd.DataFrame:
    """Keep only the best trades for each entry date.

    RSI and Hammer/ATR come directly from each trade's signal candle.  Volume,
    trend and volatility are calculated at the signal close using trailing data
    only.  Temporary ranking columns are removed from the returned trade log.
    """
    if trades.empty or selection.max_entries_per_date == 0:
        return trades.copy()
    if selection.max_entries_per_date < 0:
        raise ValueError("max_entries_per_date must be zero or greater")
    if selection.ranking_lookback < 2:
        raise ValueError("ranking_lookback must be at least 2")

    work = trades.copy()
    metric_by_ticker: dict[str, pd.DataFrame] = {}
    for ticker, result in results_by_ticker.items():
        frame = result.data
        close = pd.to_numeric(frame["close"], errors="coerce")
        lookback = selection.ranking_lookback
        average = close.rolling(lookback, min_periods=lookback).mean()
        metrics = pd.DataFrame(index=frame.index)
        metrics["trend"] = (close / average).replace([np.inf, -np.inf], np.nan)
        metrics["volatility"] = close.pct_change(fill_method=None).rolling(
            lookback, min_periods=lookback
        ).std()
        if "volume" in frame:
            volume = pd.to_numeric(frame["volume"], errors="coerce")
            average_volume = volume.rolling(lookback, min_periods=lookback).mean()
            metrics["relative_volume"] = (volume / average_volume).replace(
                [np.inf, -np.inf], np.nan
            )
        else:
            metrics["relative_volume"] = np.nan
        metric_by_ticker[str(ticker)] = metrics

    trend = []
    volatility = []
    relative_volume = []
    for row in work.itertuples(index=False):
        metrics = metric_by_ticker.get(str(row.ticker))
        signal_date = pd.Timestamp(row.signal_date)
        if metrics is None or signal_date not in metrics.index:
            trend.append(np.nan)
            volatility.append(np.nan)
            relative_volume.append(np.nan)
            continue
        values = metrics.loc[signal_date]
        trend.append(float(values["trend"]))
        volatility.append(float(values["volatility"]))
        relative_volume.append(float(values["relative_volume"]))

    work["_rank_trend"] = trend
    work["_rank_volatility"] = volatility
    work["_rank_relative_volume"] = relative_volume

    ranking = selection.entry_ranking
    if not isinstance(ranking, PortfolioEntryRanking):
        ranking = PortfolioEntryRanking(ranking)
    rank_fields = {
        PortfolioEntryRanking.LOWEST_RSI: ("rsi_at_signal", True),
        PortfolioEntryRanking.LARGEST_HAMMER_ATR: ("signal_atr_mult", False),
        PortfolioEntryRanking.HIGHEST_RELATIVE_VOLUME: ("_rank_relative_volume", False),
        PortfolioEntryRanking.STRONGEST_TREND: ("_rank_trend", False),
        PortfolioEntryRanking.HIGHEST_VOLATILITY: ("_rank_volatility", False),
    }
    field, ascending = rank_fields[ranking]
    work["_rank_missing"] = pd.to_numeric(work[field], errors="coerce").isna()
    work["_entry_date"] = pd.to_datetime(work["entry_date"])
    work = work.sort_values(
        ["_entry_date", "_rank_missing", field, "ticker"],
        ascending=[True, True, ascending, True],
        kind="stable",
    )
    admitted = work.groupby("_entry_date", sort=False).cumcount() < selection.max_entries_per_date
    return work.loc[admitted, trades.columns].sort_values("entry_date").reset_index(drop=True)
