"""Grid-search parameter optimizer for the per-asset (pooled-trades) backtest.

For every parameter combination the strategy is run independently in the
in-sample and out-of-sample windows.  The test run starts with fresh capital but
retains the earlier rows solely as causal indicator warm-up; an eligibility mask
prevents any pre-test entry.  Consequently test P&L is never contaminated by
capital accumulated in training.
"""
from __future__ import annotations

import copy
import itertools
import math
from concurrent.futures import ThreadPoolExecutor
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
    return [dict(zip(keys, combo, strict=True))
            for combo in itertools.product(*(param_ranges[k] for k in keys))]


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


def _window_trades(
    data_by_ticker: Dict[str, pd.DataFrame],
    cfg: StrategyConfig,
    start_exclusive=None,
    end_inclusive=None,
) -> pd.DataFrame:
    """Run one independent window, preserving prior rows as indicator warm-up.

    ``_member`` is the engine's point-in-time entry eligibility column.  Combining
    it with the requested window means warm-up rows can influence only causal
    indicators, never entries. Each engine starts from ``cfg.initial_capital``.
    """
    from dataclasses import replace

    frames = []
    for ticker, data in data_by_ticker.items():
        d = data.sort_index()
        if end_inclusive is not None:
            d = d.loc[d.index <= end_inclusive]
        if d.empty:
            continue

        eligible = pd.Series(True, index=d.index, dtype=bool)
        if start_exclusive is not None:
            eligible &= d.index > start_exclusive
        if "_member" in d.columns:
            eligible &= d["_member"].fillna(False).astype(bool)
        d = d.copy()
        d["_member"] = eligible

        res = BacktestEngine(d, replace(cfg, ticker=ticker)).run()
        if not res.trades.empty:
            frames.append(res.trades)

    if frames:
        return pd.concat(frames, ignore_index=True)
    return pd.DataFrame(columns=["entry_date", "net_return", "pnl", "bars_held"])


def _evaluate_combo(
    data_by_ticker: Dict[str, pd.DataFrame],
    base_cfg: StrategyConfig,
    combo: Dict,
    split_dt,
    end_dt=None,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Evaluate a combo with genuinely independent train and test executions."""
    cfg = apply_params(base_cfg, combo)
    train = _window_trades(data_by_ticker, cfg, end_inclusive=split_dt)
    test = _window_trades(
        data_by_ticker, cfg, start_exclusive=split_dt, end_inclusive=end_dt
    )
    return _trade_metrics(train), _trade_metrics(test)


def run_grid(
    data_by_ticker: Dict[str, pd.DataFrame],
    base_cfg: StrategyConfig,
    param_ranges: Dict[str, List],
    train_frac: float = 0.70,
    min_trades: int = 10,
    progress: Optional[Callable[[float], None]] = None,
    workers: int = 1,
) -> Tuple[pd.DataFrame, object]:
    """Run the full grid. Returns (results_df, split_date).

    Each row holds the swept parameter values plus ``train_*`` and ``test_*``
    trade metrics, and a ``valid`` flag (train trade count >= ``min_trades``).
    """
    combos = generate_grid(param_ranges)
    split_dt = _split_date(data_by_ticker, train_frac)
    rows: List[Dict] = []

    def evaluate(combo):
        return (_evaluate_combo(data_by_ticker, base_cfg, combo, split_dt)
                if split_dt is not None
                else (_trade_metrics(pd.DataFrame()), _trade_metrics(pd.DataFrame())))

    executor = ThreadPoolExecutor(max_workers=int(workers)) if workers and workers > 1 else None
    evaluated = executor.map(evaluate, combos) if executor else map(evaluate, combos)
    try:
        for j, (combo, metrics_pair) in enumerate(zip(combos, evaluated, strict=True)):
            tr_m, te_m = metrics_pair
            row = dict(combo)
            for key, val in tr_m.items():
                row[f"train_{key}"] = val
            for key, val in te_m.items():
                row[f"test_{key}"] = val
            row["valid"] = tr_m["trades"] >= min_trades
            rows.append(row)

            if progress:
                progress((j + 1) / len(combos))
    finally:
        if executor:
            executor.shutdown(wait=True)

    return pd.DataFrame(rows), split_dt


def run_walk_forward(
    data_by_ticker: Dict[str, pd.DataFrame],
    base_cfg: StrategyConfig,
    param_ranges: Dict[str, List],
    objective: str = "sharpe",
    n_splits: int = 3,
    initial_train_frac: float = 0.50,
    min_trades: int = 10,
    progress: Optional[Callable[[float], None]] = None,
) -> pd.DataFrame:
    """Expanding-window walk-forward optimization.

    For each fold, all combinations are scored only through ``train_end``; the
    best valid combination is then reported on the immediately following test
    window. Returns one row per fold and does not change :func:`run_grid`'s API.
    """
    if objective not in OBJECTIVES:
        raise ValueError(f"Unknown objective: {objective}")
    if n_splits < 1:
        raise ValueError("n_splits must be at least 1")
    if not 0 < initial_train_frac < 1:
        raise ValueError("initial_train_frac must be between 0 and 1")

    union = sorted(set().union(*[d.index for d in data_by_ticker.values()]))
    if len(union) < 3:
        return pd.DataFrame()
    first_test = max(1, min(len(union) - 1, int(round(len(union) * initial_train_frac))))
    test_indices = np.array_split(np.arange(first_test, len(union)), n_splits)
    test_indices = [idx for idx in test_indices if len(idx)]
    combos = generate_grid(param_ranges)
    rows: List[Dict] = []
    total = max(1, len(test_indices) * len(combos))
    done = 0

    for fold, indices in enumerate(test_indices, start=1):
        train_end = union[int(indices[0]) - 1]
        test_end = union[int(indices[-1])]
        candidates = []
        for combo in combos:
            train_m, test_m = _evaluate_combo(
                data_by_ticker, base_cfg, combo, train_end, test_end
            )
            candidates.append((combo, train_m, test_m))
            done += 1
            if progress:
                progress(done / total)

        valid = [c for c in candidates if c[1]["trades"] >= min_trades]
        pool = valid or candidates
        best_combo, train_m, test_m = max(
            pool,
            key=lambda c: float(c[1].get(objective, float("-inf"))),
        )
        row = {
            "fold": fold,
            "train_end": train_end,
            "test_start": union[int(indices[0])],
            "test_end": test_end,
            **best_combo,
            **{f"train_{k}": v for k, v in train_m.items()},
            **{f"test_{k}": v for k, v in test_m.items()},
            "valid": train_m["trades"] >= min_trades,
        }
        rows.append(row)

    return pd.DataFrame(rows)
