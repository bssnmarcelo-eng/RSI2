from __future__ import annotations

from datetime import datetime, timezone
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


class StrategyInput(BaseModel):
    rsi_period: int = Field(default=2, ge=2, le=100)
    rsi_entry: float = Field(default=10, ge=0, le=100)
    rsi_exit: float = Field(default=70, ge=0, le=100)
    max_bars: int = Field(default=7, ge=1, le=500)
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


class RunSummary(BaseModel):
    id: str
    name: str
    mode: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metrics: dict[str, float] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    trade_count: int = 0
    equity: list[dict[str, float | str]] = Field(default_factory=list)
    error: str | None = None


class ScreeningRequest(BaseModel):
    assets: list[AssetSeries] = Field(min_length=1)
    rsi_max: float = Field(default=20, ge=0, le=100)
    min_price: float = Field(default=0, ge=0)


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


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: str = "rsi2-api"
    version: str = "1.0.0"
