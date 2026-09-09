import pandas as pd
import pytest

from src import screener
from src.types import StrategyConfig


def test_screening_timeframes_exclude_intraday():
    assert screener.TIMEFRAMES == {
        "Daily": ("Diário", 1),
        "Weekly": ("Semanal", 5),
        "Monthly": ("Mensal", 10),
    }


def test_get_constituents_uses_norgate_watchlist(monkeypatch):
    requested = []

    def fake_symbols(name):
        requested.append(name)
        return ["ROL", "AAPL"]

    monkeypatch.setattr(screener.norgate_loader, "get_watchlist_symbols", fake_symbols)

    assert screener.get_constituents("S&P 1500") == ["ROL", "AAPL"]
    assert requested == ["S&P Composite 1500"]


def test_fetch_ohlc_uses_norgate_total_return(monkeypatch):
    captured = {}
    expected = {"ROL": pd.DataFrame({"close": [1.0]})}

    def fake_fetch_many(tickers, **kwargs):
        captured["tickers"] = tickers
        captured.update(kwargs)
        return expected, [], []

    monkeypatch.setattr(screener.norgate_loader, "fetch_many", fake_fetch_many)

    result = screener.fetch_ohlc(["ROL"], "Diário", 1, 5)

    assert result is expected
    assert captured["tickers"] == ["ROL"]
    assert captured["adjustment_label"] == "Total Return (splits + dividendos)"
    assert captured["frequency_label"] == "Diário"
    assert captured["min_bars"] == 5


def test_evaluate_exposes_atr_multiple_and_configured_period():
    dates = pd.date_range("2024-01-01", periods=20, freq="D")
    frame = pd.DataFrame(
        {
            "open": [100.0] * 20,
            "high": [102.0] * 20,
            "low": [99.0] * 20,
            "close": [101.0] * 20,
            "volume": [1_000.0] * 20,
        },
        index=dates,
    )
    cfg = StrategyConfig()
    cfg.patterns.hammer.atr_period = 7

    result = screener.evaluate(frame, cfg, ignore_last=False)

    assert result is not None
    assert result["atr_multiple"] == 1.0
    assert result["atr_period"] == 7


def test_fetch_screen_chart_uses_selected_timeframe_and_builds_rsi(monkeypatch):
    raw = pd.DataFrame(
        {"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5]},
        index=pd.to_datetime(["2026-09-04"]),
    )
    enriched = raw.assign(rsi=[8.0])
    captured = {}

    def fake_fetch_price(ticker, **kwargs):
        captured["ticker"] = ticker
        captured.update(kwargs)
        return raw, ["chart warning"]

    def fake_build_signal_frame(frame, cfg):
        assert frame is raw
        assert cfg.rsi_period == 2
        return enriched

    monkeypatch.setattr(screener.norgate_loader, "fetch_price", fake_fetch_price)
    monkeypatch.setattr(screener, "build_signal_frame", fake_build_signal_frame)

    result, warnings = screener.fetch_screen_chart(
        "AAPL",
        "Weekly",
        StrategyConfig(),
        adjustment_label="Capital (apenas splits)",
    )

    assert result is enriched
    assert warnings == ["chart warning"]
    assert captured["ticker"] == "AAPL"
    assert captured["start_date"] == "1900-01-01"
    assert captured["frequency_label"] == "Semanal"
    assert captured["adjustment_label"] == "Capital (apenas splits)"


def test_add_historical_trade_stats_calculates_requested_columns(monkeypatch):
    frame = pd.DataFrame(
        {"open": [1.0], "high": [2.0], "low": [0.5], "close": [1.5]},
        index=pd.to_datetime(["2026-09-04"]),
    )
    trades = pd.DataFrame({
        "net_return": [0.10, -0.04, 0.20],
        "mfe_12w": [0.25, 0.10, float("nan")],
    })
    progress = []

    class FakeResult:
        def __init__(self):
            self.trades = trades

    class FakeEngine:
        def __init__(self, data, cfg):
            assert data is frame
            assert cfg.ticker == "AAPL"

        def run(self):
            return FakeResult()

    monkeypatch.setattr(
        screener,
        "fetch_screen_chart",
        lambda *args, **kwargs: (frame, ["warning"]),
    )
    monkeypatch.setattr(screener, "BacktestEngine", FakeEngine)

    enriched, details, errors = screener.add_historical_trade_stats(
        pd.DataFrame({"ticker": ["AAPL"]}),
        "Weekly",
        StrategyConfig(),
        progress=progress.append,
    )

    assert errors == []
    assert enriched.loc[0, "trade_count"] == 3
    assert enriched.loc[0, "win_rate"] == 2 / 3
    assert enriched.loc[0, "avg_gain"] == pytest.approx(0.15)
    assert enriched.loc[0, "avg_loss"] == -0.04
    assert enriched.loc[0, "mfe_12w"] == pytest.approx(0.175)
    assert details["AAPL"][1] == ["warning"]
    assert progress == [1.0]
