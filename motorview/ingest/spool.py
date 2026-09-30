"""Spool SQLite durável entre MQTT e PostgreSQL."""

import hashlib
import json
import sqlite3
import threading
from pathlib import Path


class DurableSpool:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA busy_timeout=10000")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mqtt_spool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedupe_key TEXT NOT NULL UNIQUE,
                topic TEXT NOT NULL,
                payload TEXT NOT NULL,
                received_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mqtt_spool_id ON mqtt_spool(id)"
        )
        self.conn.commit()

    @staticmethod
    def _dedupe_key(topic: str, payload_text: str, received_at: str) -> str:
        try:
            payload = json.loads(payload_text)
            ts = payload.get("ts") if isinstance(payload, dict) else None
        except Exception:
            ts = None
        # Mensagens normais têm ts e ficam idempotentes em redelivery.
        # LWT usa ts=null; nesse caso cada recebimento representa um evento.
        identity = ts or received_at
        raw = f"{topic}\0{identity}\0{payload_text}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def add(self, topic: str, payload_text: str, received_at: str) -> bool:
        key = self._dedupe_key(topic, payload_text, received_at)
        with self._lock, self.conn:
            cur = self.conn.execute(
                """
                INSERT OR IGNORE INTO mqtt_spool
                    (dedupe_key, topic, payload, received_at)
                VALUES (?, ?, ?, ?)
                """,
                (key, topic, payload_text, received_at),
            )
            return cur.rowcount == 1

    def pending(self, limit: int) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT id, topic, payload, received_at
                FROM mqtt_spool
                ORDER BY id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "topic": row["topic"],
                "payload": json.loads(row["payload"]),
                "received_at": row["received_at"],
            }
            for row in rows
        ]

    def delete(self, ids: list[int]):
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self._lock, self.conn:
            self.conn.execute(
                f"DELETE FROM mqtt_spool WHERE id IN ({placeholders})",
                ids,
            )

    def count(self) -> int:
        with self._lock:
            row = self.conn.execute("SELECT COUNT(*) FROM mqtt_spool").fetchone()
            return int(row[0])

    def close(self):
        with self._lock:
            self.conn.close()
