from __future__ import annotations

import os
from dataclasses import replace
from threading import Lock
from uuid import uuid4

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from api.schemas import BacktestRequest, HealthResponse, OptimizationRequest, RunSummary, ScreeningRequest
from src.backtest_engine import BacktestEngine
from src.indicators import rsi
from src.optimizer import run_grid, run_walk_forward
from src.performance_metrics import compute_metrics
from src.portfolio_engine import PortfolioEngine
from src.types import CostConfig, ExitConfig, PortfolioConfig, SizingConfig, StrategyConfig

app = FastAPI(
    title="RSI2 Research API",
    summary="Contratos versionados para backtests, otimização e pesquisa quantitativa.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
origins = [value.strip() for value in os.getenv("RSI2_CORS_ORIGINS", "http://localhost:3000").split(",") if value.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

RUNS: dict[str, RunSummary] = {}
RUNS_LOCK = Lock()


def _frame(series) -> pd.DataFrame:
    rows = [c.model_dump() for c in series.candles]
    frame = pd.DataFrame(rows).set_index("date").sort_index()
    return frame.dropna(axis=1, how="all")


def _config(request: BacktestRequest, ticker: str = "") -> StrategyConfig:
    cfg = request.strategy
    return StrategyConfig(
        ticker=ticker,
        rsi_period=cfg.rsi_period,
        rsi_entry_threshold=cfg.rsi_entry,
        initial_capital=cfg.initial_capital,
        exits=ExitConfig(rsi_exit_threshold=cfg.rsi_exit, max_bars=cfg.max_bars),
        costs=CostConfig(commission_fixed=cfg.commission_fixed, commission_pct=cfg.commission_pct, slippage_bps=cfg.slippage_bps),
        sizing=SizingConfig(),
    )


def _json_number(value) -> float:
    number = float(value)
    return number if pd.notna(number) and abs(number) != float("inf") else 0.0


def _execute(run_id: str, request: BacktestRequest) -> None:
    with RUNS_LOCK:
        RUNS[run_id].status = "running"
    try:
        frames = {asset.ticker.upper(): _frame(asset) for asset in request.assets}
        cfg = _config(request)
        if request.mode == "portfolio":
            portfolio = PortfolioConfig(initial_capital=cfg.initial_capital, pct_per_trade=request.pct_per_trade, max_positions=request.max_positions)
            result = PortfolioEngine(frames, cfg, portfolio).run()
        else:
            asset = request.assets[0]
            result = BacktestEngine(frames[asset.ticker.upper()], replace(cfg, ticker=asset.ticker.upper())).run()
        metrics = compute_metrics(result.equity_curve, result.trades, cfg.initial_capital, len(result.equity_curve))
        equity = [{"date": str(index), "value": _json_number(value)} for index, value in result.equity_curve.items()]
        with RUNS_LOCK:
            RUNS[run_id] = RunSummary(id=run_id, name=request.name, mode=request.mode, status="completed", metrics={k: _json_number(v) for k, v in metrics.items()}, warnings=result.warnings, trade_count=len(result.trades), equity=equity)
    except Exception as exc:  # job boundary: expose a safe, inspectable failure state
        with RUNS_LOCK:
            current = RUNS[run_id]
            current.status = "failed"
            current.error = str(exc)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse()


@app.post("/v1/backtests", response_model=RunSummary, status_code=status.HTTP_202_ACCEPTED, tags=["backtests"])
def create_backtest(request: BacktestRequest, tasks: BackgroundTasks) -> RunSummary:
    run_id = f"run_{uuid4().hex[:12]}"
    run = RunSummary(id=run_id, name=request.name, mode=request.mode, status="queued")
    with RUNS_LOCK:
        RUNS[run_id] = run
    tasks.add_task(_execute, run_id, request)
    return run


@app.post("/v1/backtests/portfolio", response_model=RunSummary, status_code=status.HTTP_202_ACCEPTED, tags=["backtests"])
def create_portfolio_backtest(request: BacktestRequest, tasks: BackgroundTasks) -> RunSummary:
    request.mode = "portfolio"
    return create_backtest(request, tasks)


@app.post("/v1/backtests/per-asset", response_model=RunSummary, status_code=status.HTTP_202_ACCEPTED, tags=["backtests"])
def create_asset_backtest(request: BacktestRequest, tasks: BackgroundTasks) -> RunSummary:
    request.mode = "per_asset"
    return create_backtest(request, tasks)


@app.get("/v1/runs", response_model=list[RunSummary], tags=["runs"])
def list_runs() -> list[RunSummary]:
    with RUNS_LOCK:
        return sorted(RUNS.values(), key=lambda run: run.created_at, reverse=True)


@app.get("/v1/runs/{run_id}", response_model=RunSummary, tags=["runs"])
def get_run(run_id: str) -> RunSummary:
    with RUNS_LOCK:
        run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Execução não encontrada")
    return run


@app.delete("/v1/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["runs"])
def delete_run(run_id: str) -> None:
    with RUNS_LOCK:
        if RUNS.pop(run_id, None) is None:
            raise HTTPException(status_code=404, detail="Execução não encontrada")


@app.post("/v1/screenings", tags=["research"])
def screening(request: ScreeningRequest) -> dict:
    matches = []
    for asset in request.assets:
        frame = _frame(asset)
        value = rsi(frame["close"], 2).iloc[-1]
        close = float(frame["close"].iloc[-1])
        if pd.notna(value) and float(value) <= request.rsi_max and close >= request.min_price:
            matches.append({"ticker": asset.ticker.upper(), "close": close, "rsi_2": float(value)})
    return {"as_of": max(str(asset.candles[-1].date) for asset in request.assets), "count": len(matches), "results": sorted(matches, key=lambda row: row["rsi_2"])}


@app.get("/v1/fundamentals/{ticker}", tags=["research"])
def fundamentals(ticker: str) -> dict:
    return {"ticker": ticker.upper(), "status": "source_required", "message": "Configure o provedor fundamentalista no adaptador de dados."}


@app.post("/v1/optimizations", tags=["research"])
def optimizations(request: OptimizationRequest) -> dict:
    frames = {asset.ticker.upper(): _frame(asset) for asset in request.assets}
    stub = BacktestRequest(assets=request.assets, strategy=request.strategy)
    cfg = _config(stub)
    if request.validation == "walk_forward":
        result = run_walk_forward(frames, cfg, request.parameter_ranges, objective=request.objective, n_splits=request.splits, min_trades=request.min_trades)
        split_date = None
    else:
        result, split_date = run_grid(frames, cfg, request.parameter_ranges, min_trades=request.min_trades)
    clean = result.replace([float("inf"), float("-inf")], None).where(pd.notna(result), None)
    return {"validation": request.validation, "objective": request.objective, "split_date": str(split_date) if split_date else None, "results": clean.to_dict(orient="records")}
