"""Out-of-sample study of causal trade-ranking models.

Models are fitted on 1993-2010, selected on 2011-2018, and evaluated once on
2019-2026.  The executable portfolio rule takes the two highest scores at each
entry date, which yields at least 20 trades in every represented calendar year.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from analyze_trade_filters import ROOT, enrich, metrics
from scipy.optimize import minimize

OUTPUT = ROOT / ".local-run"
TRAIN_END = 2010
VALIDATION_END = 2018


def feature_families(frame: pd.DataFrame) -> dict[str, list[str]]:
    numeric = set(frame.select_dtypes(include="number").columns)

    def matching(parts: tuple[str, ...]) -> list[str]:
        return sorted(column for column in numeric if any(part in column for part in parts))

    families = {
        "technical": matching((
            "rsi_", "bollinger_", "stochastic_", "atr_", "trend_", "sma_slope_",
            "breadth_",
        )),
        "graphical": matching((
            "range_pct", "body_pct", "shadow_pct", "close_location", "bullish_candle",
            "gap_from_", "inside_bar", "range_compression_", "narrowest_range_",
            "signal_body_percentile", "signal_atr_mult",
        )),
        "momentum": matching((
            "momentum_", "drawdown_",
        )),
        "statistical": matching((
            "volatility_", "return_z_", "return_skew_", "return_kurt_",
            "autocorr_", "market_beta_", "market_correlation_", "relative_volume_",
            "volume_z_", "market_trin", "prior_",
        )),
    }
    families["combined"] = sorted(set().union(*families.values()))
    return families


class LogisticRanker:
    def __init__(self, regularization: float):
        self.regularization = regularization

    def fit(self, frame: pd.DataFrame, features: list[str]) -> "LogisticRanker":
        self.features = features
        raw = frame[features].to_numpy(dtype=float)
        self.median = np.nanmedian(raw, axis=0)
        self.median = np.where(np.isfinite(self.median), self.median, 0.0)
        raw = np.where(np.isfinite(raw), raw, self.median)
        self.center = np.median(raw, axis=0)
        self.scale = np.nanpercentile(raw, 75, axis=0) - np.nanpercentile(raw, 25, axis=0)
        self.scale = np.where(self.scale > 1e-12, self.scale, 1.0)
        x = np.clip((raw - self.center) / self.scale, -6.0, 6.0)
        x = np.column_stack([np.ones(len(x)), x])
        y = frame["net_return"].gt(0).to_numpy(dtype=float)

        def objective(beta: np.ndarray) -> tuple[float, np.ndarray]:
            scores = x @ beta
            losses = np.logaddexp(0.0, scores) - y * scores
            penalty = 0.5 * self.regularization * np.dot(beta[1:], beta[1:])
            probabilities = 1.0 / (1.0 + np.exp(-np.clip(scores, -35.0, 35.0)))
            gradient = x.T @ (probabilities - y)
            gradient[1:] += self.regularization * beta[1:]
            return float(losses.sum() + penalty), gradient

        result = minimize(
            objective,
            np.zeros(x.shape[1]),
            method="L-BFGS-B",
            jac=True,
            options={"maxiter": 2_000, "ftol": 1e-10},
        )
        if not np.all(np.isfinite(result.x)):
            raise RuntimeError(f"logistic fit failed: {result.message}")
        self.coefficients = result.x
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        raw = frame[self.features].to_numpy(dtype=float)
        raw = np.where(np.isfinite(raw), raw, self.median)
        x = np.clip((raw - self.center) / self.scale, -6.0, 6.0)
        return self.coefficients[0] + x @ self.coefficients[1:]


def top_per_date(frame: pd.DataFrame, score: np.ndarray, count: int) -> pd.DataFrame:
    ranked = frame.copy()
    ranked["selection_score"] = score
    return (
        ranked.sort_values(
            ["entry_date", "selection_score", "ticker"],
            ascending=[True, False, True],
        )
        .groupby("entry_date", sort=False)
        .head(count)
        .sort_values(["entry_date", "ticker"])
    )


def annual_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year, sample in frame.groupby(frame.entry_date.dt.year):
        row = {"year": int(year), **metrics(sample)}
        rows.append(row)
    return pd.DataFrame(rows)


def evaluate(run_id: str, refresh: bool = False) -> dict[str, object]:
    frame = enrich(run_id, refresh)
    train = frame.loc[frame.entry_date.dt.year <= TRAIN_END].copy()
    validation = frame.loc[
        frame.entry_date.dt.year.between(TRAIN_END + 1, VALIDATION_END)
    ].copy()
    test = frame.loc[frame.entry_date.dt.year > VALIDATION_END].copy()
    families = feature_families(frame)
    candidates: list[dict[str, object]] = []

    for family, features in families.items():
        for regularization in (0.1, 1.0, 10.0, 100.0):
            model = LogisticRanker(regularization).fit(train, features)
            for count in (2, 3, 4):
                validation_selected = top_per_date(
                    validation, model.predict(validation), count
                )
                yearly = annual_metrics(validation_selected)
                candidates.append({
                    "family": family,
                    "regularization": regularization,
                    "top_per_date": count,
                    **{f"validation_{key}": value for key, value in metrics(validation_selected).items()},
                    "validation_min_trades_year": int(yearly.n.min()),
                    "validation_min_win_rate_year": float(yearly.win_rate.min()),
                })

    candidate_table = pd.DataFrame(candidates)
    eligible = candidate_table.loc[candidate_table.validation_min_trades_year >= 20]
    chosen = eligible.sort_values(
        ["validation_win_rate", "validation_profit_factor", "validation_n"],
        ascending=[False, False, False],
    ).iloc[0]

    family_results: list[dict[str, object]] = []
    for family, family_candidates in candidate_table.groupby("family"):
        best = family_candidates.loc[
            family_candidates.validation_min_trades_year >= 20
        ].sort_values(
            ["validation_win_rate", "validation_profit_factor", "validation_n"],
            ascending=[False, False, False],
        ).iloc[0]
        family_model = LogisticRanker(float(best.regularization)).fit(
            pd.concat([train, validation]), families[family]
        )
        family_test = top_per_date(
            test, family_model.predict(test), int(best.top_per_date)
        )
        family_test_yearly = annual_metrics(family_test)
        family_results.append({
            "family": family,
            "regularization": float(best.regularization),
            "top_per_date": int(best.top_per_date),
            "validation_n": int(best.validation_n),
            "validation_win_rate": float(best.validation_win_rate),
            "validation_min_trades_year": int(best.validation_min_trades_year),
            "test_n": len(family_test),
            "test_win_rate": metrics(family_test)["win_rate"],
            "test_profit_factor": metrics(family_test)["profit_factor"],
            "test_min_trades_year": int(family_test_yearly.n.min()),
            "test_min_win_rate_year": float(family_test_yearly.win_rate.min()),
        })

    chosen_features = families[str(chosen.family)]
    # Architecture and regularization are frozen after validation. Refit on all
    # pre-test data before the single untouched test evaluation.
    development = frame.loc[frame.entry_date.dt.year <= VALIDATION_END]
    final_model = LogisticRanker(float(chosen.regularization)).fit(
        development, chosen_features
    )
    selected_test = top_per_date(
        test, final_model.predict(test), int(chosen.top_per_date)
    )
    validation_model = LogisticRanker(float(chosen.regularization)).fit(
        train, chosen_features
    )
    selected_validation = top_per_date(
        validation,
        validation_model.predict(validation),
        int(chosen.top_per_date),
    )
    selected_all = pd.concat([selected_validation, selected_test]).sort_values(
        ["entry_date", "ticker"]
    )
    baseline_annual = annual_metrics(frame)
    selected_annual = annual_metrics(selected_all)

    prefix = OUTPUT / run_id
    candidate_table.to_csv(f"{prefix}-model-validation.csv", index=False)
    selected_all.to_csv(f"{prefix}-selected-trades.csv", index=False)
    selected_annual.to_csv(f"{prefix}-selected-annual.csv", index=False)
    baseline_annual.to_csv(f"{prefix}-baseline-annual.csv", index=False)

    result: dict[str, object] = {
        "run_id": run_id,
        "selection_protocol": {
            "fit": "1993-2010",
            "model_selection": "2011-2018",
            "final_test": "2019-2026",
            "minimum_trades_per_year": 20,
        },
        "chosen": chosen.to_dict(),
        "baseline": {
            "development_1993_2018": metrics(development),
            "test_2019_2026": metrics(test),
        },
        "selected": {
            "validation_2011_2018": metrics(selected_validation),
            "test_2019_2026": metrics(selected_test),
            "out_of_sample_2011_2026": metrics(selected_all),
            "minimum_trades_in_any_year": int(selected_annual.n.min()),
            "minimum_win_rate_in_any_year": float(selected_annual.win_rate.min()),
        },
        "family_results": family_results,
        "feature_count": len(chosen_features),
        "features": chosen_features,
    }
    with Path(f"{prefix}-model-study.json").open("w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    print(json.dumps(evaluate(args.run_id, args.refresh), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
