import pandas as pd

from src import screener


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
