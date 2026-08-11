"""Optimizer (per-asset grid search) backtest mode."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from src import charts, logger, optimizer
from src.utils import fmt_num, fmt_pct
from ui.data_source import _resolve_norgate_pending, collect_multi_asset_data
from ui.params_form import configuration_form
from ui.run_logging import save_to_log

MAX_COMBOS = 4000


@st.cache_data(show_spinner="Executando e armazenando a otimização…", max_entries=8)
def _cached_grid(data_by_ticker, cfg, ranges, train_frac, min_trades, workers):
    """Reuse byte-identical optimization requests within the Streamlit session."""
    return optimizer.run_grid(
        data_by_ticker, cfg, ranges, train_frac=train_frac,
        min_trades=min_trades, workers=workers,
    )


@st.cache_data(show_spinner="Executando e armazenando o walk-forward…", max_entries=8)
def _cached_walk_forward(data_by_ticker, cfg, ranges, objective, folds, train_frac, min_trades):
    return optimizer.run_walk_forward(
        data_by_ticker, cfg, ranges, objective=objective, n_splits=folds,
        initial_train_frac=train_frac, min_trades=min_trades,
    )


def build_param_ranges() -> dict:
    """UI to pick which parameters to sweep and their min/max/step ranges."""
    st.subheader("Parâmetros para otimizar")
    labels = {k: v[0] for k, v in optimizer.PARAM_SPECS.items()}
    chosen = st.multiselect(
        "Variables to sweep (grid = all combinations)",
        options=list(optimizer.PARAM_SPECS.keys()),
        default=["rsi_entry_threshold", "max_bars"],
        format_func=lambda k: labels[k])
    ranges = {}
    for key in chosen:
        label, is_int, dmin, dmax, dstep = optimizer.PARAM_SPECS[key]
        st.markdown(f"**{label}**")
        c1, c2, c3 = st.columns(3)
        step_fmt = "%d" if is_int else "%.4f"
        lo = c1.number_input(f"{label} — min", value=float(dmin), key=f"opt_{key}_min", format=step_fmt)
        hi = c2.number_input(f"{label} — max", value=float(dmax), key=f"opt_{key}_max", format=step_fmt)
        step = c3.number_input(f"{label} — step", value=float(dstep), min_value=0.0001,
                               key=f"opt_{key}_step", format=step_fmt)
        vals = optimizer.param_values(lo, hi, step, is_int)
        ranges[key] = vals
        st.caption(f"{len(vals)} value(s): {vals if len(vals) <= 12 else str(vals[:12]) + ' …'}")
    return ranges


def render_optimizer_results(results: pd.DataFrame, ranges: dict, objective: str,
                             split_dt, min_trades: int) -> None:
    obj_label = optimizer.OBJECTIVES[objective]
    train_col = f"train_{objective}"
    valid = results[results["valid"]].copy()
    if valid.empty:
        st.error(f"No parameter combination produced at least {min_trades} in-sample trades. "
                 "Widen the ranges, lower 'min trades', or extend the date range.")
        return None

    ranked = valid.sort_values(train_col, ascending=False).reset_index(drop=True)
    best = ranked.iloc[0]
    param_keys = list(ranges.keys())

    st.subheader("🏆 Best parameters (by in-sample objective)")
    st.success(" · ".join(f"**{optimizer.PARAM_SPECS[k][0]}** = "
                          f"{int(best[k]) if optimizer.PARAM_SPECS[k][1] else best[k]:g}"
                          for k in param_keys) or "(no parameters swept)")
    m = st.columns(4)
    test_col = f"test_{objective}"
    m[0].metric(f"In-sample {obj_label}", fmt_num(best[train_col], 3))
    m[1].metric(f"Out-of-sample {obj_label}", fmt_num(best[test_col], 3))
    m[2].metric("In-sample trades", f"{int(best['train_trades'])}")
    m[3].metric("Out-of-sample trades", f"{int(best['test_trades'])}")
    if split_dt is not None:
        st.caption(f"Train/test split at **{pd.Timestamp(split_dt).date()}** "
                   f"(trades with entry on/before = in-sample). A big gap between in-sample and "
                   f"out-of-sample {obj_label} is a sign of overfitting.")

    # Heatmap when exactly two parameters were swept.
    if len(param_keys) == 2:
        st.plotly_chart(
            charts.optimizer_heatmap(ranked, param_keys[0], param_keys[1], train_col,
                                     f"In-sample {obj_label}"),
            use_container_width=True)

    # Results table.
    st.subheader("📋 All combinations")
    show_cols = param_keys + [
        "train_trades", train_col, "train_profit_factor", "train_win_rate",
        "test_trades", test_col, "test_profit_factor",
    ]
    show_cols = [c for c in show_cols if c in ranked.columns]
    disp = ranked[show_cols].copy()
    rename = {f"train_{objective}": f"IS {obj_label}", f"test_{objective}": f"OOS {obj_label}",
              "train_trades": "IS trades", "test_trades": "OOS trades",
              "train_profit_factor": "IS profit factor", "test_profit_factor": "OOS profit factor",
              "train_win_rate": "IS win rate"}
    for k in param_keys:
        rename[k] = optimizer.PARAM_SPECS[k][0]
    for col in ["train_profit_factor", "test_profit_factor"]:
        if col in disp:
            disp[col] = disp[col].map(lambda v: "∞" if v == float("inf") else fmt_num(v))
    if "train_win_rate" in disp:
        disp["train_win_rate"] = disp["train_win_rate"].map(fmt_pct)
    for col in [train_col, test_col]:
        disp[col] = disp[col].map(lambda v: fmt_num(v, 3))
    disp = disp.rename(columns=rename)
    st.dataframe(disp, use_container_width=True, hide_index=True)

    st.download_button("Baixar resultados da otimização (CSV)",
                       data=ranked.to_csv(index=False).encode("utf-8"),
                       file_name="optimization_results.csv", mime="text/csv", key="opt_csv")
    return ranked


def run_optimizer_mode(note: str = "", data_src: dict | None = None):
    data_box = st.container()
    cfg, _pconf, _submitted = configuration_form("optimizer", with_run=False)

    with data_box:
        st.subheader("📥 Dados")
        pending = collect_multi_asset_data(cfg, "Tickers in the optimization universe", data_src)
    if pending is None:
        return
    is_pending = isinstance(pending, dict) and pending.get("_pending")
    data_by_ticker = None if is_pending else pending
    n_assets = len(pending["symbols"]) if is_pending else len(data_by_ticker)

    st.subheader("Configuração da otimização")
    ranges = build_param_ranges()
    if not ranges:
        st.info("Selecione ao menos um parâmetro para variar.")
        return

    c1, c2, c3 = st.columns(3)
    obj_key = c1.selectbox("Objetivo (maximizar)", list(optimizer.OBJECTIVES.keys()),
                           format_func=lambda k: optimizer.OBJECTIVES[k], index=0)
    train_frac = c2.slider("Fração in-sample (treino)", min_value=0.3, max_value=0.9,
                           value=0.7, step=0.05)
    min_trades = c3.number_input("Mínimo de operações in-sample", min_value=1,
                                 value=10, step=1)
    validation = st.radio(
        "Validação", ["In-sample / out-of-sample", "Walk-forward"], horizontal=True,
        help="Walk-forward seleciona parâmetros em janelas expansivas e avalia somente a janela seguinte.",
    )
    c4, c5 = st.columns(2)
    workers = c4.number_input("Execuções paralelas", min_value=1, max_value=16, value=1, step=1)
    folds = c5.number_input("Janelas walk-forward", min_value=2, max_value=10, value=3, step=1,
                            disabled=not validation.startswith("Walk"))
    use_cache = st.checkbox(
        "Reutilizar resultados de uma execução idêntica", value=True,
        help="O cache considera dados, configuração, faixas e método de validação.",
    )

    n_combos = 1
    for vals in ranges.values():
        n_combos *= len(vals)
    n_runs = n_combos * n_assets
    st.caption(f"**{n_combos}** parameter combinations × **{n_assets}** assets "
               f"= **{n_runs:,}** backtests · objective: **{optimizer.OBJECTIVES[obj_key]}** · "
               f"train **{train_frac:.0%}** / test **{1 - train_frac:.0%}**.")
    if n_combos > MAX_COMBOS:
        st.error(f"{n_combos} combinations exceeds the cap of {MAX_COMBOS}. Reduce ranges or step count.")
        return

    if not st.button("Executar otimização", type="primary"):
        return

    if is_pending:
        resolved = _resolve_norgate_pending(pending, cfg)
        data_by_ticker = resolved[0] if resolved is not None else None
        if data_by_ticker is None:
            return

    bar = st.progress(0.0, text="Executando otimização…")
    if validation.startswith("Walk"):
        if use_cache:
            walk = _cached_walk_forward(
                data_by_ticker, cfg, ranges, obj_key, int(folds),
                float(train_frac), int(min_trades),
            )
        else:
            walk = optimizer.run_walk_forward(
                data_by_ticker, cfg, ranges, objective=obj_key, n_splits=int(folds),
                initial_train_frac=float(train_frac), min_trades=int(min_trades),
                progress=lambda p: bar.progress(p, text="Executando walk-forward…"),
            )
        bar.empty()
        st.subheader("Resultados walk-forward")
        if walk.empty:
            st.warning("Não há dados suficientes para montar as janelas.")
        else:
            st.dataframe(walk, use_container_width=True, hide_index=True)
            st.download_button("Baixar resultados walk-forward (CSV)",
                               walk.to_csv(index=False).encode("utf-8"),
                               file_name="walk_forward_results.csv", mime="text/csv")
        return
    if use_cache:
        results, split_dt = _cached_grid(
            data_by_ticker, cfg, ranges, float(train_frac), int(min_trades), int(workers)
        )
    else:
        results, split_dt = optimizer.run_grid(
            data_by_ticker, cfg, ranges, train_frac=float(train_frac),
            min_trades=int(min_trades), workers=int(workers),
            progress=lambda p: bar.progress(p, text="Executando grade…"))
    bar.empty()
    ranked = render_optimizer_results(results, ranges, obj_key, split_dt, int(min_trades))

    if ranked is not None and not ranked.empty:
        param_keys = list(ranges.keys())
        best = ranked.iloc[0]
        best_params = {k: (int(best[k]) if optimizer.PARAM_SPECS[k][1] else float(best[k]))
                       for k in param_keys}
        starts = [d.index.min() for d in data_by_ticker.values()]
        ends = [d.index.max() for d in data_by_ticker.values()]
        save_to_log(
            "Optimizer",
            summary={"note": note, "tickers": ", ".join(sorted(data_by_ticker.keys())),
                     "n_assets": len(data_by_ticker), "n_combos": len(results),
                     "objective": optimizer.OBJECTIVES[obj_key],
                     "start": str(min(starts).date()), "end": str(max(ends).date()),
                     "best_params": json.dumps(best_params),
                     "best_is": float(best[f"train_{obj_key}"]),
                     "best_oos": float(best[f"test_{obj_key}"]),
                     "best_is_trades": int(best["train_trades"]),
                     "train_frac": float(train_frac)},
            tables={"optimization_results": ranked},
            full={"meta": {"tickers": sorted(data_by_ticker.keys()),
                           "n_assets": len(data_by_ticker), "n_combos": len(results),
                           "objective": obj_key, "train_frac": float(train_frac),
                           "min_trades": int(min_trades),
                           "split_date": str(split_dt.date()) if split_dt is not None else None,
                           "ranges": {k: list(map(float, v)) for k, v in ranges.items()}},
                  "config": logger.config_dict(cfg), "metrics": {"best_params": best_params}})
