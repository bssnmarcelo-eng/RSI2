from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Candle(BaseModel):
    date: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_ohlc(self) -> "Candle":
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close) or self.high < self.low:
            raise ValueError("OHLC inconsistente: high/low devem conter open e close")
        return self


class OptionSimulationInput(BaseModel):
    pricing_model: Literal["black_scholes", "binomial"] = "black_scholes"
    strike_mode: Literal["exact_atm", "rounded", "otm_pct"] = "exact_atm"
    strike_interval: float = Field(default=1, gt=0, le=1_000)
    otm_pct: float = Field(default=10, gt=0, le=1_000)
    target_dte: int = Field(default=45, ge=7, le=730)
    # Deprecated compatibility field. Contracts are never rolled.
    roll_dte: int = Field(default=0, ge=0, le=365)
    volatility_window: int = Field(default=20, ge=2, le=252)
    iv_multiplier: float = Field(default=1.2, gt=0, le=10)
    iv_floor: float = Field(default=0.10, gt=0, le=10)
    iv_cap: float = Field(default=2.0, gt=0, le=10)
    iv_scenario: float = Field(default=1.0, gt=0, le=10)
    risk_free_mode: Literal["norgate", "fixed"] = "norgate"
    risk_free_symbol: str = Field(default="%3MTCM", min_length=1, max_length=24)
    risk_free_rate: float = Field(default=0.04, ge=-0.10, le=1)
    dividend_yield: float = Field(default=0, ge=0, le=1)
    spread_pct: float = Field(default=0.08, ge=0, le=2)
    minimum_half_spread: float = Field(default=0.01, ge=0, le=100)
    commission_per_contract: float = Field(default=0.65, ge=0, le=1_000)
    sizing_mode: Literal["premium_risk", "delta_equivalent"] = "premium_risk"
    premium_risk_pct: float = Field(default=10, gt=0, le=100)
    binomial_steps: int = Field(default=200, ge=10, le=2_000)

    @model_validator(mode="after")
    def validate_option_assumptions(self) -> "OptionSimulationInput":
        if self.iv_floor > self.iv_cap:
            raise ValueError("Piso de IV deve ser menor ou igual ao teto de IV")
        return self


class StrategyInput(BaseModel):
    instrument: Literal["stock", "synthetic_atm_call"] = "stock"
    options: OptionSimulationInput = Field(default_factory=OptionSimulationInput)
    rsi_period: int = Field(default=2, ge=2, le=100)
    rsi_entry: float = Field(default=10, ge=0, le=100)
    use_hammer: bool = True
    hammer_percentile: float = Field(default=0.33, gt=0, le=1)
    hammer_require_bullish_close: bool = False
    hammer_use_atr_filter: bool = True
    hammer_atr_period: int = Field(default=14, ge=1, le=500)
    hammer_atr_multiple: float = Field(default=1, ge=0, le=100)
    use_rsi_exit: bool = True
    rsi_exit: float = Field(default=70, ge=0, le=100)
    use_max_bars: bool = True
    max_bars: int = Field(default=7, ge=1, le=500)
    use_profit_target: bool = False
    profit_target_pct: float = Field(default=5, gt=0, le=1_000)
    use_stop_loss: bool = False
    stop_loss_pct: float = Field(default=3, gt=0, le=100)
    use_sma_exit: bool = False
    sma_period: int = Field(default=5, ge=1, le=500)
    use_signal_low_stop: bool = False
    use_rsi_cum_exit: bool = False
    rsi_cum_periods: int = Field(default=2, ge=1, le=50)
    rsi_cum_threshold: float = Field(default=100, ge=0, le=1_000)
    initial_capital: float = Field(default=100_000, gt=0)
    commission_fixed: float = Field(default=0, ge=0)
    commission_pct: float = Field(default=0.0003, ge=0, le=1)
    slippage_bps: float = Field(default=10, ge=0, le=10_000)


class AssetSeries(BaseModel):
    ticker: str = Field(min_length=1, max_length=24)
    candles: list[Candle] = Field(min_length=3)


class BacktestRequest(BaseModel):
    name: str = Field(default="Backtest via API", max_length=120)
    mode: Literal["per_asset", "portfolio"] = "per_asset"
    assets: list[AssetSeries] = Field(min_length=1)
    strategy: StrategyInput = Field(default_factory=StrategyInput)
    max_positions: int = Field(default=10, ge=0, le=1_000)
    pct_per_trade: float = Field(default=10, gt=0, le=100)
    max_entries_per_date: int = Field(default=1, ge=1, le=1_000)
    entry_ranking: Literal[
        "lowest_rsi", "largest_hammer_atr", "highest_relative_volume",
        "strongest_trend", "highest_volatility",
    ] = "lowest_rsi"
    ranking_lookback: int = Field(default=20, ge=2, le=500)
    minimum_candidates_per_date: int = Field(default=0, ge=0, le=1_000)
    use_trade_quality_filter: bool = False
    quality_trend_period: int = Field(default=10, ge=2, le=500)
    quality_min_trend_pct: float = Field(default=-3.0, ge=-100, le=1_000)
    quality_max_range_rank_pct: float = Field(default=10.0, gt=0, le=100)
    use_breadth_filter: bool = False
    breadth_sma_period: int = Field(default=40, ge=2, le=500)
    breadth_threshold_pct: float = Field(default=50, ge=0, le=100)


class RunSummary(BaseModel):
    id: str
    name: str
    mode: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    progress: float = Field(default=0, ge=0, le=1)
    source: Literal["inline", "norgate"] = "inline"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metrics: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    trade_count: int = 0
    equity: list[dict[str, float | str]] = Field(default_factory=list)
    trades: list[dict[str, float | int | str | None]] = Field(default_factory=list)
    data_summary: dict[str, str | int | float | bool | list[str]] = Field(default_factory=dict)
    scenario_metrics: dict[str, dict[str, float]] = Field(default_factory=dict)
    scenario_equity: dict[str, list[dict[str, float | str]]] = Field(default_factory=dict)
    error: str | None = None


class NorgateBacktestRequest(BaseModel):
    name: str = Field(default="Backtest Norgate", max_length=120)
    mode: Literal["per_asset", "portfolio"] = "portfolio"
    collection_type: Literal["watchlist", "database"] = "watchlist"
    collection_name: str = Field(min_length=1, max_length=200)
    symbols: list[str] = Field(default_factory=list, max_length=1_000)
    use_entire_collection: bool = False
    start_date: date
    end_date: date
    frequency: Literal["Diário", "Semanal", "Mensal"] = "Semanal"
    adjustment: Literal[
        "Total Return (splits + dividendos)",
        "Capital (apenas splits)",
        "Capital + dividendos especiais",
        "Sem ajuste",
    ] = "Total Return (splits + dividendos)"
    restrict_to_index: bool = False
    index_name: str | None = Field(default=None, max_length=200)
    min_bars: int = Field(default=20, ge=3, le=10_000)
    strategy: StrategyInput = Field(default_factory=StrategyInput)
    max_positions: int = Field(default=10, ge=0, le=1_000)
    pct_per_trade: float = Field(default=10, gt=0, le=100)
    max_entries_per_date: int = Field(default=1, ge=1, le=1_000)
    entry_ranking: Literal[
        "lowest_rsi", "largest_hammer_atr", "highest_relative_volume",
        "strongest_trend", "highest_volatility",
    ] = "lowest_rsi"
    ranking_lookback: int = Field(default=20, ge=2, le=500)
    minimum_candidates_per_date: int = Field(default=0, ge=0, le=1_000)
    use_trade_quality_filter: bool = False
    quality_trend_period: int = Field(default=10, ge=2, le=500)
    quality_min_trend_pct: float = Field(default=-3.0, ge=-100, le=1_000)
    quality_max_range_rank_pct: float = Field(default=10.0, gt=0, le=100)
    use_breadth_filter: bool = False
    breadth_sma_period: int = Field(default=40, ge=2, le=500)
    breadth_threshold_pct: float = Field(default=50, ge=0, le=100)

    @model_validator(mode="after")
    def validate_norgate_request(self) -> "NorgateBacktestRequest":
        if self.start_date > self.end_date:
            raise ValueError("Data inicial deve ser anterior à data final")
        if not self.use_entire_collection and not self.symbols:
            raise ValueError("Informe ao menos um símbolo ou use a coleção inteira")
        if self.restrict_to_index and not (self.index_name or "").strip():
            raise ValueError("Informe o nome do índice para a restrição point-in-time")
        if self.use_breadth_filter and self.mode == "portfolio":
            if not self.use_entire_collection or not self.restrict_to_index:
                raise ValueError(
                    "Breadth exige a coleção inteira e constituintes point-in-time"
                )
        return self


class NorgateStatus(BaseModel):
    available: bool
    package_installed: bool
    updater_running: bool
    watchlists: int = 0
    databases: int = 0
    message: str


class NorgateCatalog(BaseModel):
    watchlists: list[str]
    databases: list[str]
    adjustments: list[str]
    frequencies: list[str]


class ScreeningRequest(BaseModel):
    assets: list[AssetSeries] = Field(min_length=1)
    rsi_max: float = Field(default=20, ge=0, le=100)
    min_price: float = Field(default=0, ge=0)


class NorgateScreeningRequest(BaseModel):
    collection_type: Literal["watchlist", "database"] = "watchlist"
    collection_name: str = Field(min_length=1, max_length=200)
    symbols: list[str] = Field(default_factory=list, max_length=1_000)
    use_entire_collection: bool = False
    start_date: date = Field(default_factory=lambda: date.today() - timedelta(days=730))
    end_date: date = Field(default_factory=date.today)
    frequency: Literal["Diário", "Semanal", "Mensal"] = "Diário"
    adjustment: Literal[
        "Total Return (splits + dividendos)",
        "Capital (apenas splits)",
        "Capital + dividendos especiais",
        "Sem ajuste",
    ] = "Total Return (splits + dividendos)"
    rsi_period: int = Field(default=2, ge=2, le=100)
    rsi_max: float = Field(default=20, ge=0, le=100)
    min_price: float = Field(default=0, ge=0)
    min_average_turnover: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_norgate_screening(self) -> "NorgateScreeningRequest":
        if self.start_date > self.end_date:
            raise ValueError("Data inicial deve ser anterior à data final")
        if not self.use_entire_collection and not self.symbols:
            raise ValueError("Informe ao menos um símbolo ou use a coleção inteira")
        return self


class OptimizationRequest(BaseModel):
    assets: list[AssetSeries] = Field(min_length=1)
    strategy: StrategyInput = Field(default_factory=StrategyInput)
    parameter_ranges: dict[str, list[float | int]]
    validation: Literal["split", "walk_forward"] = "walk_forward"
    objective: Literal["sharpe", "expectancy", "profit_factor", "win_rate", "total_pnl"] = "sharpe"
    splits: int = Field(default=3, ge=1, le=12)
    min_trades: int = Field(default=10, ge=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> "OptimizationRequest":
        allowed = {"rsi_period", "rsi_entry_threshold", "rsi_exit_threshold", "max_bars", "profit_target_pct", "stop_loss_pct", "sma_period", "hammer_percentile"}
        unknown = set(self.parameter_ranges) - allowed
        combinations = 1
        for values in self.parameter_ranges.values():
            if not values:
                raise ValueError("Cada intervalo deve conter ao menos um valor")
            combinations *= len(values)
        if unknown:
            raise ValueError(f"Parâmetros desconhecidos: {', '.join(sorted(unknown))}")
        if combinations > 10_000:
            raise ValueError("Espaço de busca limitado a 10.000 combinações por requisição")
        return self


class NorgateOptimizationRequest(NorgateBacktestRequest):
    parameter_ranges: dict[str, list[float | int]]
    validation: Literal["split", "walk_forward"] = "walk_forward"
    objective: Literal["sharpe", "expectancy", "profit_factor", "win_rate", "total_pnl"] = "sharpe"
    splits: int = Field(default=3, ge=1, le=12)
    min_trades: int = Field(default=10, ge=0)

    @model_validator(mode="after")
    def validate_norgate_ranges(self) -> "NorgateOptimizationRequest":
        allowed = {"rsi_period", "rsi_entry_threshold", "rsi_exit_threshold", "max_bars", "hammer_percentile"}
        unknown = set(self.parameter_ranges) - allowed
        combinations = 1
        for values in self.parameter_ranges.values():
            if not values:
                raise ValueError("Cada intervalo deve conter ao menos um valor")
            combinations *= len(values)
        if unknown:
            raise ValueError(f"Parâmetros desconhecidos: {', '.join(sorted(unknown))}")
        if combinations > 1_000:
            raise ValueError("Espaço Norgate limitado a 1.000 combinações por requisição")
        return self


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "rsi2-api"
    version: str = "1.0.0"
