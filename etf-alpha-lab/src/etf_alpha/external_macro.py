from __future__ import annotations

from io import StringIO
from urllib.request import Request, urlopen

import pandas as pd

FRED_SERIES = {
    "real_rate_10y": "DFII10",
    "yield_curve": "T10Y2Y",
    "ig_spread": "BAMLC0A0CM",
    "hy_spread": "BAMLH0A0HYM2",
    "money_supply_m2": "M2SL",
}


def _fred_series(series_id: str, timeout: int = 15) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    request = Request(url, headers={"User-Agent": "ETF-Alpha-Lab/0.2 research"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed trusted FRED host
        payload = response.read().decode("utf-8")
    frame = pd.read_csv(StringIO(payload), na_values=["."])
    frame["observation_date"] = pd.to_datetime(frame["observation_date"])
    return pd.Series(
        pd.to_numeric(frame[series_id], errors="coerce").to_numpy(),
        index=frame["observation_date"],
        name=series_id,
    ).dropna()


def load_external_macro(
    start_date: str,
    end_date: str | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    series: dict[str, pd.Series] = {}
    errors: dict[str, str] = {}
    for name, series_id in FRED_SERIES.items():
        try:
            series[name] = _fred_series(series_id)
        except Exception as exc:
            errors[f"FRED:{series_id}"] = str(exc)
    frame = pd.DataFrame(series).sort_index()
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date) if end_date else None
    return frame.loc[start:end], errors
