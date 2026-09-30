"""Persistência PostgreSQL/Neon para o MotorView ingest worker."""

import json
import logging
from datetime import datetime, timezone

import psycopg

log = logging.getLogger("motorview.ingest.db")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class MotorViewDatabase:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.conn = None

    def connect(self):
        self.close()
        self.conn = psycopg.connect(
            self.database_url,
            autocommit=True,
            connect_timeout=10,
            application_name="motorview-ingest",
        )
        with self.conn.cursor() as cur:
            cur.execute("SELECT current_user, current_database()")
            user, database = cur.fetchone()
        log.info("PostgreSQL conectado: database=%s user=%s", database, user)

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    def ensure_connection(self):
        if self.conn is None or self.conn.closed:
            self.connect()

    def process(self, topic: str, payload: dict, received_at: str):
        self.ensure_connection()

        parts = topic.split("/")
        if len(parts) < 3 or parts[0] != "motorview":
            return

        site_id = parts[1]

        if len(parts) == 4 and parts[2] == "gateway" and parts[3] == "status":
            self._insert_connectivity(site_id, payload, received_at)
            return

        if len(parts) != 4:
            return

        inverter_id, kind = parts[2], parts[3]
        ts = payload.get("ts") or received_at

        # Mantém o cadastro sincronizado com o nome publicado pelo gateway.
        self._upsert_inverter(
            site_id,
            inverter_id,
            payload.get("name") or inverter_id,
        )

        if kind == "telemetry":
            self._insert_telemetry(site_id, inverter_id, ts, payload, received_at)
        elif kind == "current_fast":
            self._insert_current_fast(site_id, inverter_id, ts, payload, received_at)
        elif kind == "fault":
            self._insert_fault(site_id, inverter_id, ts, payload, received_at)

    def _upsert_inverter(self, site_id: str, inverter_id: str, name: str):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO motorview.inverters
                    (site_id, inverter_id, name, active)
                VALUES (%s, %s, %s, TRUE)
                ON CONFLICT (site_id, inverter_id)
                DO UPDATE SET
                    name = EXCLUDED.name,
                    active = TRUE,
                    updated_at = NOW()
                """,
                (site_id, inverter_id, name),
            )

    def _insert_telemetry(
        self, site_id: str, inverter_id: str, ts: str, p: dict, received_at: str
    ):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO motorview.telemetry (
                    site_id, inverter_id, ts, comm_error,
                    speed_rpm, current_a, dc_link_v, frequency_hz,
                    voltage_v, torque_pct, status_word, fault_code,
                    last_fault_code, last_fault_description,
                    last_fault_current_a, last_fault_dc_link_v,
                    last_fault_frequency_hz, last_fault_igbt_temp_c,
                    last_fault_status_word,
                    second_fault_code, second_fault_description,
                    third_fault_code, third_fault_description,
                    status_bits, payload, received_at
                )
                VALUES (
                    %s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s,%s,
                    %s,%s,%s,
                    %s,%s,%s,%s,
                    %s::jsonb,%s::jsonb,%s
                )
                ON CONFLICT (site_id, inverter_id, ts) DO NOTHING
                """,
                (
                    site_id, inverter_id, ts, bool(p.get("comm_error", False)),
                    p.get("speed_rpm"), p.get("current_A"), p.get("dc_link_V"),
                    p.get("frequency_Hz"), p.get("voltage_V"), p.get("torque_pct"),
                    p.get("status_word"), p.get("fault_code"),
                    p.get("last_fault_code"), p.get("last_fault_description"),
                    p.get("last_fault_current_A"), p.get("last_fault_dc_link_V"),
                    p.get("last_fault_frequency_Hz"), p.get("last_fault_igbt_temp_C"),
                    p.get("last_fault_status_word"), p.get("second_fault_code"),
                    p.get("second_fault_description"), p.get("third_fault_code"),
                    p.get("third_fault_description"),
                    json.dumps(p.get("status_bits")) if p.get("status_bits") is not None else None,
                    json.dumps(p, ensure_ascii=False),
                    received_at,
                ),
            )

    def _insert_current_fast(
        self, site_id: str, inverter_id: str, ts: str, p: dict, received_at: str
    ):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO motorview.current_fast (
                    site_id, inverter_id, ts, window_start, window_end,
                    current_a, current_min_a, current_max_a, current_avg_a,
                    samples, sample_interval_ms, payload, received_at
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                ON CONFLICT (site_id, inverter_id, ts) DO NOTHING
                """,
                (
                    site_id, inverter_id, ts, p.get("window_start"), p.get("window_end"),
                    p.get("current_A"), p.get("current_min_A"), p.get("current_max_A"),
                    p.get("current_avg_A"), p.get("samples"), p.get("sample_interval_ms"),
                    json.dumps(p, ensure_ascii=False), received_at,
                ),
            )

    def _insert_fault(
        self, site_id: str, inverter_id: str, ts: str, p: dict, received_at: str
    ):
        active = bool(p.get("active", int(p.get("fault_code") or 0) != 0))
        event_type = "fault_active" if active else "fault_cleared"
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO motorview.faults (
                    site_id, inverter_id, ts, fault_code, fault_description,
                    event_type, current_a, dc_link_v, frequency_hz,
                    igbt_temp_c, status_word, payload, received_at
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                ON CONFLICT (site_id, inverter_id, ts, fault_code, event_type)
                DO NOTHING
                """,
                (
                    site_id, inverter_id, ts, int(p.get("fault_code") or 0),
                    p.get("fault_description"), event_type,
                    p.get("current_A"), p.get("dc_link_V"), p.get("frequency_Hz"),
                    p.get("last_fault_igbt_temp_C"), p.get("status_word"),
                    json.dumps(p, ensure_ascii=False), received_at,
                ),
            )

    def _insert_connectivity(self, site_id: str, p: dict, received_at: str):
        # LWT do gateway publica ts=null: nesse caso o horário de recebimento
        # pelo worker é a melhor referência disponível.
        ts = p.get("ts") or received_at
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO motorview.connectivity (
                    site_id, ts, source, status, message, payload, received_at
                )
                VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s)
                """,
                (
                    site_id, ts, p.get("source") or "mqtt",
                    p.get("status") or "unknown", p.get("message"),
                    json.dumps(p, ensure_ascii=False), received_at,
                ),
            )
