"""Motor causal de sinais e backtests para as estratégias do estudo."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .catalog import STRATEGIES
from .indicators import connors_rsi, historical_volatility, wilder_rsi


@dataclass(slots=True)
class StrategyConfig:
    strategy: str
    initial_capital: float = 100_000.0
    commission_model: str = "IBKR Pro Tiered"
    third_party_bps: float = 0.10
    commission_bps: float = 0.0  # custo adicional opcional; mantido para compatibilidade
    slippage_bps: float = 3.0
    execution_model: str = "Próxima abertura"
    close_open_positions_at_end: bool = False
    entry_level: float | None = None
    add_level: float | None = None
    exit_level: float | None = None
    limit_pct: float | None = None
    scale_scheme: str = "1/2/3/4"
    ma_type: str = "SMA"
    exclude_terror_outliers: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BacktestResult:
    ticker: str
    strategy: str
    trades: pd.DataFrame
    equity: pd.DataFrame
    metrics: dict[str, float]
    signals: pd.DataFrame


def _features(data: pd.DataFrame) -> pd.DataFrame:
    df = data.copy().sort_index()
    close = df["Close"]
    for n in (2, 4):
        df[f"RSI{n}"] = wilder_rsi(close, n)
    df["CRSI"] = connors_rsi(close)
    df["SMA5"] = close.rolling(5).mean()
    df["SMA10"] = close.rolling(10).mean()
    df["SMA30"] = close.rolling(30).mean()
    df["SMA200"] = close.rolling(200).mean()
    df["EMA10"] = close.ewm(span=10, adjust=False).mean()
    df["EMA30"] = close.ewm(span=30, adjust=False).mean()
    df["AVG_VOL20"] = df["Volume"].rolling(20).mean()
    df["HV100"] = historical_volatility(close, 100)
    df["HIGH252_PREV"] = df["High"].shift(1).rolling(252).max()
    df["RECENT_52W_HIGH"] = (df["High"] >= df["HIGH252_PREV"]).rolling(20).max().fillna(0).astype(bool)
    return df


def _weights(scheme: str) -> list[float]:
    return {
        "sem escala": [1.0],
        "1/1": [0.5, 0.5],
        "2/3/5": [0.2, 0.3, 0.5],
        "1/2/3/4": [0.1, 0.2, 0.3, 0.4],
    }.get(scheme, [0.1, 0.2, 0.3, 0.4])


def _params(config: StrategyConfig) -> dict[str, float]:
    defaults: dict[str, dict[str, float]] = {
        "rsi_powerzones": {"entry": 30, "add": 25, "exit": 55},
        "crash": {"entry": 90, "exit": 30, "limit": 3, "hv": 100, "volume": 1_000_000},
        "vol_panics": {"entry": 70, "exit": 20},
        "trading_new_highs": {"entry": 15, "exit": 70, "limit": 7, "volume": 1_000_000},
        "tps_long": {"entry": 25, "exit": 70, "volume": 250_000},
        "tps_short": {"entry": 75, "exit": 30, "volume": 250_000},
        "terror_gaps": {"entry": 5, "exit": 70, "limit": 1, "volume": 250_000},
    }
    p = defaults.get(config.strategy, {}).copy()
    if config.entry_level is not None:
        p["entry"] = config.entry_level
    if config.add_level is not None:
        p["add"] = config.add_level
    if config.exit_level is not None:
        p["exit"] = config.exit_level
    if config.limit_pct is not None:
        p["limit"] = config.limit_pct
    p.update({k: float(v) for k, v in config.extra.items() if isinstance(v, (int, float))})
    return p


def _signals(df: pd.DataFrame, ticker: str, config: StrategyConfig) -> pd.DataFrame:
    p = _params(config)
    s = config.strategy
    out = pd.DataFrame(index=df.index)
    out["entry"] = False
    out["add"] = False
    out["exit"] = False
    out["limit"] = np.nan
    out["direction"] = "long"

    if s == "rsi_powerzones":
        out["entry"] = (df.Close > df.SMA200) & (df.RSI4 < p["entry"])
        out["add"] = (df.Close > df.SMA200) & (df.RSI4 < p["add"])
        out["exit"] = df.RSI4 > p["exit"]
    elif s == "crash":
        setup = (df.Close > 5) & (df.AVG_VOL20 >= p["volume"]) & (df.HV100 >= p["hv"]) & (df.CRSI >= p["entry"])
        out["entry"] = setup.shift(1, fill_value=False)
        out["limit"] = df.Close.shift(1) * (1 + p["limit"] / 100)
        out["exit"] = df.CRSI < p["exit"]
        out["direction"] = "short"
    elif s == "vol_panics":
        out["entry"] = (df.Close > df.SMA5) & (df.RSI4 > p["entry"])
        out["add"] = out["entry"]
        out["exit"] = df.Close < df.SMA5
        out["direction"] = "short"
    elif s == "vxx_trend":
        fast, slow = (df.EMA10, df.EMA30) if config.ma_type.upper() == "EMA" else (df.SMA10, df.SMA30)
        out["entry"] = (fast < slow) & (fast.shift(1) >= slow.shift(1))
        out["exit"] = (fast > slow) & (fast.shift(1) <= slow.shift(1))
        out["direction"] = "short"
    elif s == "trading_new_highs":
        setup = (df.Close > 5) & (df.AVG_VOL20 > p["volume"]) & df.RECENT_52W_HIGH & (df.CRSI < p["entry"])
        out["entry"] = setup.shift(1, fill_value=False)
        out["limit"] = df.Close.shift(1) * (1 - p["limit"] / 100)
        out["exit"] = df.CRSI > p["exit"]
    elif s == "tps_long":
        out["entry"] = (df.Close > df.SMA200) & (df.RSI2 < p["entry"]) & (df.RSI2.shift(1) < p["entry"])
        out["add"] = df.Close > df.SMA200
        out["exit"] = df.RSI2 > p["exit"]
    elif s == "tps_short":
        out["entry"] = (df.Close < df.SMA200) & (df.RSI2 > p["entry"]) & (df.RSI2.shift(1) > p["entry"])
        out["add"] = df.Close < df.SMA200
        out["exit"] = df.RSI2 < p["exit"]
        out["direction"] = "short"
    elif s == "terror_gaps":
        setup = df.CRSI.shift(1) < p["entry"]
        gap = df.Open < df.Close.shift(1)
        out["entry"] = setup & gap & (df.AVG_VOL20.shift(1) > p["volume"])
        out["limit"] = df.Open * (1 - p["limit"] / 100)
        out["exit"] = df.CRSI > p["exit"]
        if config.exclude_terror_outliers:
            out.loc[out.index.normalize().isin(pd.to_datetime(["2008-10-10", "2015-08-24"])), "entry"] = False
    else:
        raise ValueError(f"Estratégia desconhecida: {s}")
    if "_member" in df:
        eligible = df["_member"].fillna(False).astype(bool)
        out["entry"] &= eligible
        out["add"] &= eligible
    return out


def _metrics(trades: pd.DataFrame, equity: pd.DataFrame, initial: float) -> dict[str, float]:
    r = trades["net_return"] if not trades.empty else pd.Series(dtype=float)
    gains, losses = r[r > 0], r[r < 0]
    curve = equity["equity"]
    dd = curve / curve.cummax() - 1
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1 / 365.25)
    final = float(curve.iloc[-1])
    return {
        "trades": float(len(trades)),
        "win_rate": float((r > 0).mean() * 100) if len(r) else 0.0,
        "avg_return": float(r.mean() * 100) if len(r) else 0.0,
        "avg_gain": float(gains.mean() * 100) if len(gains) else 0.0,
        "avg_loss": float(losses.mean() * 100) if len(losses) else 0.0,
        "profit_factor": float(gains.sum() / abs(losses.sum())) if len(losses) else (float("inf") if len(gains) else 0.0),
        "max_drawdown": float(dd.min() * 100),
        "total_return": float((final / initial - 1) * 100),
        "cagr": float(((final / initial) ** (1 / years) - 1) * 100) if final > 0 else -100.0,
        "avg_days": float(trades["bars_held"].mean()) if not trades.empty else 0.0,
    }


def _order_commission(config: StrategyConfig, shares: float, notional: float) -> float:
    """Comissão aproximada para uma ordem de ações/ETFs dos EUA."""
    shares, notional = abs(float(shares)), abs(float(notional))
    if shares == 0 or notional == 0:
        return 0.0
    if config.commission_model == "Sem comissão":
        base = 0.0
    elif config.commission_model == "IBKR Pro Fixed":
        base = max(1.00, shares * 0.005)
        base = min(base, notional * 0.01)
    else:  # primeira faixa mensal do IBKR Pro Tiered
        base = max(0.35, shares * 0.0035)
        base = min(base, notional * 0.01)
    third_party = 0.0 if config.commission_model == "Sem comissão" else notional * max(config.third_party_bps, 0.0) / 10_000
    legacy_variable = notional * max(config.commission_bps, 0.0) / 10_000
    return base + third_party + legacy_variable


def _next_bar_price(
    direction: str,
    model: str,
    signal_bar: pd.Series,
    next_bar: pd.Series,
    slippage: float,
) -> float | None:
    """Preço causal de D+1 para sinal conhecido após o fechamento de D.

    No modelo de rompimento, um gap que ultrapassa o gatilho não é preenchido
    automaticamente: a ordem só executa se a barra retornar ao preço-limite.
    Esse comportamento corresponde, operacionalmente, a uma stop-limit DAY.
    """
    if model == "Próxima abertura":
        return float(next_bar.Open) * (1 + slippage if direction == "long" else 1 - slippage)
    if direction == "long":
        trigger = float(signal_bar.High)
        entry_price = trigger * (1 + slippage)
        if next_bar.Open > trigger:
            return entry_price if next_bar.Low < trigger else None
        if next_bar.High >= trigger:
            return entry_price
    else:
        trigger = float(signal_bar.Low)
        entry_price = trigger * (1 - slippage)
        if next_bar.Open < trigger:
            return entry_price if next_bar.High > trigger else None
        if next_bar.Low <= trigger:
            return entry_price
    return None


def run_backtest(data: pd.DataFrame, ticker: str, config: StrategyConfig) -> BacktestResult:
    """Executa um backtest sem look-ahead, com uma posição por ativo."""
    df = _features(data)
    sig = _signals(df, ticker, config)
    direction = str(sig["direction"].iloc[-1])
    weights = [1.0] if config.strategy in {"crash", "vxx_trend", "trading_new_highs", "terror_gaps"} else _weights(config.scale_scheme)
    if config.strategy == "rsi_powerzones" and len(weights) > 2:
        weights = [0.5, 0.5]
    slip = config.slippage_bps / 10_000
    capital = config.initial_capital
    equity_values = pd.Series(capital, index=df.index, dtype=float)
    position: dict[str, Any] | None = None
    rows: list[dict[str, Any]] = []

    close_signal_strategies = {"rsi_powerzones", "vol_panics", "vxx_trend", "tps_long", "tps_short"}

    for i, (date, bar) in enumerate(df.iterrows()):
        signal = sig.loc[date]
        previous_signal = sig.iloc[i - 1] if i > 0 else None
        previous_bar = df.iloc[i - 1] if i > 0 else None

        # Sinais de saída confirmados em D só podem ser executados em D+1.
        if position is not None and previous_signal is not None and bool(previous_signal.exit):
            px = float(bar.Open) * (1 - slip if direction == "long" else 1 + slip)
            invested = sum(position["weights"])
            avg_entry = float(np.average(position["prices"], weights=position["weights"]))
            side = 1 if direction == "long" else -1
            base_capital = position["capital"]
            gross_pnl = sum(base_capital * weight * (px / entry - 1) * side for entry, weight in zip(position["prices"], position["weights"]))
            total_shares = sum(base_capital * weight / entry for entry, weight in zip(position["prices"], position["weights"]))
            total_commission = sum(position["commissions"]) + _order_commission(config, total_shares, total_shares * px)
            pnl = gross_pnl - total_commission
            gross = gross_pnl / (base_capital * invested)
            net = pnl / (base_capital * invested)
            portfolio_return = pnl / base_capital
            capital += pnl
            rows.append({"ticker": ticker, "strategy": STRATEGIES[config.strategy]["name"], "signal_date": position["signal_date"], "entry_date": position["date"], "exit_signal_date": df.index[i - 1], "exit_date": date, "direction": direction, "execution_model": position["execution_model"], "tranches": len(position["prices"]), "tranche_dates": position["dates"].copy(), "tranche_prices": position["prices"].copy(), "tranche_weights": position["weights"].copy(), "invested_fraction": invested, "avg_entry": avg_entry, "exit_price": px, "gross_return": gross, "net_return": net, "portfolio_return": portfolio_return, "commission": total_commission, "bars_held": i - position["index"], "pnl": pnl, "forced_exit": False})
            position = None

        # Estratégias originalmente acionadas no fechamento agora entram em D+1.
        if position is None and config.strategy in close_signal_strategies and previous_signal is not None and bool(previous_signal.entry):
            px = _next_bar_price(direction, config.execution_model, previous_bar, bar, slip)
            if px is not None:
                notional = capital * weights[0]
                position = {"signal_date": df.index[i - 1], "date": date, "index": i, "capital": capital, "dates": [date], "prices": [px], "weights": [weights[0]], "commissions": [_order_commission(config, notional / px, notional)], "execution_model": config.execution_model}

        # CRASH, Trading New Highs e Terror Gaps já possuem ordem intradiária própria.
        if position is None and config.strategy not in close_signal_strategies and bool(signal.entry):
            is_limit = np.isfinite(signal["limit"])
            limit = float(signal["limit"]) if is_limit else np.nan
            filled = (bar.High >= limit) if direction == "short" and is_limit else (bar.Low <= limit) if is_limit else True
            if filled:
                px = limit if is_limit else float(bar.Close) * (1 + slip if direction == "long" else 1 - slip)
                notional = capital * weights[0]
                signal_date = df.index[i - 1] if config.strategy in {"crash", "trading_new_highs"} and i > 0 else date
                position = {"signal_date": signal_date, "date": date, "index": i, "capital": capital, "dates": [date], "prices": [px], "weights": [weights[0]], "commissions": [_order_commission(config, notional / px, notional)], "execution_model": "Limite da estratégia"}

        # O fechamento de D autoriza a próxima parcela; a execução ocorre em D+1.
        if position is not None and position["index"] < i and previous_signal is not None and len(position["prices"]) < len(weights) and bool(previous_signal.add):
            prior = position["prices"][-1]
            favorable_for_add = previous_bar.Close < prior if direction == "long" else previous_bar.Close > prior
            if favorable_for_add:
                px = _next_bar_price(direction, config.execution_model, previous_bar, bar, slip)
                if px is not None:
                    position["prices"].append(px)
                    position["dates"].append(date)
                    weight = weights[len(position["prices"]) - 1]
                    position["weights"].append(weight)
                    notional = position["capital"] * weight
                    position["commissions"].append(_order_commission(config, notional / px, notional))

        # Marcação diária a mercado, incluindo custos de entrada já incorridos.
        if position is None:
            equity_values.loc[date] = capital
        else:
            side = 1 if direction == "long" else -1
            open_pnl = sum(position["capital"] * weight * (float(bar.Close) / entry - 1) * side for entry, weight in zip(position["prices"], position["weights"]))
            equity_values.loc[date] = capital + open_pnl - sum(position["commissions"])

    if position is not None and config.close_open_positions_at_end:
        date, bar = df.index[-1], df.iloc[-1]
        px = float(bar.Close) * (1 - slip if direction == "long" else 1 + slip)
        invested = sum(position["weights"])
        avg_entry = float(np.average(position["prices"], weights=position["weights"]))
        side = 1 if direction == "long" else -1
        base_capital = position["capital"]
        gross_pnl = sum(base_capital * weight * (px / entry - 1) * side for entry, weight in zip(position["prices"], position["weights"]))
        total_shares = sum(base_capital * weight / entry for entry, weight in zip(position["prices"], position["weights"]))
        total_commission = sum(position["commissions"]) + _order_commission(config, total_shares, total_shares * px)
        pnl = gross_pnl - total_commission
        gross = gross_pnl / (base_capital * invested)
        net = pnl / (base_capital * invested)
        capital += pnl
        equity_values.loc[date] = capital
        rows.append({"ticker": ticker, "strategy": STRATEGIES[config.strategy]["name"], "signal_date": position["signal_date"], "entry_date": position["date"], "exit_signal_date": pd.NaT, "exit_date": date, "direction": direction, "execution_model": position["execution_model"], "tranches": len(position["prices"]), "tranche_dates": position["dates"].copy(), "tranche_prices": position["prices"].copy(), "tranche_weights": position["weights"].copy(), "invested_fraction": invested, "avg_entry": avg_entry, "exit_price": px, "gross_return": gross, "net_return": net, "portfolio_return": pnl / base_capital, "commission": total_commission, "bars_held": len(df) - 1 - position["index"], "pnl": pnl, "forced_exit": True})

    trades = pd.DataFrame(rows)
    equity = pd.DataFrame({"equity": equity_values.ffill()})
    visible = pd.concat([df[["Close", "RSI2", "RSI4", "CRSI"]], sig], axis=1)
    return BacktestResult(ticker, config.strategy, trades, equity, _metrics(trades, equity, config.initial_capital), visible)


def screen_latest(data: pd.DataFrame, ticker: str, configs: list[StrategyConfig]) -> list[dict[str, Any]]:
    """Prepara apenas ações que ainda podem ser executadas após a última barra."""
    df = _features(data)
    if df.empty:
        return []
    date, bar = df.index[-1], df.iloc[-1]
    rows: list[dict[str, Any]] = []
    for config in configs:
        sig = _signals(df, ticker, config)
        last = sig.iloc[-1]
        p = _params(config)
        action = None
        order_type = None
        trigger = np.nan
        limit_price = np.nan
        eligible = bool(bar.get("_member", True))

        # Estes setups são conhecidos no fechamento de hoje e geram uma ordem
        # limitada válida exclusivamente para a próxima sessão.
        if config.strategy == "crash":
            setup_now = eligible and bar.Close > 5 and bar.AVG_VOL20 >= p["volume"] and bar.HV100 >= p["hv"] and bar.CRSI >= p["entry"]
            if setup_now:
                action = "Agendar venda limitada para a próxima sessão"
                order_type = "SELL LMT"
                trigger = limit_price = float(bar.Close) * (1 + p["limit"] / 100)
        elif config.strategy == "trading_new_highs":
            setup_now = eligible and bar.Close > 5 and bar.AVG_VOL20 > p["volume"] and bool(bar.RECENT_52W_HIGH) and bar.CRSI < p["entry"]
            if setup_now:
                action = "Agendar compra limitada para a próxima sessão"
                order_type = "BUY LMT"
                trigger = limit_price = float(bar.Close) * (1 - p["limit"] / 100)
        elif config.strategy == "terror_gaps":
            setup_now = eligible and bar.CRSI < p["entry"] and bar.AVG_VOL20 > p["volume"]
            if setup_now:
                action = f"Monitorar gap de baixa; se ocorrer, comprar {p['limit']:.2f}% abaixo da abertura"
                order_type = "COND BUY LMT"
        elif bool(last.entry):
            if config.execution_model == "Próxima abertura":
                action = "Agendar para a próxima abertura"
                order_type = "MKT"
            else:
                action = "Agendar rompimento para a próxima sessão"
                order_type = "BUY STP LMT" if last.direction == "long" else "SELL STP LMT"
                trigger = float(bar.High if last.direction == "long" else bar.Low)
                slip = config.slippage_bps / 10_000
                limit_price = trigger * (1 + slip if last.direction == "long" else 1 - slip)
        if action:
            strategy_weights = [1.0] if config.strategy in {"crash", "vxx_trend", "trading_new_highs", "terror_gaps"} else _weights(config.scale_scheme)
            if config.strategy == "rsi_powerzones" and len(strategy_weights) > 2:
                strategy_weights = [0.5, 0.5]
            if config.strategy in {"rsi_powerzones", "vol_panics"}:
                raw_strength = p["entry"] - float(bar.RSI4) if config.strategy == "rsi_powerzones" else float(bar.RSI4) - p["entry"]
            elif config.strategy in {"tps_long", "tps_short"}:
                raw_strength = p["entry"] - float(bar.RSI2) if config.strategy == "tps_long" else float(bar.RSI2) - p["entry"]
            elif config.strategy in {"crash", "trading_new_highs", "terror_gaps"}:
                raw_strength = p["entry"] - float(bar.CRSI) if config.strategy != "crash" else float(bar.CRSI) - p["entry"]
            else:
                raw_strength = 0.0
            rows.append({"data_sinal": date.date(), "ticker": ticker, "estrategia": STRATEGIES[config.strategy]["name"], "direcao": str(last.direction), "acao": action, "tipo_ordem": order_type, "preco_stop": round(trigger, 4) if np.isfinite(trigger) and "STP" in order_type else np.nan, "preco_limite": round(limit_price, 4) if np.isfinite(limit_price) else np.nan, "validade": "DAY", "parcela_inicial": strategy_weights[0], "forca_sinal": round(raw_strength, 4) if np.isfinite(raw_strength) else np.nan, "fechamento": round(float(bar.Close), 4), "RSI2": round(float(bar.RSI2), 2) if pd.notna(bar.RSI2) else np.nan, "RSI4": round(float(bar.RSI4), 2) if pd.notna(bar.RSI4) else np.nan, "ConnorsRSI": round(float(bar.CRSI), 2) if pd.notna(bar.CRSI) else np.nan})
    return rows
