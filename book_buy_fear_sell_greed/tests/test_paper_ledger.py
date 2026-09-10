import json

from fear_greed.paper_ledger import append_event, append_signal_rows, read_ledger, verify_ledger


def test_ledger_is_append_only_idempotent_and_hash_chained(tmp_path):
    path = tmp_path / "paper.jsonl"
    rows = [{"data_sinal": "2026-09-10", "ticker": "SPY", "estrategia": "TPS", "direcao": "long", "tipo_ordem": "MKT", "preco_stop": None, "preco_limite": None}]
    assert append_signal_rows(path, rows) == (1, 0)
    assert append_signal_rows(path, rows) == (0, 1)
    append_event(path, "order_staged", {"ticker": "SPY", "transmit": False}, event_key="order:1")
    status = verify_ledger(path)
    assert status.valid
    assert status.records == 2
    assert len(read_ledger(path)) == 2


def test_ledger_detects_tampering(tmp_path):
    path = tmp_path / "paper.jsonl"
    append_event(path, "fill", {"ticker": "SPY", "price": 100})
    record = json.loads(path.read_text(encoding="utf-8"))
    record["payload"]["price"] = 1
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    status = verify_ledger(path)
    assert not status.valid
    assert "Hash inválido" in status.error
