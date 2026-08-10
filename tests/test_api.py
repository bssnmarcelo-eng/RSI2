from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from api.main import RUNS, app


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
