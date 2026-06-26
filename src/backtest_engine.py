"""Event-driven, candle-by-candle backtest engine.

Design contract — NO LOOK-AHEAD BIAS
-------------------------------------
* Indicators (RSI, SMA) are computed once up front but are causal: the value at
  bar i uses only bars <= i.
* A trade *signal* is evaluated at the CLOSE of bar i (we only know the candle is
  a hammer / RSI is low once the candle is finished).
* With the realistic default (Execution.NEXT_OPEN) the resulting order is filled
  at the OPEN of bar i+1. We never fill at a price from the same bar whose close
  produced the signal.
* The optional Execution.SIGNAL_CLOSE fills at the close of the signal bar. It is
  explicitly flagged in the UI as optimistic / less realistic.

Per-bar processing order:
    1. Fill any order scheduled for *this* bar's open (exits first, then entries).
    2. If in a position, evaluate exit rules at this bar's close and schedule
       (or, for SIGNAL_CLOSE, immediately execute) the exit.
    3. If flat, evaluate the entry signal at this bar's close and schedule
       (or immediately execute) the entry.
    4. Mark-to-market: record equity at this bar's close.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import pandas as pd

from . import indicators
from .candlestick_patterns import detect_all
from .types import Execution, SizingMethod, StrategyConfig, Trade
from .utils import commission_for


@dataclass
class _OpenPosition:
    """Internal bookkeeping for the single open position (one at a time)."""

    shares: float
    entry_price: float          # executed price incl. slippage
    entry_index: int
    entry_date: object
    entry_commission: float
    # Carried-over signal metadata for the eventual trade-log row.
    signal_date: object
    signal_close: float
    signal_low: float           # low of the signal candle (for the signal-low stop)
    signal_range: float         # high - low of the signal candle
    signal_body_percentile: float  # (high - min(open,close)) / range of the signal candle
    signal_atr_mult: float      # range / ATR(period) of the signal candle
    rsi_at_signal: float
    pattern: str
    entered_at_close: bool      # True if filled on its own signal bar's close
    max_high_seen: float = 0.0  # running peak high for MFE calculation


@dataclass
class BacktestResult:
    """Everything the UI needs to render results."""

    trades: pd.DataFrame
    equity_curve: pd.Series          # equity marked at each bar close
    data: pd.DataFrame               # OHLC + rsi + sma + signal columns
    config: StrategyConfig
    warnings: List[str]


def build_signal_frame(data: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    """Attach indicators, patterns and the boolean entry-signal column.

    Causal by construction: every column at bar i depends only on bars <= i.
    Shared by both the single-asset and the portfolio engines so the signal
    definition stays identical across modes.
    """
    df = data[["open", "high", "low", "close"]].copy()
    df["rsi"] = indicators.rsi(df["close"], config.rsi_period)

    # Candle size in ATR units (range / ATR) — the candle's "ATR multiple". Always
    # computed (independent of the optional ATR hammer filter) for the trade log.
    atr_series = indicators.atr(df["high"], df["low"], df["close"], config.patterns.hammer.atr_period)
    df["atr_mult"] = ((df["high"] - df["low"]) / atr_series).replace([np.inf, -np.inf], np.nan)

    # SMA used by the optional "close above SMA(n)" exit rule.
    if config.exits.use_sma_exit:
        df["sma_exit"] = indicators.sma(df["close"], config.exits.sma_period)
    else:
        df["sma_exit"] = np.nan

    # Cumulative RSI: rolling sum of RSI over the last N bars.
    if config.exits.use_rsi_cum_exit:
        n = config.exits.rsi_cum_periods
        df["rsi_cum"] = df["rsi"].rolling(n, min_periods=n).sum()
    else:
        df["rsi_cum"] = np.nan

    patterns = detect_all(data, config.patterns)
    df["pattern"] = patterns["pattern"] if "pattern" in patterns else ""
    any_pattern = patterns["any_pattern"] if "any_pattern" in patterns else False

    # Entry signal confirmed at candle close: RSI below threshold AND an
    # enabled bullish-reversal pattern present on this candle.
    signal = (df["rsi"] < config.rsi_entry_threshold) & any_pattern

    # Optional price filter on the signal candle's close (0 = bound disabled).
    if config.min_price and config.min_price > 0:
        signal &= df["close"] >= config.min_price
    if config.max_price and config.max_price > 0:
        signal &= df["close"] <= config.max_price

    # Point-in-time index membership: when a boolean ``_member`` column is attached
    # (Norgate source with constituent gating on), only allow entries on bars where
    # the asset was actually a constituent of the selected index. Indicators above
    # are still computed over the full history, so they stay causal/correct.
    if "_member" in data.columns:
        signal &= data["_member"].reindex(df.index).fillna(False)

    df["entry_signal"] = signal.fillna(False)
    return df


class BacktestEngine:
    """Runs one long-only mean-reversion backtest on a prepared OHLC frame."""

    def __init__(self, data: pd.DataFrame, config: StrategyConfig):
        self.raw = data
        self.config = config
        self.warnings: List[str] = []

    # ------------------------------------------------------------------ setup
    def _prepare_signals(self) -> pd.DataFrame:
        """Attach indicators, patterns and the boolean entry-signal column."""
        return build_signal_frame(self.raw, self.config)

    # ------------------------------------------------------------ sizing/costs
    def _shares_for(self, cash: float, equity: float, price: float) -> float:
        """Determine share quantity for an entry given the sizing method."""
        cfg = self.config.sizing
        if cfg.method == SizingMethod.FIXED:
            capital = min(cfg.fixed_capital, cash)
        elif cfg.method == SizingMethod.PERCENT:
            capital = min(equity * (cfg.percent / 100.0), cash)
        else:  # FULL
            capital = cash

        if price <= 0 or capital <= 0:
            return 0.0
        shares = capital / price
        if not cfg.allow_fractional:
            shares = math.floor(shares)
        return float(shares)

    def _commission(self, shares: float, notional: float) -> float:
        return commission_for(self.config.costs, shares, notional)

    def _fit_to_cash(self, shares: float, price: float, cash: float) -> float:
        """Shrink ``shares`` if needed so notional + commission fits in ``cash``.

        Full-equity sizing deploys ~100% of cash into shares, which would leave no
        room for commission; this scales the order down (a few passes converge) so
        the buy is always affordable. Returns 0 if nothing fits.
        """
        if shares <= 0 or price <= 0:
            return 0.0
        for _ in range(4):
            notional = shares * price
            total = notional + self._commission(shares, notional)
            if total <= cash + 1e-9:
                return shares
            shares = shares * (cash / total) * (1.0 - 1e-9) if total > 0 else 0.0
            if not self.config.sizing.allow_fractional:
                shares = float(math.floor(shares))
            if shares <= 0:
                return 0.0
        notional = shares * price
        return shares if notional + self._commission(shares, notional) <= cash + 1e-9 else 0.0

    def _buy_price(self, raw_price: float) -> float:
        # Slippage moves the fill against the buyer (pay a little more).
        return raw_price * (1.0 + self.config.costs.slippage_bps / 10_000.0)

    def _sell_price(self, raw_price: float) -> float:
        # Slippage moves the fill against the seller (receive a little less).
        return raw_price * (1.0 - self.config.costs.slippage_bps / 10_000.0)

    # ------------------------------------------------------------------- exits
    def _exit_reason(self, pos: _OpenPosition, i: int, df: pd.DataFrame) -> Optional[str]:
        """Return the first triggered exit reason at the close of bar ``i``.

        Profit-target / stop-loss are evaluated on the *close* (the price we can
        confirm), consistent with the close-confirmation philosophy of the entry.
        """
        cfg = self.config.exits
        close = float(df["close"].iat[i])
        rsi_val = df["rsi"].iat[i]
        bars_held = i - pos.entry_index

        # Priority order: RSI -> cumulative RSI -> time stop -> profit target -> stop loss -> SMA.
        if cfg.use_rsi_exit and pd.notna(rsi_val) and rsi_val > cfg.rsi_exit_threshold:
            return f"RSI > {cfg.rsi_exit_threshold:g}"

        if cfg.use_rsi_cum_exit:
            rsi_cum_val = df["rsi_cum"].iat[i]
            if pd.notna(rsi_cum_val) and rsi_cum_val > cfg.rsi_cum_threshold:
                return f"RSI({cfg.rsi_cum_periods}) acum > {cfg.rsi_cum_threshold:g}"

        if cfg.use_max_bars and bars_held >= cfg.max_bars:
            return f"Time stop ({cfg.max_bars} bars)"

        if cfg.use_profit_target:
            if close >= pos.entry_price * (1.0 + cfg.profit_target_pct / 100.0):
                return f"Profit target (+{cfg.profit_target_pct:g}%)"

        if cfg.use_stop_loss:
            if close <= pos.entry_price * (1.0 - cfg.stop_loss_pct / 100.0):
                return f"Stop loss (-{cfg.stop_loss_pct:g}%)"

        if cfg.use_sma_exit:
            sma_val = df["sma_exit"].iat[i]
            if pd.notna(sma_val) and close > sma_val:
                return f"Close > SMA({cfg.sma_period})"

        return None

    # ------------------------------------------------------------------- close
    def _close_position(
        self,
        pos: _OpenPosition,
        exit_price_raw: float,
        exit_index: int,
        exit_date,
        reason: str,
        df: pd.DataFrame,
        cash: float,
    ) -> tuple[float, Trade]:
        """Execute the sell, returning (new_cash, completed Trade)."""
        exec_price = self._sell_price(exit_price_raw)
        proceeds = pos.shares * exec_price
        exit_commission = self._commission(pos.shares, proceeds)
        new_cash = cash + proceeds - exit_commission

        entry_notional = pos.shares * pos.entry_price
        gross_pnl = proceeds - entry_notional
        net_pnl = gross_pnl - pos.entry_commission - exit_commission
        cost_basis = entry_notional + pos.entry_commission
        gross_return = (exec_price / pos.entry_price) - 1.0 if pos.entry_price else 0.0
        net_return = net_pnl / cost_basis if cost_basis else 0.0

        mfe_raw = pos.max_high_seen - pos.entry_price
        mfe = mfe_raw / pos.entry_price if pos.entry_price else 0.0

        trade = Trade(
            ticker=self.config.ticker,
            signal_date=pos.signal_date,
            signal_close=pos.signal_close,
            rsi_at_signal=pos.rsi_at_signal,
            signal_range=pos.signal_range,
            signal_body_percentile=pos.signal_body_percentile,
            signal_atr_mult=pos.signal_atr_mult,
            pattern=pos.pattern,
            entry_date=pos.entry_date,
            entry_price=pos.entry_price,
            exit_date=exit_date,
            exit_price=exec_price,
            exit_reason=reason,
            bars_held=exit_index - pos.entry_index,
            gross_return=gross_return,
            net_return=net_return,
            pnl=net_pnl,
            equity_after=new_cash,  # flat after exit, so equity == cash
            mfe=mfe,
        )
        return new_cash, trade

    # -------------------------------------------------------------------- main
    def run(self, progress=None) -> BacktestResult:
        """Run the backtest.

        *progress* is an optional callable ``(fraction: float) -> None`` called
        approximately every 250 bars so the UI can update a progress bar.
        """
        cfg = self.config
        df = self._prepare_signals()
        n = len(df)

        opens = df["open"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        dates = df.index

        cash = float(cfg.initial_capital)
        position: Optional[_OpenPosition] = None
        pending_entry: Optional[dict] = None   # filled at next bar's open
        pending_exit: Optional[dict] = None     # filled at next bar's open

        trades: List[Trade] = []
        equity = np.empty(n, dtype=float)

        _step = max(1, n // 200)   # report ~200 times regardless of dataset size

        for i in range(n):
            if progress and i % _step == 0:
                progress(i / n)
            open_i = opens[i]
            close_i = closes[i]

            # --- 1a. Fill scheduled EXIT at this bar's open --------------------
            if pending_exit is not None and position is not None:
                cash, trade = self._close_position(
                    position, open_i, i, dates[i], pending_exit["reason"], df, cash
                )
                trades.append(trade)
                position = None
                pending_exit = None

            # --- 1b. Fill scheduled ENTRY on this bar ---------------------------
            if pending_entry is not None and position is None:
                # Determine the fill price (None = order does not fill this bar).
                if cfg.entry_execution == Execution.LIMIT_AT_CLOSE:
                    limit = pending_entry["signal_close"]
                    if open_i <= limit:
                        exec_price = open_i          # case 1: gap below the limit
                    elif lows[i] <= limit:
                        exec_price = limit           # case 2: retraced to the limit
                    else:
                        exec_price = None            # case 3: limit never reached
                    # A limit order fills at the limit price or better — no slippage.
                else:  # NEXT_OPEN: market order at the open (slippage applies)
                    exec_price = self._buy_price(open_i)

                if exec_price is not None:
                    equity_now = cash  # flat, so equity == cash
                    shares = self._fit_to_cash(
                        self._shares_for(cash, equity_now, exec_price), exec_price, cash)
                    if shares > 0:
                        notional = shares * exec_price
                        commission = self._commission(shares, notional)
                        cash -= notional + commission
                        position = _OpenPosition(
                            shares=shares,
                            entry_price=exec_price,
                            entry_index=i,
                            entry_date=dates[i],
                            entry_commission=commission,
                            signal_date=pending_entry["signal_date"],
                            signal_close=pending_entry["signal_close"],
                            signal_low=pending_entry["signal_low"],
                            signal_range=pending_entry["signal_range"],
                            signal_body_percentile=pending_entry["signal_body_percentile"],
                            signal_atr_mult=pending_entry["signal_atr_mult"],
                            rsi_at_signal=pending_entry["rsi_at_signal"],
                            pattern=pending_entry["pattern"],
                            entered_at_close=False,
                            max_high_seen=exec_price,
                        )
                pending_entry = None  # one-bar order: filled or cancelled

            # --- 1c. Intrabar hard stop at the signal candle's low ------------
            if (position is not None and pending_exit is None
                    and cfg.exits.use_signal_low_stop):
                just_entered_at_close = position.entered_at_close and position.entry_index == i
                stop = position.signal_low
                if not just_entered_at_close and not np.isnan(stop) and lows[i] <= stop:
                    # Fill at the stop, or at the open if the bar gapped below it.
                    fill_raw = open_i if open_i < stop else stop
                    cash, trade = self._close_position(
                        position, fill_raw, i, dates[i], "Signal-low stop", df, cash
                    )
                    trades.append(trade)
                    position = None

            # --- 2. Evaluate EXIT at this bar's close --------------------------
            if position is not None and pending_exit is None:
                # Guard: a SIGNAL_CLOSE entry filled on *this* bar cannot also be
                # exited on the same close (we just bought at this close).
                just_entered_at_close = position.entered_at_close and position.entry_index == i
                if not just_entered_at_close:
                    reason = self._exit_reason(position, i, df)
                    if reason is not None:
                        if cfg.exit_execution == Execution.SIGNAL_CLOSE:
                            cash, trade = self._close_position(
                                position, close_i, i, dates[i], reason, df, cash
                            )
                            trades.append(trade)
                            position = None
                        else:  # NEXT_OPEN
                            pending_exit = {"reason": reason}

            # --- 3. Evaluate ENTRY signal at this bar's close ------------------
            if position is None and pending_entry is None and bool(df["entry_signal"].iat[i]):
                sig_range = float(highs[i] - lows[i])
                sig_body_low = min(float(opens[i]), close_i)
                sig_body_pct = (float(highs[i]) - sig_body_low) / sig_range if sig_range > 0 else float("nan")
                sig_atr_mult = float(df["atr_mult"].iat[i])
                signal_meta = {
                    "signal_date": dates[i],
                    "signal_close": close_i,
                    "signal_low": float(lows[i]),
                    "signal_range": sig_range,
                    "signal_body_percentile": sig_body_pct,
                    "signal_atr_mult": sig_atr_mult,
                    "rsi_at_signal": float(df["rsi"].iat[i]),
                    "pattern": str(df["pattern"].iat[i]),
                }
                if cfg.entry_execution == Execution.SIGNAL_CLOSE:
                    equity_now = cash
                    exec_price = self._buy_price(close_i)
                    shares = self._fit_to_cash(
                        self._shares_for(cash, equity_now, exec_price), exec_price, cash)
                    if shares > 0:
                        notional = shares * exec_price
                        commission = self._commission(shares, notional)
                        cash -= notional + commission
                        position = _OpenPosition(
                            shares=shares,
                            entry_price=exec_price,
                            entry_index=i,
                            entry_date=dates[i],
                            entry_commission=commission,
                            signal_date=signal_meta["signal_date"],
                            signal_close=signal_meta["signal_close"],
                            signal_low=signal_meta["signal_low"],
                            signal_range=signal_meta["signal_range"],
                            signal_body_percentile=signal_meta["signal_body_percentile"],
                            signal_atr_mult=signal_meta["signal_atr_mult"],
                            rsi_at_signal=signal_meta["rsi_at_signal"],
                            pattern=signal_meta["pattern"],
                            entered_at_close=True,
                            max_high_seen=exec_price,
                        )
                else:  # NEXT_OPEN (default, realistic)
                    pending_entry = signal_meta

            # --- 3b. Track peak high for MFE (skip entry bar for SIGNAL_CLOSE entries) --
            if position is not None:
                if not (position.entered_at_close and position.entry_index == i):
                    position.max_high_seen = max(position.max_high_seen, float(highs[i]))

            # --- 4. Mark-to-market equity at this bar's close ------------------
            position_value = position.shares * close_i if position is not None else 0.0
            equity[i] = cash + position_value

        # --- Force-close any position still open at the end of the data --------
        if position is not None:
            last = n - 1
            cash, trade = self._close_position(
                position, closes[last], last, dates[last], "End of data", df, cash
            )
            trades.append(trade)
            equity[last] = cash
            self.warnings.append(
                "A position was still open at the end of the data and was closed "
                "at the final candle's close for accounting purposes."
            )

        equity_series = pd.Series(equity, index=df.index, name="equity")
        trades_df = self._trades_to_frame(trades)
        trades_df = add_period_mfe(trades_df, df)
        return BacktestResult(
            trades=trades_df,
            equity_curve=equity_series,
            data=df,
            config=cfg,
            warnings=self.warnings,
        )

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _trades_to_frame(trades: List[Trade]) -> pd.DataFrame:
        columns = [
            "ticker", "signal_date", "signal_close", "rsi_at_signal", "signal_range",
            "signal_body_percentile", "signal_atr_mult", "pattern", "entry_date", "entry_price",
            "exit_date", "exit_price", "exit_reason", "bars_held", "gross_return", "net_return",
            "pnl", "equity_after", "mfe",
        ]
        if not trades:
            return pd.DataFrame(columns=columns)
        return pd.DataFrame([t.__dict__ for t in trades])[columns]


def add_period_mfe(
    trades_df: pd.DataFrame,
    data,
) -> pd.DataFrame:
    """Add mfe_1w … mfe_5w columns to *trades_df*.

    Each column is the maximum unrealised gain (vs entry_price) achievable in
    the first N calendar weeks after entry, independent of actual exit date.
    *data* is either a single OHLCV DataFrame (single-asset) or a
    ``{ticker: DataFrame}`` dict (multi-asset / portfolio).

    A "week" is 7 calendar days; for weekly-bar data that equals ~1 bar.
    """
    result = trades_df.copy()
    period_cols = [f"mfe_{n}w" for n in range(1, 6)]

    if result.empty:
        for col in period_cols:
            result[col] = float("nan")
        return result

    data_is_dict = isinstance(data, dict)

    def _high_series(ticker: str) -> pd.Series:
        if data_is_dict:
            df = data.get(ticker)
            return df["high"].sort_index() if df is not None and "high" in df.columns else pd.Series(dtype=float)
        return data["high"].sort_index() if "high" in data.columns else pd.Series(dtype=float)

    for n_weeks in range(1, 6):
        col = f"mfe_{n_weeks}w"
        offset = pd.DateOffset(weeks=n_weeks)
        values: list = []
        for _, row in result.iterrows():
            ticker = str(row.get("ticker", "")) if data_is_dict else ""
            highs = _high_series(ticker)
            if highs.empty:
                values.append(float("nan"))
                continue
            ep = float(row["entry_price"])
            if ep <= 0:
                values.append(float("nan"))
                continue
            entry_ts = pd.Timestamp(row["entry_date"])
            cutoff = entry_ts + offset
            window = highs.loc[entry_ts:cutoff]
            if window.empty:
                values.append(float("nan"))
            else:
                values.append((float(window.max()) - ep) / ep)
        result[col] = values
    return result
