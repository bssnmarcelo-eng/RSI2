from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from api.main import RUNS, _config, app
from api.schemas import BacktestRequest, NorgateBacktestRequest


def _candles(count: int = 40) -> list[dict]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        close = 100 + (index % 8) - (8 if index in {18, 19, 20} else 0)
        rows.append({
            "date": (start + timedelta(days=index)).isoformat(),
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 2,
            "close": close,
            "volume": 1_000_000,
        })
    return rows


def test_health_and_openapi_are_available():
    client = TestClient(app)
    assert client.get("/health").json()["status"] == "ok"
    assert "/v1/backtests" in client.get("/openapi.json").json()["paths"]


def test_backtest_job_reaches_terminal_state():
    RUNS.clear()
    client = TestClient(app)
    response = client.post("/v1/backtests/per-asset", json={
        "name": "regression",
        "mode": "per_asset",
        "assets": [{"ticker": "TEST3", "candles": _candles()}],
    })
    assert response.status_code == 202
    run = client.get(f"/v1/runs/{response.json()['id']}").json()
    assert run["status"] == "completed"
    assert "total_return" in run["metrics"]


def test_inline_synthetic_options_expose_scenarios_and_option_fields():
    RUNS.clear()
    client = TestClient(app)
    response = client.post("/v1/backtests/per-asset", json={
        "name": "options regression",
        "mode": "per_asset",
        "assets": [{"ticker": "TEST3", "candles": _candles()}],
        "strategy": {
            "instrument": "synthetic_atm_call",
            "rsi_entry": 100,
            "hammer_percentile": 1,
            "hammer_use_atr_filter": False,
            "use_max_bars": True,
            "max_bars": 3,
            "options": {"volatility_window": 3, "premium_risk_pct": 25},
        },
    })
    assert response.status_code == 202
    run = client.get(f"/v1/runs/{response.json()['id']}").json()
    assert run["status"] == "completed"
    assert run["data_summary"]["instrument"] == "synthetic_atm_call"
    assert set(run["scenario_metrics"]) == {"low", "base", "high"}
    assert set(run["scenario_equity"]) == {"low", "base", "high"}
    if run["trades"]:
        assert run["trades"][0]["option_instrument"] == "synthetic_atm_call"
        assert "option_delta_entry" in run["trades"][0]
        assert "pnl" in run["trades"][0]


def test_screening_returns_sorted_matches():
    client = TestClient(app)
    response = client.post("/v1/screenings", json={
        "assets": [{"ticker": "TEST3", "candles": _candles()}],
        "rsi_max": 100,
    })
    assert response.status_code == 200
    assert response.json()["results"][0]["ticker"] == "TEST3"


def test_optimizer_exposes_independent_split_results():
    client = TestClient(app)
    response = client.post("/v1/optimizations", json={
        "assets": [{"ticker": "TEST3", "candles": _candles(70)}],
        "parameter_ranges": {"rsi_entry_threshold": [5, 10]},
        "validation": "split",
        "min_trades": 0,
    })
    assert response.status_code == 200
    assert len(response.json()["results"]) == 2
    assert "test_sharpe" in response.json()["results"][0]


def test_api_maps_all_position_management_rules():
    request = BacktestRequest.model_validate({
        "assets": [{"ticker": "TEST3", "candles": _candles(3)}],
        "strategy": {
            "use_hammer": True,
            "hammer_percentile": 0.25,
            "hammer_require_bullish_close": True,
            "hammer_use_atr_filter": True,
            "hammer_atr_period": 21,
            "hammer_atr_multiple": 1.5,
            "use_rsi_exit": False,
            "rsi_exit": 72,
            "use_max_bars": False,
            "max_bars": 11,
            "use_profit_target": True,
            "profit_target_pct": 6.5,
            "use_stop_loss": True,
            "stop_loss_pct": 2.5,
            "use_sma_exit": True,
            "sma_period": 8,
            "use_signal_low_stop": True,
            "use_rsi_cum_exit": True,
            "rsi_cum_periods": 3,
            "rsi_cum_threshold": 115,
            "options": {
                "strike_mode": "otm_pct",
                "strike_interval": 5,
                "otm_pct": 10,
            },
        },
    })

    config = _config(request)
    exits = config.exits

    assert config.patterns.use_hammer is True
    assert config.patterns.hammer.percentile == 0.25
    assert config.patterns.hammer.require_bullish_close is True
    assert config.patterns.hammer.use_atr_filter is True
    assert config.patterns.hammer.atr_period == 21
    assert config.patterns.hammer.atr_multiple == 1.5
    assert exits.use_rsi_exit is False
    assert exits.rsi_exit_threshold == 72
    assert exits.use_max_bars is False
    assert exits.max_bars == 11
    assert exits.use_profit_target is True
    assert exits.profit_target_pct == 6.5
    assert exits.use_stop_loss is True
    assert exits.stop_loss_pct == 2.5
    assert exits.use_sma_exit is True
    assert exits.sma_period == 8
    assert exits.use_signal_low_stop is True
    assert exits.use_rsi_cum_exit is True
    assert exits.rsi_cum_periods == 3
    assert exits.rsi_cum_threshold == 115
    assert config.options.strike_mode == "otm_pct"
    assert config.options.strike_interval == 5
    assert config.options.otm_pct == 10


def test_norgate_catalog_and_symbols(monkeypatch):
    monkeypatch.setattr("api.main.norgate_loader.is_available", lambda: True)
    monkeypatch.setattr("api.main.norgate_loader.get_watchlists", lambda: ["S&P 500 Current & Past"])
    monkeypatch.setattr("api.main.norgate_loader.get_databases", lambda: ["US Equities"])
    monkeypatch.setattr("api.main.norgate_loader.get_watchlist_symbols", lambda name: ["AAPL", "MSFT"])
    client = TestClient(app)
    catalog = client.get("/v1/data-sources/norgate/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["watchlists"] == ["S&P 500 Current & Past"]
    symbols = client.get("/v1/data-sources/norgate/symbols", params={"collection_type": "watchlist", "collection_name": "S&P 500 Current & Past"})
    assert symbols.json()["symbols"] == ["AAPL", "MSFT"]


def test_norgate_backtest_loads_local_frames(monkeypatch):
    import pandas as pd

    RUNS.clear()
    frame = pd.DataFrame(_candles(40)).assign(date=lambda data: pd.to_datetime(data["date"])).set_index("date")
    monkeypatch.setattr("api.main.norgate_loader.is_available", lambda: True)
    monkeypatch.setattr("api.main.norgate_loader.get_watchlist_symbols", lambda name: ["TEST3"])
    monkeypatch.setattr("api.main.norgate_loader.fetch_many", lambda symbols, **kwargs: ({"TEST3": frame}, [], []))
    client = TestClient(app)
    response = client.post("/v1/backtests/norgate", json={
        "name": "norgate regression",
        "mode": "portfolio",
        "collection_type": "watchlist",
        "collection_name": "Teste",
        "symbols": ["TEST3"],
        "start_date": "2026-01-01",
        "end_date": "2026-03-31",
    })
    assert response.status_code == 202
    run = client.get(f"/v1/runs/{response.json()['id']}").json()
    assert run["status"] == "completed"
    assert run["source"] == "norgate"
    assert run["data_summary"]["assets_loaded"] == 1


def test_norgate_options_keep_user_frequency_and_adjustment():
    payload = {
        "collection_type": "watchlist",
        "collection_name": "Teste",
        "symbols": ["TEST3"],
        "start_date": "2026-01-01",
        "end_date": "2026-03-31",
        "frequency": "Semanal",
        "adjustment": "Total Return (splits + dividendos)",
        "strategy": {"instrument": "synthetic_atm_call"},
    }
    request = NorgateBacktestRequest.model_validate(payload)
    assert request.frequency == "Semanal"
    assert request.adjustment == "Total Return (splits + dividendos)"
    assert request.strategy.instrument == "synthetic_atm_call"


def test_norgate_options_load_weekly_signals_and_daily_pricing_separately(monkeypatch):
    import pandas as pd

    RUNS.clear()
    frame = pd.DataFrame(_candles(40)).assign(
        date=lambda data: pd.to_datetime(data["date"])
    ).set_index("date")
    calls = []

    def fetch_many(symbols, **kwargs):
        calls.append(kwargs)
        return {"TEST3": frame}, [], []

    monkeypatch.setattr("api.main.norgate_loader.is_available", lambda: True)
    monkeypatch.setattr("api.main.norgate_loader.get_watchlist_symbols", lambda name: ["TEST3"])
    monkeypatch.setattr("api.main.norgate_loader.fetch_many", fetch_many)
    client = TestClient(app)
    response = client.post("/v1/backtests/norgate", json={
        "name": "weekly option comparison",
        "mode": "per_asset",
        "collection_type": "watchlist",
        "collection_name": "Teste",
        "symbols": ["TEST3"],
        "start_date": "2026-01-01",
        "end_date": "2026-03-31",
        "frequency": "Semanal",
        "adjustment": "Total Return (splits + dividendos)",
        "strategy": {
            "instrument": "synthetic_atm_call",
            "rsi_entry": 100,
            "hammer_percentile": 1,
            "hammer_use_atr_filter": False,
            "options": {"volatility_window": 3},
        },
    })
    run = client.get(f"/v1/runs/{response.json()['id']}").json()

    assert run["status"] == "completed"
    assert calls[0]["frequency_label"] == "Semanal"
    assert calls[0]["adjustment_label"] == "Total Return (splits + dividendos)"
    assert calls[1]["frequency_label"] == "Diário"
    assert calls[1]["adjustment_label"] == "Capital (apenas splits)"
    assert run["data_summary"]["frequency"] == "Semanal"
