from __future__ import annotations

import os
from dataclasses import replace
from threading import Lock
from uuid import uuid4

import pandas as pd
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from api.schemas import (
    BacktestRequest,
    HealthResponse,
    NorgateBacktestRequest,
    NorgateCatalog,
    NorgateOptimizationRequest,
    NorgateScreeningRequest,
    NorgateStatus,
    OptimizationRequest,
    RunSummary,
    ScreeningRequest,
)
from src import fundamentals as fundamental_data
from src import norgate_loader
from src.backtest_engine import BacktestEngine, build_signal_frame
from src.indicators import rsi
from src.optimizer import run_grid, run_walk_forward
from src.performance_metrics import compute_metrics
from src.portfolio_engine import PortfolioEngine
from src.types import (
    CostConfig,
    ExitConfig,
    HammerParams,
    InstrumentType,
    OptionConfig,
    OptionPricingModel,
    OptionSizingMode,
    PatternConfig,
    PortfolioConfig,
    PortfolioEntryRanking,
    SizingConfig,
    StrategyConfig,
)

app = FastAPI(
    title="RSI2 Research API",
    summary="Contratos versionados para backtests, otimização e pesquisa quantitativa.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
origins = [
    value.strip()
    for value in os.getenv(
        "RSI2_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if value.strip()
]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

RUNS: dict[str, RunSummary] = {}
RUNS_LOCK = Lock()


def _frame(series) -> pd.DataFrame:
    rows = [c.model_dump() for c in series.candles]
    frame = pd.DataFrame(rows).set_index("date").sort_index()
    return frame.dropna(axis=1, how="all")


def _config(request: BacktestRequest | NorgateBacktestRequest, ticker: str = "") -> StrategyConfig:
    cfg = request.strategy
    option_input = cfg.options
    return StrategyConfig(
        ticker=ticker,
        instrument=InstrumentType(cfg.instrument),
        options=OptionConfig(
            enabled=cfg.instrument == "synthetic_atm_call",
            pricing_model=OptionPricingModel(option_input.pricing_model),
            strike_mode=option_input.strike_mode,
            strike_interval=option_input.strike_interval,
            otm_pct=option_input.otm_pct,
            target_dte=option_input.target_dte,
            roll_dte=0,
            volatility_window=option_input.volatility_window,
            iv_multiplier=option_input.iv_multiplier,
            iv_floor=option_input.iv_floor,
            iv_cap=option_input.iv_cap,
            iv_scenario=option_input.iv_scenario,
            risk_free_mode=option_input.risk_free_mode,
            risk_free_symbol=option_input.risk_free_symbol,
            risk_free_rate=option_input.risk_free_rate,
            dividend_yield=option_input.dividend_yield,
            spread_pct=option_input.spread_pct,
            minimum_half_spread=option_input.minimum_half_spread,
            commission_per_contract=option_input.commission_per_contract,
            sizing_mode=OptionSizingMode(option_input.sizing_mode),
            premium_risk_pct=option_input.premium_risk_pct,
            binomial_steps=option_input.binomial_steps,
        ),
        rsi_period=cfg.rsi_period,
        rsi_entry_threshold=cfg.rsi_entry,
        patterns=PatternConfig(
            use_hammer=cfg.use_hammer,
            hammer=HammerParams(
                percentile=cfg.hammer_percentile,
                require_bullish_close=cfg.hammer_require_bullish_close,
                use_atr_filter=cfg.hammer_use_atr_filter,
                atr_period=cfg.hammer_atr_period,
                atr_multiple=cfg.hammer_atr_multiple,
            ),
        ),
        initial_capital=cfg.initial_capital,
        exits=ExitConfig(
            use_rsi_exit=cfg.use_rsi_exit,
            rsi_exit_threshold=cfg.rsi_exit,
            use_max_bars=cfg.use_max_bars,
            max_bars=cfg.max_bars,
            use_profit_target=cfg.use_profit_target,
            profit_target_pct=cfg.profit_target_pct,
            use_stop_loss=cfg.use_stop_loss,
            stop_loss_pct=cfg.stop_loss_pct,
            use_sma_exit=cfg.use_sma_exit,
            sma_period=cfg.sma_period,
            use_signal_low_stop=cfg.use_signal_low_stop,
            use_rsi_cum_exit=cfg.use_rsi_cum_exit,
            rsi_cum_periods=cfg.rsi_cum_periods,
            rsi_cum_threshold=cfg.rsi_cum_threshold,
        ),
        costs=CostConfig(commission_fixed=cfg.commission_fixed, commission_pct=cfg.commission_pct, slippage_bps=cfg.slippage_bps),
        sizing=SizingConfig(),
    )


def _json_number(value) -> float:
    number = float(value)
    return number if pd.notna(number) and abs(number) != float("inf") else 0.0


def _json_value(value):
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return _json_number(value)
    if isinstance(value, (int, str, bool)):
        return value
    return str(value)


def _serialize_trades(trades: pd.DataFrame, limit: int = 500) -> list[dict]:
    if trades.empty:
        return []
    return [{str(key): _json_value(value) for key, value in row.items()} for row in trades.head(limit).to_dict(orient="records")]


def _set_progress(run_id: str, value: float) -> None:
    with RUNS_LOCK:
        if run_id in RUNS:
            RUNS[run_id].progress = min(0.99, max(0.0, float(value)))


def _finish_run(run_id: str, request, result, *, source: str, data_summary: dict) -> None:
    cfg = result.config
    metrics = compute_metrics(result.equity_curve, result.trades, cfg.initial_capital, len(result.equity_curve))
    equity = [{"date": str(index), "value": _json_number(value)} for index, value in result.equity_curve.items()]
    scenario_equity = {
        label: [{"date": str(index), "value": _json_number(value)} for index, value in series.items()]
        for label, series in getattr(result, "scenario_equity", {}).items()
    }
    scenario_metrics = {
        label: {key: _json_number(value) for key, value in values.items()}
        for label, values in getattr(result, "scenario_metrics", {}).items()
    }
    with RUNS_LOCK:
        created_at = RUNS[run_id].created_at
        RUNS[run_id] = RunSummary(
            id=run_id,
            name=request.name,
            mode=request.mode,
            status="completed",
            progress=1,
            source=source,
            created_at=created_at,
            metrics={key: _json_number(value) for key, value in metrics.items()},
            warnings=result.warnings,
            trade_count=len(result.trades),
            equity=equity,
            trades=_serialize_trades(result.trades),
            data_summary=data_summary,
            scenario_metrics=scenario_metrics,
            scenario_equity=scenario_equity,
        )


def _run_frames(run_id: str, request, frames: dict[str, pd.DataFrame], progress_start: float = 0.0,
                option_frames: dict[str, pd.DataFrame] | None = None):
    cfg = _config(request)
    span = 1.0 - progress_start

    def progress(value: float) -> None:
        _set_progress(run_id, progress_start + span * float(value))

    if request.mode == "portfolio":
        portfolio = PortfolioConfig(
            initial_capital=cfg.initial_capital,
            pct_per_trade=request.pct_per_trade,
            max_positions=request.max_positions,
            max_entries_per_date=request.max_entries_per_date,
            entry_ranking=PortfolioEntryRanking(request.entry_ranking),
            ranking_lookback=request.ranking_lookback,
            use_trade_quality_filter=request.use_trade_quality_filter,
            quality_trend_period=request.quality_trend_period,
            quality_min_trend_pct=request.quality_min_trend_pct,
            quality_max_range_rank_pct=request.quality_max_range_rank_pct,
            use_breadth_filter=request.use_breadth_filter,
            breadth_sma_period=request.breadth_sma_period,
            breadth_threshold_pct=request.breadth_threshold_pct,
        )
        return PortfolioEngine(
            frames, cfg, portfolio, option_data_by_ticker=option_frames
        ).run(progress=progress)
    ticker = next(iter(frames))
    return BacktestEngine(
        frames[ticker], replace(cfg, ticker=ticker),
        option_data=(option_frames or {}).get(ticker),
    ).run(progress=progress)


def _execute(run_id: str, request: BacktestRequest) -> None:
    with RUNS_LOCK:
        RUNS[run_id].status = "running"
    try:
        frames = {asset.ticker.upper(): _frame(asset) for asset in request.assets}
        result = _run_frames(run_id, request, frames)
        _finish_run(
            run_id,
            request,
            result,
            source="inline",
            data_summary={
                "assets_loaded": len(frames),
                "instrument": request.strategy.instrument,
                "option_model": request.strategy.options.pricing_model,
            },
        )
    except Exception as exc:  # job boundary: expose a safe, inspectable failure state
        with RUNS_LOCK:
            current = RUNS[run_id]
            current.status = "failed"
            current.progress = 1
            current.error = str(exc)


def _norgate_symbols(collection_type: str, collection_name: str) -> list[str]:
    if collection_type == "watchlist":
        return norgate_loader.get_watchlist_symbols(collection_name)
    return norgate_loader.get_database_symbols(collection_name)


def _execute_norgate(run_id: str, request: NorgateBacktestRequest) -> None:
    with RUNS_LOCK:
        RUNS[run_id].status = "running"
    try:
        if not norgate_loader.is_available():
            raise RuntimeError("Norgate Data Updater não está disponível. Inicie o NDU e tente novamente.")
        catalog_symbols = _norgate_symbols(request.collection_type, request.collection_name)
        requested = catalog_symbols if request.use_entire_collection else [symbol.strip().upper() for symbol in request.symbols if symbol.strip()]
        allowed = set(catalog_symbols)
        symbols = list(dict.fromkeys(symbol for symbol in requested if symbol in allowed))
        unknown = [symbol for symbol in requested if symbol not in allowed]
        if not symbols:
            raise ValueError("Nenhum dos símbolos informados pertence à coleção selecionada.")
        frames, warnings, skipped = norgate_loader.fetch_many(
            symbols,
            adjustment_label=request.adjustment,
            start_date=request.start_date.isoformat(),
            end_date=request.end_date.isoformat(),
            min_bars=request.min_bars,
            frequency_label=request.frequency,
            include_option_inputs=False,
            progress=lambda value: _set_progress(run_id, value * 0.40),
        )
        option_frames = None
        if request.strategy.instrument == "synthetic_atm_call":
            option_frames, option_warnings, option_skipped = norgate_loader.fetch_many(
                list(frames),
                adjustment_label="Capital (apenas splits)",
                start_date=request.start_date.isoformat(),
                end_date=request.end_date.isoformat(),
                min_bars=max(request.strategy.options.volatility_window + 2, 5),
                frequency_label="Diário",
                include_option_inputs=True,
                risk_free_symbol=(request.strategy.options.risk_free_symbol
                                  if request.strategy.options.risk_free_mode == "norgate" else ""),
                progress=lambda value: _set_progress(run_id, 0.40 + value * 0.20),
            )
            warnings.extend(option_warnings)
            if option_skipped:
                warnings.append(
                    "Sem série diária auxiliar para precificar calls: "
                    + ", ".join(option_skipped[:20])
                )
        if request.restrict_to_index:
            total = max(1, len(frames))
            for index, (ticker, frame) in enumerate(frames.items(), start=1):
                frame["_member"] = norgate_loader.membership_mask(
                    ticker,
                    request.index_name or "",
                    frame.index,
                    request.start_date.isoformat(),
                    request.end_date.isoformat(),
                )
                _set_progress(run_id, 0.60 + 0.05 * index / total)
        if not frames:
            raise ValueError("Nenhum ativo possui barras suficientes no período informado.")
        if request.mode == "per_asset" and len(frames) > 1:
            frames = {next(iter(frames)): next(iter(frames.values()))}
            warnings.append("Modo por ativo usa apenas o primeiro símbolo selecionado.")
        result = _run_frames(
            run_id, request, frames, progress_start=0.65,
            option_frames=option_frames,
        )
        result.warnings.extend(warnings)
        summary = {
            "collection_type": request.collection_type,
            "collection_name": request.collection_name,
            "assets_requested": len(requested),
            "assets_loaded": len(frames),
            "symbols": list(frames),
            "skipped": skipped,
            "unknown": unknown,
            "frequency": request.frequency,
            "adjustment": request.adjustment,
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "point_in_time": request.restrict_to_index,
            "breadth_filter": request.use_breadth_filter,
            "breadth_sma_period": request.breadth_sma_period,
            "breadth_threshold_pct": request.breadth_threshold_pct,
            "max_entries_per_date": request.max_entries_per_date,
            "entry_ranking": request.entry_ranking,
            "ranking_lookback": request.ranking_lookback,
            "use_trade_quality_filter": request.use_trade_quality_filter,
            "quality_trend_period": request.quality_trend_period,
            "quality_min_trend_pct": request.quality_min_trend_pct,
            "quality_max_range_rank_pct": request.quality_max_range_rank_pct,
            "instrument": request.strategy.instrument,
            "option_model": request.strategy.options.pricing_model,
            "option_pricing_frequency": ("Diário" if option_frames is not None else ""),
            "option_pricing_adjustment": ("Capital (apenas splits)" if option_frames is not None else ""),
        }
        _finish_run(run_id, request, result, source="norgate", data_summary=summary)
    except Exception as exc:
        with RUNS_LOCK:
            current = RUNS[run_id]
            current.status = "failed"
            current.progress = 1
            current.error = str(exc)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/v1/data-sources/norgate/status", response_model=NorgateStatus, tags=["data sources"])
def norgate_status() -> NorgateStatus:
    try:
        import norgatedata  # noqa: F401, PLC0415
        package_installed = True
    except ImportError:
        package_installed = False
    available = norgate_loader.is_available() if package_installed else False
    watchlists = norgate_loader.get_watchlists() if available else []
    databases = norgate_loader.get_databases() if available else []
    message = "Norgate Data Updater conectado." if available else "Instale o pacote e inicie o Norgate Data Updater."
    return NorgateStatus(available=available, package_installed=package_installed, updater_running=available, watchlists=len(watchlists), databases=len(databases), message=message)


@app.get("/v1/data-sources/norgate/catalog", response_model=NorgateCatalog, tags=["data sources"])
def norgate_catalog() -> NorgateCatalog:
    if not norgate_loader.is_available():
        raise HTTPException(status_code=503, detail="Norgate Data Updater indisponível")
    return NorgateCatalog(watchlists=norgate_loader.get_watchlists(), databases=norgate_loader.get_databases(), adjustments=norgate_loader.ADJ_LABELS, frequencies=norgate_loader.FREQ_LABELS)


@app.get("/v1/data-sources/norgate/symbols", tags=["data sources"])
def norgate_symbols(collection_type: str, collection_name: str) -> dict:
    if collection_type not in {"watchlist", "database"}:
        raise HTTPException(status_code=422, detail="collection_type deve ser watchlist ou database")
    symbols = _norgate_symbols(collection_type, collection_name)
    if not symbols:
        raise HTTPException(status_code=404, detail="Coleção não encontrada ou vazia")
    return {"collection_type": collection_type, "collection_name": collection_name, "count": len(symbols), "symbols": symbols}


@app.post("/v1/backtests/norgate", response_model=RunSummary, status_code=status.HTTP_202_ACCEPTED, tags=["backtests"])
def create_norgate_backtest(request: NorgateBacktestRequest, tasks: BackgroundTasks) -> RunSummary:
    run_id = f"run_{uuid4().hex[:12]}"
    run = RunSummary(id=run_id, name=request.name, mode=request.mode, status="queued", source="norgate")
    with RUNS_LOCK:
        RUNS[run_id] = run
    tasks.add_task(_execute_norgate, run_id, request)
    return run


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


@app.post("/v1/screenings/norgate", tags=["research"])
def norgate_screening(request: NorgateScreeningRequest) -> dict:
    if not norgate_loader.is_available():
        raise HTTPException(status_code=503, detail="Norgate Data Updater indisponível")
    catalog_symbols = _norgate_symbols(request.collection_type, request.collection_name)
    requested = catalog_symbols if request.use_entire_collection else [symbol.strip().upper() for symbol in request.symbols if symbol.strip()]
    allowed = set(catalog_symbols)
    symbols = list(dict.fromkeys(symbol for symbol in requested if symbol in allowed))
    if not symbols:
        raise HTTPException(status_code=422, detail="Nenhum símbolo pertence à coleção selecionada")
    frames, warnings, skipped = norgate_loader.fetch_many(
        symbols,
        adjustment_label=request.adjustment,
        start_date=request.start_date.isoformat(),
        end_date=request.end_date.isoformat(),
        min_bars=20,
        frequency_label=request.frequency,
    )
    cfg = StrategyConfig(rsi_period=request.rsi_period, rsi_entry_threshold=request.rsi_max)
    matches = []
    latest_date = None
    max_staleness = {"Diário": 10, "Semanal": 21, "Mensal": 62}[request.frequency]
    for ticker, frame in frames.items():
        observed = pd.Timestamp(frame.index[-1]).tz_localize(None)
        if (pd.Timestamp(request.end_date) - observed).days > max_staleness:
            skipped.append(ticker)
            continue
        signals = build_signal_frame(frame, cfg)
        row = signals.iloc[-1]
        close = float(row["close"])
        rsi_value = float(row["rsi"]) if pd.notna(row["rsi"]) else None
        turnover = float((frame["close"] * frame["volume"]).tail(20).mean()) if "volume" in frame else 0.0
        sma_200 = float(frame["close"].rolling(200).mean().iloc[-1]) if len(frame) >= 200 else None
        if rsi_value is None or rsi_value > request.rsi_max or close < request.min_price or turnover < request.min_average_turnover:
            continue
        matches.append({
            "ticker": ticker,
            "date": observed.date().isoformat(),
            "close": close,
            "rsi": rsi_value,
            "entry_signal": bool(row["entry_signal"]),
            "pattern": str(row["pattern"] or ""),
            "average_turnover": turnover,
            "distance_sma_200": (close / sma_200 - 1) if sma_200 else None,
        })
        latest_date = max(latest_date, observed) if latest_date is not None else observed
    return {
        "source": "norgate",
        "as_of": latest_date.date().isoformat() if latest_date is not None else request.end_date.isoformat(),
        "count": len(matches),
        "assets_loaded": len(frames),
        "skipped": sorted(set(skipped)),
        "warnings": warnings,
        "results": sorted(matches, key=lambda row: row["rsi"]),
    }


@app.get("/v1/fundamentals/{ticker}", tags=["research"])
def fundamentals(ticker: str) -> dict:
    symbol = ticker.strip().upper()
    if not symbol:
        raise HTTPException(status_code=422, detail="Informe um ticker")
    if not fundamental_data.is_available():
        raise HTTPException(status_code=503, detail="Norgate Data Updater indisponível")
    overview = fundamental_data.overview(symbol)
    values = fundamental_data.fetch_all(symbol)
    non_null = sum(value is not None for value, _ in values.values())
    if not overview.get("name") and non_null == 0:
        raise HTTPException(status_code=404, detail=f"Nenhum fundamento encontrado para {symbol}")
    end_date = pd.Timestamp.today().date().isoformat()
    start_date = (pd.Timestamp.today() - pd.Timedelta(days=45)).date().isoformat()
    prices, _ = norgate_loader.fetch_price(symbol, start_date=start_date, end_date=end_date, frequency_label="Diário")
    categories = []
    for title, help_text, fields in fundamental_data.CATALOG:
        metrics = []
        for token, label, unit in fields:
            value, reference_date = values.get(token, (None, None))
            metrics.append({
                "token": token,
                "label": label,
                "unit": unit,
                "value": _json_value(value),
                "formatted": fundamental_data.format_value(value, unit),
                "reference_date": reference_date,
            })
        categories.append({"title": title, "help": help_text, "metrics": metrics})
    return {
        "ticker": symbol,
        "source": "norgate",
        "overview": overview,
        "price": _json_number(prices["close"].iloc[-1]) if not prices.empty else None,
        "fields_with_data": non_null,
        "fields_total": len(fundamental_data.ALL_FIELDS),
        "categories": categories,
    }


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


@app.post("/v1/optimizations/norgate", tags=["research"])
def norgate_optimizations(request: NorgateOptimizationRequest) -> dict:
    if not norgate_loader.is_available():
        raise HTTPException(status_code=503, detail="Norgate Data Updater indisponível")
    catalog_symbols = _norgate_symbols(request.collection_type, request.collection_name)
    requested = catalog_symbols if request.use_entire_collection else [symbol.strip().upper() for symbol in request.symbols if symbol.strip()]
    allowed = set(catalog_symbols)
    symbols = list(dict.fromkeys(symbol for symbol in requested if symbol in allowed))
    if not symbols:
        raise HTTPException(status_code=422, detail="Nenhum símbolo pertence à coleção selecionada")
    frames, warnings, skipped = norgate_loader.fetch_many(
        symbols,
        adjustment_label=request.adjustment,
        start_date=request.start_date.isoformat(),
        end_date=request.end_date.isoformat(),
        min_bars=max(50, request.min_bars),
        frequency_label=request.frequency,
        include_option_inputs=request.strategy.instrument == "synthetic_atm_call",
        risk_free_symbol=(request.strategy.options.risk_free_symbol
                          if request.strategy.options.risk_free_mode == "norgate" else ""),
    )
    if not frames:
        raise HTTPException(status_code=422, detail="Nenhum ativo possui barras suficientes")
    cfg = _config(request)
    if request.validation == "walk_forward":
        result = run_walk_forward(frames, cfg, request.parameter_ranges, objective=request.objective, n_splits=request.splits, min_trades=request.min_trades)
        split_date = None
    else:
        result, split_date = run_grid(frames, cfg, request.parameter_ranges, min_trades=request.min_trades)
    clean = result.replace([float("inf"), float("-inf")], None).where(pd.notna(result), None)
    return {
        "source": "norgate",
        "validation": request.validation,
        "objective": request.objective,
        "split_date": str(split_date) if split_date else None,
        "assets_loaded": len(frames),
        "symbols": list(frames),
        "skipped": skipped,
        "warnings": warnings,
        "results": clean.to_dict(orient="records"),
    }
