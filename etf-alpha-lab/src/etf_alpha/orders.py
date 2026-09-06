from __future__ import annotations

import math

import pandas as pd


def target_orders(
    current_positions: dict[str, float],
    target_weights: pd.Series,
    prices: pd.Series,
    net_liquidation: float,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for symbol, weight in target_weights.items():
        price = float(prices.get(symbol, float("nan")))
        if not math.isfinite(price) or price <= 0:
            continue
        current = float(current_positions.get(symbol, 0.0))
        target = math.trunc(float(weight) * net_liquidation / price)
        delta = target - current
        if delta:
            rows.append(
                {
                    "symbol": symbol,
                    "action": "BUY" if delta > 0 else "SELL",
                    "quantity": abs(int(delta)),
                    "target_shares": int(target),
                    "reference_price": price,
                    "target_weight": float(weight),
                }
            )
    return pd.DataFrame(rows)
