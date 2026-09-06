from __future__ import annotations

from .config import CostConfig


def order_cost(shares: float, price: float, config: CostConfig) -> float:
    shares = abs(float(shares))
    trade_value = shares * float(price)
    if shares == 0 or trade_value == 0:
        return 0.0
    commission = max(config.minimum_per_order, shares * config.commission_per_share)
    commission = min(commission, trade_value * config.maximum_fraction)
    variable = trade_value * (config.third_party_bps + config.slippage_bps) / 10_000.0
    return commission + variable
