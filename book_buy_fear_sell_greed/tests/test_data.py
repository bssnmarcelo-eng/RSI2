import sys
from types import SimpleNamespace

import pandas as pd

from fear_greed.data import download_norgate, norgate_collections, norgate_status, norgate_symbols


class FakeNorgate:
    StockPriceAdjustmentType = SimpleNamespace(TOTALRETURN="total", CAPITAL="capital", CAPITALSPECIAL="special", NONE="none")
    PaddingType = SimpleNamespace(NONE="none")

    @staticmethod
    def status():
        return True

    @staticmethod
    def watchlists():
        return ["S&P 500 Current & Past"]

    @staticmethod
    def databases():
        return ["US Equities"]

    @staticmethod
    def watchlist_symbols(name):
        return ["SPY", "QQQ"]

    @staticmethod
    def database_symbols(name):
        return ["MSFT", "AAPL"]

    @staticmethod
    def price_timeseries(symbol, **kwargs):
        idx = pd.bdate_range("2024-01-01", periods=30)
        return pd.DataFrame({"Open": 100, "High": 101, "Low": 99, "Close": 100, "Volume": 1_000_000}, index=idx)

    @staticmethod
    def index_constituent_timeseries(symbol, name, **kwargs):
        idx = pd.bdate_range("2024-01-01", periods=30)
        return pd.DataFrame({"Index Constituent": [0] * 10 + [1] * 20}, index=idx)


def test_norgate_adapter(monkeypatch):
    monkeypatch.setitem(sys.modules, "norgatedata", FakeNorgate)
    assert norgate_status()[0]
    assert norgate_collections("Watchlist") == ["S&P 500 Current & Past"]
    assert norgate_symbols("Database", "US Equities") == ["AAPL", "MSFT"]
    frames, warnings = download_norgate(["SPY"], "2024-01-01", "2024-12-31")
    assert not warnings
    assert list(frames["SPY"].columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(frames["SPY"]) == 30


def test_norgate_point_in_time_membership(monkeypatch):
    monkeypatch.setitem(sys.modules, "norgatedata", FakeNorgate)
    frames, warnings = download_norgate(["SPY"], "2024-01-01", "2024-12-31", index_name="S&P 500")
    assert not warnings
    assert frames["SPY"]["_member"].sum() == 20
