"""Ledger prospectivo append-only e verificável por encadeamento SHA-256."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import threading
from typing import Any, Iterable
from uuid import uuid4

import pandas as pd


_LEDGER_LOCK = threading.RLock()


@dataclass(slots=True)
class LedgerStatus:
    valid: bool
    records: int
    last_hash: str | None
    error: str | None = None


def _json_value(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_value)


def read_ledger(path: str | Path) -> list[dict[str, Any]]:
    ledger = Path(path)
    if not ledger.exists():
        return []
    records: list[dict[str, Any]] = []
    with ledger.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Ledger inválido na linha {line_number}: {exc}") from exc
    return records


def verify_ledger(path: str | Path) -> LedgerStatus:
    try:
        records = read_ledger(path)
        previous_hash: str | None = None
        for index, record in enumerate(records, 1):
            stored_hash = record.get("record_hash")
            content = {key: value for key, value in record.items() if key != "record_hash"}
            expected = hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()
            if record.get("previous_hash") != previous_hash:
                return LedgerStatus(False, len(records), previous_hash, f"Encadeamento inválido no registro {index}.")
            if stored_hash != expected:
                return LedgerStatus(False, len(records), previous_hash, f"Hash inválido no registro {index}.")
            previous_hash = stored_hash
        return LedgerStatus(True, len(records), previous_hash)
    except (OSError, ValueError) as exc:
        return LedgerStatus(False, 0, None, str(exc))


def append_event(
    path: str | Path,
    event_type: str,
    payload: dict[str, Any],
    *,
    event_key: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Acrescenta um evento; nunca altera nem remove registros existentes."""
    with _LEDGER_LOCK:
        ledger = Path(path)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        status = verify_ledger(ledger)
        if not status.valid:
            raise ValueError(status.error or "O ledger existente falhou na verificação.")
        records = read_ledger(ledger)
        if event_key:
            duplicate = next((record for record in records if record.get("event_key") == event_key), None)
            if duplicate is not None:
                return duplicate, False
        content = {
            "schema_version": 1,
            "event_id": str(uuid4()),
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": str(event_type),
            "event_key": event_key,
            "payload": {str(key): _json_value(value) for key, value in payload.items()},
            "previous_hash": status.last_hash,
        }
        record = {**content, "record_hash": hashlib.sha256(_canonical(content).encode("utf-8")).hexdigest()}
        with ledger.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record, True


def signal_event_key(row: dict[str, Any]) -> str:
    identity = {key: _json_value(row.get(key)) for key in ("data_sinal", "ticker", "estrategia", "direcao", "tipo_ordem", "preco_stop", "preco_limite")}
    return "signal:" + hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()


def append_signal_rows(path: str | Path, rows: Iterable[dict[str, Any]]) -> tuple[int, int]:
    added = duplicates = 0
    for row in rows:
        _, created = append_event(path, "signal", row, event_key=signal_event_key(row))
        added += int(created)
        duplicates += int(not created)
    return added, duplicates


def ledger_frame(path: str | Path) -> pd.DataFrame:
    flattened: list[dict[str, Any]] = []
    for record in read_ledger(path):
        flattened.append({
            "recorded_at_utc": record.get("recorded_at_utc"),
            "event_type": record.get("event_type"),
            "event_id": record.get("event_id"),
            "event_key": record.get("event_key"),
            **record.get("payload", {}),
            "record_hash": record.get("record_hash"),
        })
    return pd.DataFrame(flattened)
