"""Grid-search parameter optimizer for the per-asset (pooled-trades) backtest.

For every combination of the swept parameters this runs the strategy on each
asset independently (full capital each), pools all trades, then splits the trades
by entry date into an **in-sample (train)** set and an **out-of-sample (test)**
set. Trade-level metrics are reported for both so you can tell whether a parameter
choice generalises or is just curve-fit to the training window.

Splitting the trades of a single full-period run by date is equivalent to running
train-then-test separately for these trade-level statistics (the strategy is
causal and nothing is fit *within* a run), and it is far cheaper.
"""
from __future__ import annotations

import copy
import itertools
import math
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .backtest_engine import BacktestEngine
from .types import StrategyConfig

# key -> (label, is_int, default_min, default_max, default_step)
PARAM_SPECS: Dict[str, tuple] = {
    "rsi_period": ("RSI period", True, 2, 5, 1),
    "rsi_entry_threshold": ("RSI entry threshold", False, 5.0, 20.0, 5.0),
    "rsi_exit_threshold": ("RSI exit threshold", False, 60.0, 80.0, 10.0),
    "max_bars": ("Max bars (time stop)", True, 3, 10, 1),
    "profit_target_pct": ("Profit target %", False, 3.0, 10.0, 1.0),
    "stop_loss_pct": ("Stop loss %", False, 2.0, 6.0, 1.0),
    "sma_period": ("SMA exit period", True, 3, 10, 1),
    "hammer_percentile": ("Hammer body percentile", False, 0.2, 0.5, 0.05),
}

# objective key -> friendly label (all are maximised)
OBJECTIVES: Dict[str, str] = {
    "sharpe": "Sharpe (per trade)",
    "expectancy": "Expectancy per trade",
    "profit_factor": "Profit factor",
    "win_rate": "Win rate",
    "total_pnl": "Total P&L",
}


def param_values(lo: float, hi: float, step: float, is_int: bool) -> List:
    """Inclusive list of values from ``lo`` to ``hi`` in increments of ``step``."""
    if step <= 0 or hi < lo:
        return [int(lo) if is_int else float(lo)]
    n = int(math.floor((hi - lo) / step + 1e-9)) + 1
    vals = [lo + i * step for i in range(n)]
    if is_int:
        return sorted({int(round(v)) for v in vals})
    return [round(v, 6) for v in vals]


def generate_grid(param_ranges: Dict[str, List]) -> List[Dict]:
    """Cartesian product of the per-parameter value lists."""
    if not param_ranges:
        return [{}]
    keys = list(param_ranges.keys())
    return [dict(zip(keys, combo)) for combo in itertools.product(*(param_ranges[k] for k in keys))]


def apply_params(base: StrategyConfig, combo: Dict) -> StrategyConfig:
    """Return a deep copy of ``base`` with the combo's parameters applied.

    Sweeping an exit-rule parameter automatically enables that exit rule (otherwise
    the parameter would have no effect).
    """
    cfg = copy.deepcopy(base)
    for k, v in combo.items():
        if k == "rsi_period":
            cfg.rsi_period = int(v)
        elif k == "rsi_entry_threshold":
            cfg.rsi_entry_threshold = float(v)
        elif k == "rsi_exit_threshold":
            cfg.exits.rsi_exit_threshold = float(v)
            cfg.exits.use_rsi_exit = True
        elif k == "max_bars":
            cfg.exits.max_bars = int(v)
            cfg.exits.use_max_bars = True
        elif k == "profit_target_pct":
            cfg.exits.profit_target_pct = float(v)
            cfg.exits.use_profit_target = True
        elif k == "stop_loss_pct":
            cfg.exits.stop_loss_pct = float(v)
            cfg.exits.use_stop_loss = True
        elif k == "sma_period":
            cfg.exits.sma_period = int(v)
            cfg.exits.use_sma_exit = True
        elif k == "hammer_percentile":
            cfg.patterns.hammer.percentile = float(v)
    return cfg


def _trade_metrics(trades: pd.DataFrame) -> Dict[str, float]:
    """Trade-level statistics for a set of trades (empty-safe)."""
    n = len(trades)
    if n == 0:
        return {"trades": 0, "sharpe": 0.0, "expectancy": 0.0, "profit_factor": 0.0,
                "win_rate": 0.0, "total_pnl": 0.0, "avg_holding": 0.0}
    nr = trades["net_return"]
    pnl = trades["pnl"]
    std = float(nr.std(ddof=1)) if n > 1 else 0.0
    sharpe = float(nr.mean() / std) if std > 0 else 0.0
    gross_win = float(pnl[pnl > 0].sum())
    gross_loss = float(abs(pnl[pnl < 0].sum()))
    pf = gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    return {
        "trades": n,
        "sharpe": sharpe,
        "expectancy": float(nr.mean()),
        "profit_factor": pf,
        "win_rate": float((nr > 0).mean()),
        "total_pnl": float(pnl.sum()),
        "avg_holding": float(trades["bars_held"].mean()),
    }


def _split_date(data_by_ticker: Dict[str, pd.DataFrame], train_frac: float):
    """Date at the train/test boundary (last in-sample date)."""
    union = sorted(set().union(*[d.index for d in data_by_ticker.values()]))
    if not union:
        return None
    k = max(1, min(len(union) - 1, int(round(len(union) * train_frac))))
    return union[k - 1]


def run_grid(
    data_by_ticker: Dict[str, pd.DataFrame],
    base_cfg: StrategyConfig,
    param_ranges: Dict[str, List],
    train_frac: float = 0.70,
    min_trades: int = 10,
    progress: Optional[Callable[[float], None]] = None,
) -> Tuple[pd.DataFrame, object]:
    """Run the full grid. Returns (results_df, split_date).

    Each row holds the swept parameter values plus ``train_*`` and ``test_*``
    trade metrics, and a ``valid`` flag (train trade count >= ``min_trades``).
    """
    from dataclasses import replace

    combos = generate_grid(param_ranges)
    split_dt = _split_date(data_by_ticker, train_frac)
    rows: List[Dict] = []

    for j, combo in enumerate(combos):
        cfg = apply_params(base_cfg, combo)
        frames = []
        for t, d in data_by_ticker.items():
            res = BacktestEngine(d, replace(cfg, ticker=t)).run()
            if not res.trades.empty:
                frames.append(res.trades)
        trades = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
            columns=["entry_date", "net_return", "pnl", "bars_held"])

        if split_dt is not None and not trades.empty:
            train = trades[trades["entry_date"] <= split_dt]
            test = trades[trades["entry_date"] > split_dt]
        else:
            train, test = trades, trades.iloc[0:0]

        tr_m = _trade_metrics(train)
        te_m = _trade_metrics(test)
        row = dict(combo)
        for key, val in tr_m.items():
            row[f"train_{key}"] = val
        for key, val in te_m.items():
            row[f"test_{key}"] = val
        row["valid"] = tr_m["trades"] >= min_trades
        rows.append(row)

        if progress:
            progress((j + 1) / len(combos))

    return pd.DataFrame(rows), split_dt
