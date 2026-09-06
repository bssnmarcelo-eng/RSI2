from __future__ import annotations

import pandas as pd

from .config import RiskConfig


def strategy_budgets(proxy_returns: pd.DataFrame, policy_weights: dict[str, float]) -> pd.DataFrame:
    """Transparent fixed policy weights; no full-sample portfolio optimizer."""
    names = list(proxy_returns.columns)
    strategic = pd.Series(policy_weights, dtype=float).reindex(names).fillna(0.0)
    if strategic.sum() <= 0:
        raise ValueError("O candidato precisa alocar ao menos uma estratégia")
    strategic /= strategic.sum()
    return pd.DataFrame(
        [strategic.to_numpy()] * len(proxy_returns), index=proxy_returns.index, columns=names
    )


def combine_strategies(
    signals: dict[str, pd.DataFrame], close: pd.DataFrame, risk: RiskConfig,
    policy_weights: dict[str, float],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    asset_returns = close.pct_change(fill_method=None)
    proxy = pd.DataFrame(
        {name: (weights.shift(1) * asset_returns).sum(axis=1) for name, weights in signals.items()}
    )
    budgets = strategy_budgets(proxy, policy_weights)
    target = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    for name, weights in signals.items():
        target = target.add(weights.mul(budgets[name], axis=0), fill_value=0.0)

    target = target.clip(-risk.max_symbol_weight, risk.max_symbol_weight)
    gross = target.abs().sum(axis=1)
    target = target.div((gross / risk.max_gross).clip(lower=1.0), axis=0)
    net = target.sum(axis=1).abs()
    target = target.div((net / risk.max_net).clip(lower=1.0), axis=0)
    return target.fillna(0.0), proxy, budgets
