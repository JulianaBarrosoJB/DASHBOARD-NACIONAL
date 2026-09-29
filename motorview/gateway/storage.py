"""
MotorView Gateway - log local (SQLite) e fila de reenvio offline
====================================================================
Todo dado lido do inversor é sempre gravado localmente primeiro (mesmo
sem internet), e só depois publicado no MQTT. Se o broker estiver
inacessível, a linha fica marcada como "não enviada" e um flusher tenta
reenviar periodicamente - assim nenhuma leitura se perde por causa de
uma queda de link, e ainda existe um histórico local no próprio
Raspberry Pi (útil para auditoria/depuração mesmo com a nuvem no ar).
"""

import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("motorview.storage")

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
"""


class LocalStore:
    def __init__(self, db_path: str, retention_days: int = 90):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        with self._conn:
            self._conn.executescript(SCHEMA)

    def record_telemetry(self, inverter_id: str, topic: str, payload: dict) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO telemetry_log (ts, inverter_id, payload, topic, sent) VALUES (?,?,?,?,0)",
                (payload.get("ts", datetime.utcnow().isoformat()), inverter_id, json.dumps(payload), topic),
            )
        return cur.lastrowid

    def record_fault(self, inverter_id: str, topic: str, payload: dict) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO fault_log (ts, inverter_id, payload, topic, sent) VALUES (?,?,?,?,0)",
                (payload.get("ts", datetime.utcnow().isoformat()), inverter_id, json.dumps(payload), topic),
            )
        return cur.lastrowid

    def mark_sent(self, table: str, row_id: int):
        with self._conn:
            self._conn.execute(f"UPDATE {table} SET sent=1 WHERE id=?", (row_id,))

    def pending(self, table: str, limit: int = 200):
        rows = self._conn.execute(
            f"SELECT id, topic, payload FROM {table} WHERE sent=0 ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [{"id": r[0], "topic": r[1], "payload": json.loads(r[2])} for r in rows]

    def purge_old(self):
        cutoff = (datetime.utcnow() - timedelta(days=self.retention_days)).isoformat()
        with self._conn:
            self._conn.execute("DELETE FROM telemetry_log WHERE ts < ? AND sent=1", (cutoff,))
            self._conn.execute("DELETE FROM fault_log WHERE ts < ? AND sent=1", (cutoff,))

    def close(self):
        self._conn.close()
