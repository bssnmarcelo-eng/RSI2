"""Causal filter research for a saved per-asset backtest.

The script enriches the saved trade log with information available at each
signal close, then evaluates simple, auditable filters on chronological
train/validation/test samples. Generated tables are written below ``.local-run``.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from src.norgate_loader import fetch_price

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
OUTPUT = ROOT / ".local-run"


def _price_features(frame: pd.DataFrame) -> pd.DataFrame:
    close = pd.to_numeric(frame["close"], errors="coerce")
    volume = pd.to_numeric(frame.get("volume"), errors="coerce")
    returns = close.pct_change(fill_method=None)
    result = pd.DataFrame(index=frame.index)
    for window in (4, 13, 26, 52):
        result[f"momentum_{window}"] = close.pct_change(window, fill_method=None)
    for window in (10, 20, 40):
        average = close.rolling(window, min_periods=window).mean()
        result[f"trend_{window}"] = close / average - 1.0
    for window in (10, 20, 52):
        result[f"volatility_{window}"] = returns.rolling(window, min_periods=window).std()
    for window in (10, 20, 52):
        average_volume = volume.rolling(window, min_periods=window).mean()
        result[f"relative_volume_{window}"] = volume / average_volume
    result["drawdown_52"] = close / close.rolling(52, min_periods=20).max() - 1.0
    result["range_pct"] = (
        pd.to_numeric(frame["high"], errors="coerce")
        - pd.to_numeric(frame["low"], errors="coerce")
    ) / close
    return result.replace([np.inf, -np.inf], np.nan)


def enrich(run_id: str, refresh: bool = False) -> pd.DataFrame:
    OUTPUT.mkdir(exist_ok=True)
    cache = OUTPUT / f"{run_id}-causal-features.csv"
    if cache.exists() and not refresh:
        return pd.read_csv(cache, parse_dates=["signal_date", "entry_date", "exit_date"])

    path = LOGS / run_id / "all_operations.csv"
    trades = pd.read_csv(path, parse_dates=["signal_date", "entry_date", "exit_date"])
    feature_rows: list[dict[str, float]] = []
    tickers = trades["ticker"].drop_duplicates().tolist()
    for number, ticker in enumerate(tickers, start=1):
        frame, _warnings = fetch_price(
            ticker,
            adjustment_label="Total Return (splits + dividendos)",
            start_date="1990-01-01",
            end_date="2026-09-04",
            frequency_label="Semanal",
        )
        metrics = _price_features(frame) if not frame.empty else pd.DataFrame()
        ticker_trades = trades.loc[trades["ticker"] == ticker, ["signal_date"]]
        for index, row in ticker_trades.iterrows():
            values: dict[str, float] = {"_row": index}
            if row.signal_date in metrics.index:
                values.update(metrics.loc[row.signal_date].to_dict())
            feature_rows.append(values)
        if number % 25 == 0 or number == len(tickers):
            print(f"features {number}/{len(tickers)}", flush=True)

    features = pd.DataFrame(feature_rows).set_index("_row")
    enriched = trades.join(features)
    enriched["candidate_count"] = enriched.groupby("entry_date")["ticker"].transform("size")

    rank_columns = [
        "rsi_at_signal", "signal_body_percentile", "signal_atr_mult",
        "momentum_4", "momentum_13", "momentum_26", "momentum_52",
        "trend_10", "trend_20", "trend_40", "volatility_10",
        "volatility_20", "volatility_52", "relative_volume_10",
        "relative_volume_20", "relative_volume_52", "drawdown_52", "range_pct",
    ]
    for column in rank_columns:
        enriched[f"xrank_{column}"] = enriched.groupby("entry_date")[column].rank(
            method="average", pct=True
        )

    # Historical trade quality uses only outcomes from earlier, already-closed
    # positions in the same ticker. Per-asset simulations never overlap trades.
    enriched = enriched.sort_values(["ticker", "signal_date"]).reset_index(drop=True)
    grouped = enriched.groupby("ticker", sort=False)["net_return"]
    enriched["prior_trade_count"] = grouped.cumcount()
    enriched["prior_mean_all"] = grouped.transform(lambda s: s.expanding().mean().shift())
    enriched["prior_win_all"] = grouped.transform(lambda s: s.gt(0).expanding().mean().shift())
    for window in (3, 5, 10):
        enriched[f"prior_mean_{window}"] = grouped.transform(
            lambda s, w=window: s.shift().rolling(w, min_periods=w).mean()
        )
        enriched[f"prior_win_{window}"] = grouped.transform(
            lambda s, w=window: s.gt(0).shift().rolling(w, min_periods=w).mean()
        )
        enriched[f"prior_min_{window}"] = grouped.transform(
            lambda s, w=window: s.shift().rolling(w, min_periods=w).min()
        )
    enriched = enriched.sort_values(["entry_date", "ticker"]).reset_index(drop=True)
    enriched.to_csv(cache, index=False)
    return enriched


def metrics(frame: pd.DataFrame) -> dict[str, float]:
    returns = frame["net_return"].dropna()
    gains = returns[returns > 0].sum()
    losses = -returns[returns < 0].sum()
    return {
        "n": int(len(returns)),
        "win_rate": float(returns.gt(0).mean()) if len(returns) else math.nan,
        "mean": float(returns.mean()) if len(returns) else math.nan,
        "median": float(returns.median()) if len(returns) else math.nan,
        "profit_factor": float(gains / losses) if losses > 0 else math.inf,
        "min": float(returns.min()) if len(returns) else math.nan,
        "loss_20_rate": float(returns.le(-0.20).mean()) if len(returns) else math.nan,
        "sum_log_return": float(np.log1p(returns.clip(lower=-0.999999999)).sum()),
    }


def _split(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "train_1993_2010": frame.loc[frame.entry_date.dt.year <= 2010],
        "validation_2011_2018": frame.loc[frame.entry_date.dt.year.between(2011, 2018)],
        "test_2019_2026": frame.loc[frame.entry_date.dt.year >= 2019],
    }


def threshold_rules(frame: pd.DataFrame) -> pd.DataFrame:
    excluded = {
        "net_return", "gross_return", "pnl", "equity_after", "entry_price",
        "exit_price", "bars_held", "mfe", "mfe_1w", "mfe_2w", "mfe_3w",
        "mfe_4w", "mfe_5w", "signal_range", "signal_close",
    }
    numeric = [
        column for column in frame.select_dtypes(include="number").columns
        if column not in excluded
    ]
    splits = _split(frame)
    train = splits["train_1993_2010"]
    records = []
    quantiles = np.arange(0.05, 1.0, 0.05)
    for column in numeric:
        values = train[column].dropna()
        if values.nunique() < 5:
            continue
        for quantile in quantiles:
            threshold = float(values.quantile(quantile))
            for direction in ("le", "ge"):
                record = {"feature": column, "direction": direction, "threshold": threshold}
                for split_name, sample in splits.items():
                    selected = sample.loc[
                        sample[column].le(threshold) if direction == "le"
                        else sample[column].ge(threshold)
                    ]
                    for key, value in metrics(selected).items():
                        record[f"{split_name}_{key}"] = value
                records.append(record)
    return pd.DataFrame(records)


def top_n_rules(frame: pd.DataFrame) -> pd.DataFrame:
    rank_features = [column for column in frame if column.startswith("xrank_")]
    records = []
    splits = _split(frame)
    for feature in rank_features:
        for direction in ("low", "high"):
            for top_n in (1, 2, 3, 5, 10):
                selected_all = frame.sort_values(
                    ["entry_date", feature, "ticker"],
                    ascending=[True, direction == "low", True],
                    na_position="last",
                ).groupby("entry_date", sort=False).head(top_n)
                record = {"feature": feature, "direction": direction, "top_n": top_n}
                selected_splits = _split(selected_all)
                for split_name in splits:
                    for key, value in metrics(selected_splits[split_name]).items():
                        record[f"{split_name}_{key}"] = value
                records.append(record)
    return pd.DataFrame(records)


def conjunction_rules(frame: pd.DataFrame, univariate: pd.DataFrame) -> pd.DataFrame:
    # Pair only train-promising, reasonably broad univariate filters. This keeps
    # the search auditable and greatly reduces multiple-testing pressure.
    candidates = univariate.loc[
        (univariate.train_1993_2010_n >= 150)
        & (univariate.train_1993_2010_win_rate >= 0.90)
    ].sort_values(
        ["train_1993_2010_win_rate", "train_1993_2010_profit_factor"], ascending=False
    ).drop_duplicates("feature").head(20)
    definitions = candidates[["feature", "direction", "threshold"]].to_dict("records")
    splits = _split(frame)
    records = []
    for i, first in enumerate(definitions):
        for second in definitions[i + 1:]:
            if first["feature"] == second["feature"]:
                continue
            record = {"rule_1": first, "rule_2": second}
            for split_name, sample in splits.items():
                mask = pd.Series(True, index=sample.index)
                for rule in (first, second):
                    series = sample[rule["feature"]]
                    mask &= series.le(rule["threshold"]) if rule["direction"] == "le" else series.ge(rule["threshold"])
                for key, value in metrics(sample.loc[mask]).items():
                    record[f"{split_name}_{key}"] = value
            records.append(record)
    result = pd.DataFrame(records)
    if not result.empty:
        result["rule_1"] = result.rule_1.map(json.dumps)
        result["rule_2"] = result.rule_2.map(json.dumps)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    frame = enrich(args.run_id, args.refresh)
    baseline = {name: metrics(sample) for name, sample in _split(frame).items()}
    uni = threshold_rules(frame)
    top = top_n_rules(frame)
    pairs = conjunction_rules(frame, uni)
    prefix = OUTPUT / args.run_id
    uni.to_csv(f"{prefix}-univariate.csv", index=False)
    top.to_csv(f"{prefix}-top-n.csv", index=False)
    pairs.to_csv(f"{prefix}-pairs.csv", index=False)
    print(json.dumps({"baseline": baseline, "feature_rows": len(frame)}, indent=2))
    print("\nBest validation precision (univariate):")
    print(uni.loc[uni.validation_2011_2018_n >= 30].sort_values(
        ["validation_2011_2018_win_rate", "test_2019_2026_win_rate", "validation_2011_2018_n"],
        ascending=False,
    ).head(15).to_string(index=False))
    print("\nRules with 100% validation and their untouched test result:")
    perfect = pd.concat([
        uni.assign(kind="threshold"), top.assign(kind="top_n"), pairs.assign(kind="pair")
    ], ignore_index=True, sort=False)
    perfect = perfect.loc[
        (perfect.validation_2011_2018_n >= 10)
        & (perfect.validation_2011_2018_win_rate == 1.0)
    ].sort_values(["test_2019_2026_win_rate", "validation_2011_2018_n"], ascending=False)
    print(perfect.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
