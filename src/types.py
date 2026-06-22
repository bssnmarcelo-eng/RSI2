"""Typed configuration objects and result containers for the backtester.

These dataclasses centralise every tunable parameter so the engine never relies
on hardcoded magic numbers. The Streamlit UI builds a :class:`StrategyConfig`
from sidebar widgets and hands it to the engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Execution(str, Enum):
    """When an order is filled relative to the signal candle.

    NEXT_OPEN is the realistic default: a signal is only *known* once the candle
    closes, so the earliest tradable price is the next candle's open. SIGNAL_CLOSE
    fills at the close of the signal candle itself, which is optimistic /
    less realistic because it assumes you can transact at a price you only
    observe after the bar is complete.
    """

    NEXT_OPEN = "next_open"
    SIGNAL_CLOSE = "signal_close"
    # LIMIT_AT_CLOSE: place a buy limit order at the signal candle's close, valid
    # only for the next candle. On that next candle:
    #   1. open <= limit            -> fill at the open (gap below the limit)
    #   2. open > limit & low <= limit -> fill at the limit price (price retraced)
    #   3. open > limit & low > limit  -> no fill (limit never reached; cancelled)
    LIMIT_AT_CLOSE = "limit_at_close"


class SizingMethod(str, Enum):
    """How much capital is committed per trade."""

    FIXED = "fixed"            # fixed cash amount per trade
    PERCENT = "percent"        # percentage of current equity
    FULL = "full"             # all available cash


class PortfolioSizing(str, Enum):
    """How the portfolio engine sizes each position."""

    PERCENT = "percent"          # % of equity per trade, capped by buying power
    FULL_EQUITY = "full_equity"  # 100% of equity per trade, unlimited buying power


class CommissionModel(str, Enum):
    """How per-order commissions are computed."""

    GENERIC = "generic"          # fixed per fill + % of notional (user-defined)
    IBKR_FIXED = "ibkr_fixed"    # Interactive Brokers "IBKR Pro — Fixed" (US stocks)


@dataclass
class HammerParams:
    """Percentile-based hammer-detection thresholds (see candlestick_patterns.py).

    A candle is a hammer when BOTH the open and the close sit in the top
    ``percentile`` fraction of the candle's range, i.e. with ``range = high - low``:

        open  > high - percentile * range
        close > high - percentile * range

    This puts the body near the top of the candle (a long lower shadow).
    ``percentile = 1/3`` ≈ the classic "body in the upper third".
    """

    percentile: float = 0.33
    require_bullish_close: bool = False
    # Optional ATR filter: require the candle's range (high - low) to exceed
    # atr_multiple * ATR(atr_period), i.e. only "wide" reversal candles qualify.
    use_atr_filter: bool = True
    atr_period: int = 14
    atr_multiple: float = 1.0


@dataclass
class PatternConfig:
    """Bullish-reversal pattern configuration. Only the Hammer is supported."""

    use_hammer: bool = True
    hammer: HammerParams = field(default_factory=HammerParams)

    def any_enabled(self) -> bool:
        return self.use_hammer


@dataclass
class ExitConfig:
    """Exit rules. When several are enabled, the first one triggered wins."""

    # 1) RSI closes above threshold.
    use_rsi_exit: bool = True
    rsi_exit_threshold: float = 70.0

    # 2) Time stop: exit after a fixed number of bars held.
    use_max_bars: bool = True
    max_bars: int = 5

    # 3) Profit target (percentage gain vs entry price), disabled by default.
    use_profit_target: bool = False
    profit_target_pct: float = 5.0

    # 4) Stop loss (percentage loss vs entry price), disabled by default.
    use_stop_loss: bool = False
    stop_loss_pct: float = 3.0

    # 5) Close above SMA(n), disabled by default.
    use_sma_exit: bool = False
    sma_period: int = 5

    # 6) Hard stop at the LOW of the signal candle (the candlestick-pattern bar).
    #    Unlike the rules above (which are confirmed on the close), this is an
    #    intrabar stop order: if a bar's low pierces the signal candle's low, the
    #    position is exited within that bar at the stop level (or at the open if
    #    the bar gaps below it). Disabled by default.
    use_signal_low_stop: bool = False

    # 7) Cumulative RSI exit: exit when the rolling sum of RSI over the last
    #    rsi_cum_periods bars exceeds rsi_cum_threshold. Captures mean-reversion
    #    exhaustion even when individual RSI bars haven't breached the exit level.
    use_rsi_cum_exit: bool = False
    rsi_cum_periods: int = 2
    rsi_cum_threshold: float = 100.0


@dataclass
class CostConfig:
    """Transaction frictions applied on every fill (entry and exit each count)."""

    model: CommissionModel = CommissionModel.GENERIC

    # --- GENERIC model parameters ---
    commission_fixed: float = 0.0     # currency units per execution
    commission_pct: float = 0.0       # fraction of notional, e.g. 0.001 = 0.1%

    # --- IBKR Pro "Fixed" (US stocks/ETFs) parameters ---
    # Commission per order = clamp(shares * per_share, min=min_per_order,
    #                              max=max_pct_of_trade * trade_value).
    # The per-share rate bundles all exchange, clearing and regulatory fees.
    ibkr_per_share: float = 0.005       # USD 0.005 per share
    ibkr_min_per_order: float = 1.0     # USD 1.00 minimum per order
    ibkr_max_pct: float = 0.01          # capped at 1.0% of trade value

    # --- Applies to all models ---
    slippage_bps: float = 0.0         # basis points moved against you per fill


@dataclass
class SizingConfig:
    """Position-sizing configuration."""

    method: SizingMethod = SizingMethod.FULL
    fixed_capital: float = 10_000.0   # used when method == FIXED
    percent: float = 100.0            # used when method == PERCENT (% of equity)
    allow_fractional: bool = True     # fractional shares keep equity math exact


@dataclass
class PortfolioConfig:
    """Shared-capital portfolio settings (used by the multi-asset engine).

    Buying power is modelled IBKR-style: ``buying_power = equity * leverage``.
    A single cash pool is shared across all assets; cash may go negative
    (a margin loan) as long as total long exposure stays within buying power.
    Each new position is sized as ``pct_per_trade`` percent of current equity
    (notional). When several entry signals fire on the same bar and buying power
    is scarce, the most oversold names (lowest RSI) are filled first.
    """

    initial_capital: float = 100_000.0
    sizing_mode: PortfolioSizing = PortfolioSizing.PERCENT
    pct_per_trade: float = 10.0       # % of equity (notional) per position (PERCENT mode)
    leverage: float = 1.0             # buying-power multiple (1.0 = cash account) (PERCENT mode)
    max_positions: int = 0            # hard cap on concurrent positions; 0 = no cap (PERCENT mode)
    allow_fractional: bool = True     # fractional shares keep portfolio math exact


@dataclass
class StrategyConfig:
    """Complete, self-contained description of a backtest run."""

    # --- Indicator / entry ---
    rsi_period: int = 2
    rsi_entry_threshold: float = 10.0

    # --- Price filter (applied to the signal candle's close; 0 = no bound) ---
    min_price: float = 0.0   # only trade when close >= min_price
    max_price: float = 0.0   # only trade when close <= max_price

    # --- Patterns ---
    patterns: PatternConfig = field(default_factory=PatternConfig)

    # --- Execution timing ---
    entry_execution: Execution = Execution.NEXT_OPEN
    exit_execution: Execution = Execution.NEXT_OPEN

    # --- Exits / costs / sizing ---
    exits: ExitConfig = field(default_factory=ExitConfig)
    costs: CostConfig = field(default_factory=CostConfig)
    sizing: SizingConfig = field(default_factory=SizingConfig)

    # --- Account ---
    initial_capital: float = 100_000.0

    ticker: str = ""


@dataclass
class Trade:
    """A single completed round-trip trade for the trade log."""

    ticker: str
    signal_date: object
    signal_close: float
    rsi_at_signal: float
    signal_range: float           # high - low of the signal candle
    signal_body_percentile: float  # (high - min(open,close)) / range of the signal candle
    signal_atr_mult: float        # range / ATR(period) of the signal candle (bar size in ATRs)
    pattern: str
    entry_date: object
    entry_price: float
    exit_date: object
    exit_price: float
    exit_reason: str
    bars_held: int
    gross_return: float
    net_return: float
    pnl: float
    equity_after: float
