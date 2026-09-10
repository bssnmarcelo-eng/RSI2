"""Aquisição e normalização de séries OHLCV."""
from __future__ import annotations

import io
from collections.abc import Iterable

import pandas as pd


NORGATE_ADJUSTMENTS = {
    "Total Return (splits + dividendos)": "TOTALRETURN",
    "Capital (apenas splits)": "CAPITAL",
    "Capital + dividendos especiais": "CAPITALSPECIAL",
    "Sem ajuste": "NONE",
}


def normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    """Converte uma série para colunas canônicas Open/High/Low/Close/Volume."""
    df = frame.copy()
    if isinstance(df.columns, pd.MultiIndex):
        if len(df.columns.get_level_values(-1).unique()) == 1:
            df.columns = df.columns.get_level_values(0)
        else:
            raise ValueError("A série contém mais de um ticker.")
    mapping = {str(c).strip().lower().replace(" ", "_"): c for c in df.columns}
    selected: dict[str, pd.Series] = {}
    aliases = {
        "Open": ("open",),
        "High": ("high",),
        "Low": ("low",),
        "Close": ("close", "adj_close", "adjclose"),
        "Volume": ("volume", "vol"),
    }
    for canonical, names in aliases.items():
        source = next((mapping[name] for name in names if name in mapping), None)
        if source is not None:
            selected[canonical] = pd.to_numeric(df[source], errors="coerce")
    missing = [c for c in ("Open", "High", "Low", "Close") if c not in selected]
    if missing:
        raise ValueError(f"Colunas OHLC ausentes: {', '.join(missing)}")
    if "Volume" not in selected:
        selected["Volume"] = pd.Series(0.0, index=df.index)
    result = pd.DataFrame(selected)
    result.index = pd.to_datetime(result.index, errors="coerce").tz_localize(None)
    result = result[~result.index.isna()].sort_index()
    result = result[~result.index.duplicated(keep="last")].dropna(subset=["Open", "High", "Low", "Close"])
    return result[(result[["Open", "High", "Low", "Close"]] > 0).all(axis=1)]


def download_yahoo(tickers: Iterable[str], start, end) -> dict[str, pd.DataFrame]:
    """Baixa dados ajustados do Yahoo; retorna somente séries válidas."""
    import yfinance as yf

    names = [str(t).strip().upper() for t in tickers if str(t).strip()]
    if not names:
        return {}
    raw = yf.download(
        names,
        start=pd.Timestamp(start),
        end=pd.Timestamp(end) + pd.Timedelta(days=1),
        auto_adjust=True,
        actions=False,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    result: dict[str, pd.DataFrame] = {}
    for ticker in names:
        try:
            part = raw[ticker] if isinstance(raw.columns, pd.MultiIndex) else raw
            clean = normalize_ohlcv(part)
            if not clean.empty:
                result[ticker] = clean
        except (KeyError, ValueError):
            continue
    return result


def _norgate():
    try:
        import norgatedata as nd
    except ImportError as exc:
        raise ImportError("Instale a integração com: python -m pip install norgatedata") from exc
    return nd


def norgate_status() -> tuple[bool, str]:
    """Informa se o pacote está instalado e o NDU responde localmente."""
    try:
        available = bool(_norgate().status())
        return available, "Norgate Data Updater conectado." if available else "Abra o Norgate Data Updater e atualize a base."
    except ImportError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"Norgate indisponível: {exc}"


def norgate_collections(kind: str) -> list[str]:
    """Lista watchlists ou databases existentes na instalação local."""
    nd = _norgate()
    values = nd.watchlists() if kind == "Watchlist" else nd.databases()
    return sorted(str(value) for value in (values or []))


def norgate_symbols(kind: str, name: str) -> list[str]:
    """Retorna símbolos de uma coleção Norgate."""
    nd = _norgate()
    values = nd.watchlist_symbols(name) if kind == "Watchlist" else nd.database_symbols(name)
    return sorted(str(value) for value in (values or []))


def download_norgate(
    tickers: Iterable[str],
    start,
    end,
    adjustment: str = "Total Return (splits + dividendos)",
    index_name: str | None = None,
) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Carrega séries diárias locais do NDU e relata ativos ignorados."""
    nd = _norgate()
    if not nd.status():
        raise RuntimeError("Norgate Data Updater não está disponível. Abra o NDU e tente novamente.")
    enum_name = NORGATE_ADJUSTMENTS.get(adjustment, "TOTALRETURN")
    adjustment_type = getattr(nd.StockPriceAdjustmentType, enum_name)
    frames: dict[str, pd.DataFrame] = {}
    warnings: list[str] = []
    for raw_ticker in tickers:
        ticker = str(raw_ticker).strip().upper()
        if not ticker:
            continue
        try:
            raw = nd.price_timeseries(
                ticker,
                stock_price_adjustment_setting=adjustment_type,
                padding_setting=nd.PaddingType.NONE,
                timeseriesformat="pandas-dataframe",
                interval="D",
                start_date=pd.Timestamp(start).date().isoformat(),
                end_date=pd.Timestamp(end).date().isoformat(),
            )
            if raw is None or raw.empty:
                warnings.append(f"{ticker}: sem dados no período.")
                continue
            clean = normalize_ohlcv(raw)
            if len(clean) < 20:
                warnings.append(f"{ticker}: menos de 20 barras válidas.")
                continue
            if index_name:
                try:
                    membership = nd.index_constituent_timeseries(
                        ticker,
                        index_name,
                        padding_setting=nd.PaddingType.NONE,
                        timeseriesformat="pandas-dataframe",
                        start_date=pd.Timestamp(start).date().isoformat(),
                        end_date=pd.Timestamp(end).date().isoformat(),
                    )
                    if membership is None or membership.empty:
                        clean["_member"] = False
                        warnings.append(f"{ticker}: histórico de pertencimento a {index_name} indisponível.")
                    else:
                        membership.index = pd.to_datetime(membership.index).tz_localize(None)
                        flags = pd.to_numeric(membership.iloc[:, 0], errors="coerce").fillna(0).gt(0.5)
                        clean["_member"] = flags.reindex(clean.index).ffill().fillna(False).astype(bool)
                except Exception as exc:
                    clean["_member"] = False
                    warnings.append(f"{ticker}: erro no histórico de {index_name}: {exc}")
            frames[ticker] = clean
        except Exception as exc:
            warnings.append(f"{ticker}: {exc}")
    return frames, warnings


def read_uploaded_csv(content: bytes) -> dict[str, pd.DataFrame]:
    """Lê CSV único ou multiativo com coluna ticker/symbol."""
    raw = pd.read_csv(io.BytesIO(content), sep=None, engine="python")
    raw.columns = [str(c).strip().lower().replace(" ", "_") for c in raw.columns]
    date_col = next((c for c in ("date", "datetime", "timestamp") if c in raw), None)
    if date_col is None:
        raise ValueError("O CSV precisa de uma coluna date/datetime.")
    raw[date_col] = pd.to_datetime(raw[date_col], errors="coerce")
    ticker_col = next((c for c in ("ticker", "symbol", "asset") if c in raw), None)
    groups = [("ATIVO", raw)] if ticker_col is None else raw.groupby(ticker_col)
    result: dict[str, pd.DataFrame] = {}
    for ticker, group in groups:
        indexed = group.set_index(date_col)
        result[str(ticker).upper()] = normalize_ohlcv(indexed)
    return result
