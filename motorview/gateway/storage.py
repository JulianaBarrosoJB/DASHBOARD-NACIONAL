"""
MotorView Gateway - armazenamento local e outbox MQTT
======================================================
- telemetria completa (2 s, configurável);
- eventos de falha;
- amostras brutas de corrente rápida (somente local);
- agregados de corrente rápida (min/max/média/última) enviados ao MQTT.

As amostras brutas de 100 ms NÃO são enviadas individualmente ao broker.
Isso preserva detalhes de pico no Raspberry sem desperdiçar tráfego MQTT.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    inverter_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    topic TEXT NOT NULL,
    sent INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_telemetry_sent ON telemetry_log(sent);
CREATE INDEX IF NOT EXISTS idx_telemetry_ts ON telemetry_log(ts);

CREATE TABLE IF NOT EXISTS fault_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    inverter_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    topic TEXT NOT NULL,
    sent INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_fault_sent ON fault_log(sent);
CREATE INDEX IF NOT EXISTS idx_fault_ts ON fault_log(ts);

CREATE TABLE IF NOT EXISTS current_sample (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    inverter_id TEXT NOT NULL,
    current_A REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_current_sample_inv_ts
    ON current_sample(inverter_id, ts);

CREATE TABLE IF NOT EXISTS fast_current_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    inverter_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    topic TEXT NOT NULL,
    sent INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_fast_current_sent ON fast_current_log(sent);
CREATE INDEX IF NOT EXISTS idx_fast_current_ts ON fast_current_log(ts);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class LocalStore:
    def __init__(
        self,
        db_path: str,
        retention_days: int = 90,
        raw_current_retention_days: int = 7,
    ):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self.raw_current_retention_days = raw_current_retention_days
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        with self._conn:
            self._conn.executescript(SCHEMA)

    def record_telemetry(self, inverter_id: str, topic: str, payload: dict) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO telemetry_log (ts, inverter_id, payload, topic, sent) VALUES (?,?,?,?,0)",
                (payload.get("ts", _utc_now_iso()), inverter_id, json.dumps(payload), topic),
            )
        return cur.lastrowid

    def record_fault(self, inverter_id: str, topic: str, payload: dict) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO fault_log (ts, inverter_id, payload, topic, sent) VALUES (?,?,?,?,0)",
                (payload.get("ts", _utc_now_iso()), inverter_id, json.dumps(payload), topic),
            )
        return cur.lastrowid

    def record_current_samples(self, samples: list[dict]) -> None:
        """Grava amostras brutas em lote para reduzir escrita na SD."""
        if not samples:
            return
        rows = [
            (s["ts"], s["inverter_id"], float(s["current_A"]))
            for s in samples
        ]
        with self._conn:
            self._conn.executemany(
                "INSERT INTO current_sample (ts, inverter_id, current_A) VALUES (?,?,?)",
                rows,
            )

    def record_fast_current(self, inverter_id: str, topic: str, payload: dict) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO fast_current_log (ts, inverter_id, payload, topic, sent) VALUES (?,?,?,?,0)",
                (payload.get("ts", _utc_now_iso()), inverter_id, json.dumps(payload), topic),
            )
        return cur.lastrowid

    def mark_sent(self, table: str, row_id: int):
        if table not in {"telemetry_log", "fault_log", "fast_current_log"}:
            raise ValueError(f"Tabela de outbox inválida: {table}")
        with self._conn:
            self._conn.execute(f"UPDATE {table} SET sent=1 WHERE id=?", (row_id,))

    def pending(self, table: str, limit: int = 200):
        if table not in {"telemetry_log", "fault_log", "fast_current_log"}:
            raise ValueError(f"Tabela de outbox inválida: {table}")
        rows = self._conn.execute(
            f"SELECT id, topic, payload FROM {table} WHERE sent=0 ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{"id": r[0], "topic": r[1], "payload": json.loads(r[2])} for r in rows]

    def purge_old(self):
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=self.retention_days)).isoformat()
        raw_cutoff = (now - timedelta(days=self.raw_current_retention_days)).isoformat()
        with self._conn:
            self._conn.execute("DELETE FROM telemetry_log WHERE ts < ? AND sent=1", (cutoff,))
            self._conn.execute("DELETE FROM fault_log WHERE ts < ? AND sent=1", (cutoff,))
            self._conn.execute("DELETE FROM fast_current_log WHERE ts < ? AND sent=1", (cutoff,))
            self._conn.execute("DELETE FROM current_sample WHERE ts < ?", (raw_cutoff,))

    def close(self):
        self._conn.close()
