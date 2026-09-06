from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import pandas as pd

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")
LEADING_INDICATORS = {
    "pmi": "#NAPMI",
    "jobless_claims": "#INJOB",
    "yield_curve": "#US10Y-2Y",
    "financial_conditions": "#NFCI",
    "activity": "#CFNAI",
    "industrial_production_yoy": "#INDSA3",
    "housing_starts_yoy": "#HOSSA3",
    "inflation_yoy": "#CPIUN3",
}


def configure_norgate_root(path: str | Path) -> Path:
    root = Path(path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("NORGATEDATA_ROOT", str(root))
    return root


def norgate_status() -> bool:
    try:
        import norgatedata as nd

        return bool(nd.status())
    except Exception:
        return False


def is_etf(symbol: str) -> bool:
    import norgatedata as nd

    return nd.subtype1(symbol) == "Exchange Traded Product" and nd.subtype2(symbol) == "Exchange Traded Fund (ETF)"


def validate_etfs(symbols: Iterable[str]) -> tuple[list[str], dict[str, str]]:
    valid: list[str] = []
    rejected: dict[str, str] = {}
    import norgatedata as nd

    for raw in dict.fromkeys(symbols):
        symbol = raw.strip().upper()
        if not symbol:
            continue
        try:
            if is_etf(symbol):
                valid.append(symbol)
            else:
                rejected[symbol] = f"{nd.subtype1(symbol)} / {nd.subtype2(symbol)}"
        except Exception as exc:
            rejected[symbol] = str(exc)
    return valid, rejected


def load_norgate(
    symbols: Iterable[str], start_date: str, end_date: str | None = None
) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    import norgatedata as nd

    frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    kwargs = {
        "stock_price_adjustment_setting": nd.StockPriceAdjustmentType.TOTALRETURN,
        "padding_setting": nd.PaddingType.NONE,
        "timeseriesformat": "pandas-dataframe",
        "interval": "D",
        "start_date": start_date,
    }
    if end_date:
        kwargs["end_date"] = end_date
    for symbol in symbols:
        try:
            raw = nd.price_timeseries(symbol, **kwargs)
            if raw is None or raw.empty:
                raise ValueError("sem dados")
            frame = raw.copy()
            frame.index = pd.to_datetime(frame.index)
            frame.columns = [str(column).lower() for column in frame.columns]
            frame = frame.loc[:, [column for column in REQUIRED_COLUMNS if column in frame.columns]]
            frame = frame.apply(pd.to_numeric, errors="coerce")
            frame = frame.dropna(subset=["open", "close"])
            frame = frame[(frame["open"] > 0) & (frame["close"] > 0)]
            if len(frame) < 260:
                raise ValueError(f"histórico insuficiente ({len(frame)} barras)")
            frames[symbol] = frame
        except Exception as exc:
            errors[symbol] = str(exc)
    return frames, errors


def price_panels(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    opens = pd.concat({symbol: frame["open"] for symbol, frame in frames.items()}, axis=1).sort_index()
    closes = pd.concat({symbol: frame["close"] for symbol, frame in frames.items()}, axis=1).sort_index()
    return opens.ffill(limit=3), closes.ffill(limit=3)


def load_leading_indicators(start_date: str, end_date: str | None = None) -> tuple[pd.DataFrame, dict[str, str]]:
    """Load Norgate economic series used only as lagged signals, never as tradable assets."""
    import norgatedata as nd

    series: dict[str, pd.Series] = {}
    errors: dict[str, str] = {}
    kwargs = {
        "padding_setting": nd.PaddingType.NONE,
        "timeseriesformat": "pandas-dataframe",
        "interval": "D",
        "start_date": start_date,
    }
    if end_date:
        kwargs["end_date"] = end_date
    for name, symbol in LEADING_INDICATORS.items():
        try:
            raw = nd.price_timeseries(symbol, **kwargs)
            if raw is None or raw.empty:
                raise ValueError("sem dados")
            columns = {str(column).lower(): column for column in raw.columns}
            values = pd.to_numeric(raw[columns.get("close", raw.columns[-1])], errors="coerce")
            values.index = pd.to_datetime(values.index)
            series[name] = values
        except Exception as exc:
            errors[symbol] = str(exc)
    return pd.DataFrame(series).sort_index(), errors


def merge_macro_sources(norgate: pd.DataFrame, external: pd.DataFrame) -> pd.DataFrame:
    """External series take precedence; Norgate fills unavailable licensed history."""
    combined = norgate.copy()
    if "pmi" in combined and "ism_manufacturing" not in external:
        combined["ism_manufacturing"] = combined["pmi"]
    for column in external:
        combined[column] = external[column].reindex(combined.index.union(external.index))
    return combined.sort_index()
