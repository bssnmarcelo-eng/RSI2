from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .candidates import CANDIDATES, get_candidate
from .config import LabConfig
from .costs import order_cost
from .data import price_panels
from .metrics import performance_metrics, rolling_scorecard
from .portfolio import combine_strategies
from .strategies import strategy_signals


@dataclass
class BacktestResult:
    equity: pd.Series
    benchmark: pd.Series
    target_weights: pd.DataFrame
    executed_weights: pd.DataFrame
    strategy_returns: pd.DataFrame
    strategy_budgets: pd.DataFrame
    strategy_equity: pd.DataFrame
    strategy_metrics: pd.DataFrame
    regime: pd.DataFrame
    costs: pd.Series
    metrics: dict[str, float]
    benchmark_metrics: dict[str, float]
    scorecard: pd.DataFrame
    candidate_comparison: pd.DataFrame


def _simulate(
    opens: pd.DataFrame, targets: pd.DataFrame, config: LabConfig
) -> tuple[pd.Series, pd.DataFrame, pd.Series]:
    dates = opens.index
    executed = targets.shift(1).reindex(dates).fillna(0.0)
    execution_matrix = executed.reindex(columns=opens.columns, fill_value=0.0)
    values = pd.Series(index=dates, dtype=float)
    costs = pd.Series(0.0, index=dates)
    capital = config.initial_capital
    previous_weights = np.zeros(len(opens.columns), dtype=float)
    previous_open: np.ndarray | None = None

    for date in dates:
        prices = opens.loc[date].to_numpy(dtype=float)
        if previous_open is not None:
            with np.errstate(divide="ignore", invalid="ignore"):
                returns = prices / previous_open - 1.0
            returns = np.nan_to_num(returns, nan=0.0, posinf=0.0, neginf=0.0)
            capital *= 1.0 + float(np.dot(previous_weights, returns))
            short_exposure = float(np.abs(np.minimum(previous_weights, 0.0)).sum())
            borrow = capital * short_exposure * config.costs.short_borrow_rate / 252.0
            capital -= borrow
            costs.loc[date] += borrow

        desired = execution_matrix.loc[date].to_numpy(dtype=float)
        desired = np.where(np.isfinite(prices), desired, 0.0)
        delta = desired - previous_weights
        traded = (prices > 0) & (np.abs(delta) > 1e-10)
        shares = np.zeros_like(delta)
        shares[traded] = np.abs(delta[traded]) * capital / prices[traded]
        trade_value = shares * np.nan_to_num(prices, nan=0.0)
        commission = np.maximum(
            config.costs.minimum_per_order, shares * config.costs.commission_per_share
        )
        commission = np.minimum(commission, trade_value * config.costs.maximum_fraction)
        variable = trade_value * (
            config.costs.third_party_bps + config.costs.slippage_bps
        ) / 10_000.0
        trade_cost = float((commission[traded] + variable[traded]).sum())
        capital -= trade_cost
        costs.loc[date] += trade_cost
        values.loc[date] = capital
        previous_weights = desired
        previous_open = prices
    return values, executed, costs


def _turnover_and_changes(weights: pd.DataFrame) -> tuple[float, int]:
    changes = weights.diff().abs().sum(axis=1).fillna(0.0)
    years = max((weights.index[-1] - weights.index[0]).days / 365.25, 1 / 252)
    return float(changes.sum() / years), int(changes.gt(1e-8).sum())


def run_backtest(
    frames: dict[str, pd.DataFrame], config: LabConfig, indicators: pd.DataFrame | None = None
) -> BacktestResult:
    if config.benchmark not in frames:
        raise ValueError(f"Benchmark {config.benchmark} não foi carregado")
    opens, closes = price_panels(frames)
    common_start = frames[config.benchmark].index.min()
    opens = opens.loc[common_start:]
    closes = closes.reindex(opens.index)
    signals, regime = strategy_signals(closes, indicators)
    selected_profile = get_candidate(config.candidate)
    targets, strategy_returns, budgets = combine_strategies(
        signals, closes, config.risk, selected_profile.weights
    )
    equity, executed, costs = _simulate(opens, targets, config)

    strategy_equity: dict[str, pd.Series] = {}
    metric_rows: list[dict[str, float | str]] = []
    for name, weights in signals.items():
        sleeve_equity, sleeve_executed, sleeve_costs = _simulate(opens, weights, config)
        strategy_equity[name] = sleeve_equity
        sleeve_metrics = performance_metrics(sleeve_equity)
        turnover, changes = _turnover_and_changes(sleeve_executed)
        metric_rows.append(
            {
                "strategy": name,
                **sleeve_metrics,
                "annual_turnover": turnover,
                "rebalance_days": changes,
                "costs_usd": float(sleeve_costs.sum()),
                "short_days": int(sleeve_executed.lt(0).any(axis=1).sum()),
            }
        )
    strategy_equity_frame = pd.DataFrame(strategy_equity)
    strategy_returns = strategy_equity_frame.pct_change(fill_method=None).fillna(0.0)

    benchmark_returns = opens[config.benchmark].pct_change(fill_method=None).fillna(0.0)
    initial_benchmark_cost = order_cost(
        config.initial_capital / opens[config.benchmark].iloc[0],
        opens[config.benchmark].iloc[0],
        config.costs,
    )
    benchmark = (config.initial_capital - initial_benchmark_cost) * (1.0 + benchmark_returns).cumprod()
    benchmark_metrics = performance_metrics(benchmark)

    candidate_rows: list[dict[str, float | str | bool]] = []
    for key, profile in CANDIDATES.items():
        if key == config.candidate:
            candidate_equity, candidate_executed, candidate_costs = equity, executed, costs
        else:
            candidate_targets, _, _ = combine_strategies(
                signals, closes, config.risk, profile.weights
            )
            candidate_equity, candidate_executed, candidate_costs = _simulate(
                opens, candidate_targets, config
            )
        candidate_metrics = performance_metrics(candidate_equity, benchmark)
        turnover, changes = _turnover_and_changes(candidate_executed)
        candidate_rows.append(
            {
                "candidate_key": key,
                "candidate": profile.name,
                "objective": profile.objective,
                **candidate_metrics,
                "annual_turnover": turnover,
                "rebalance_days": changes,
                "costs_usd": float(candidate_costs.sum()),
                "lower_vol_than_spy": candidate_metrics["annual_volatility"] < benchmark_metrics["annual_volatility"],
                "lower_drawdown_than_spy": candidate_metrics["max_drawdown"] > benchmark_metrics["max_drawdown"],
            }
        )
    return BacktestResult(
        equity=equity,
        benchmark=benchmark,
        target_weights=targets,
        executed_weights=executed,
        strategy_returns=strategy_returns,
        strategy_budgets=budgets,
        strategy_equity=strategy_equity_frame,
        strategy_metrics=pd.DataFrame(metric_rows).set_index("strategy"),
        regime=regime,
        costs=costs,
        metrics=performance_metrics(equity, benchmark),
        benchmark_metrics=benchmark_metrics,
        scorecard=rolling_scorecard(equity, benchmark),
        candidate_comparison=pd.DataFrame(candidate_rows).set_index("candidate_key"),
    )
