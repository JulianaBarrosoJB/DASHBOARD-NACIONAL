"""
MotorView Dashboard - camada de dados
========================================
Igual à ideia do prodview/db.py: hoje fala com um SQLite local
(data/motorview.db), alimentado em tempo real pelo assinante MQTT
(mqtt_ingest.py). Quando quiser trocar por uma base persistente de
verdade (Postgres no Supabase/Neon/Railway, por exemplo - recomendado
para produção, já que o disco do Streamlit Community Cloud é apagado a
cada novo deploy/hibernação), o ponto de troca é só a função
get_conn() abaixo, mantendo os nomes de tabela/coluna (ou ajustando as
queries) - o resto do app não muda.
"""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "motorview.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS inverters (
    id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    name TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    inverter_id TEXT NOT NULL,
    current_A REAL,
    voltage_V REAL,
    dc_link_V REAL,
    frequency_Hz REAL,
    speed_rpm REAL,
    torque_pct REAL,
    status_word INTEGER,
    fault_code INTEGER,
    fault_description TEXT,
    comm_error INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_telemetry_inv_ts ON telemetry(inverter_id, ts);

CREATE TABLE IF NOT EXISTS faults (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    inverter_id TEXT NOT NULL,
    fault_code INTEGER NOT NULL,
    fault_description TEXT,
    active INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_faults_ts ON faults(ts);

CREATE TABLE IF NOT EXISTS connectivity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    site_id TEXT NOT NULL,
    status TEXT NOT NULL
);
"""


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    with conn:
        conn.executescript(SCHEMA)
    conn.close()


# ---------------------------------------------------------------------
# Ingestão (chamada pelo mqtt_ingest.py a cada mensagem MQTT recebida)
# ---------------------------------------------------------------------

def upsert_inverter(inverter_id: str, site_id: str, name: str, ts: str):
    conn = get_conn()
    with conn:
        conn.execute(
            "INSERT INTO inverters (id, site_id, name, first_seen, last_seen) VALUES (?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen, name=excluded.name",
            (inverter_id, site_id, name, ts, ts),
        )
    conn.close()


def insert_telemetry(row: dict):
    conn = get_conn()
    with conn:
        conn.execute(
            "INSERT INTO telemetry (ts, inverter_id, current_A, voltage_V, dc_link_V, frequency_Hz, "
            "speed_rpm, torque_pct, status_word, fault_code, fault_description, comm_error) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("ts"), row.get("inverter_id"), row.get("current_A"), row.get("voltage_V"),
                row.get("dc_link_V"), row.get("frequency_Hz"), row.get("speed_rpm"), row.get("torque_pct"),
                row.get("status_word"), row.get("fault_code"), row.get("fault_description"),
                1 if row.get("comm_error") else 0,
            ),
        )
    conn.close()


def insert_fault(row: dict):
    conn = get_conn()
    with conn:
        conn.execute(
            "INSERT INTO faults (ts, inverter_id, fault_code, fault_description, active) VALUES (?,?,?,?,?)",
            (row.get("ts"), row.get("inverter_id"), row.get("fault_code", 0),
             row.get("fault_description"), 1 if row.get("active") else 0),
        )
    conn.close()


def log_connectivity(site_id: str, status: str, ts: str):
    conn = get_conn()
    with conn:
        conn.execute(
            "INSERT INTO connectivity_log (ts, site_id, status) VALUES (?,?,?)",
            (ts, site_id, status),
        )
    conn.close()


def prune_old_telemetry(days: int = 30):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    conn = get_conn()
    with conn:
        conn.execute("DELETE FROM telemetry WHERE ts < ?", (cutoff,))
    conn.close()


# ---------------------------------------------------------------------
# Consultas (DataFrames prontos pro Streamlit)
# ---------------------------------------------------------------------

def df_inverters() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM inverters ORDER BY name", conn)
    conn.close()
    return df


def df_telemetry_recent(minutes: int = 60, inverter_id: str | None = None) -> pd.DataFrame:
    conn = get_conn()
    start = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    query = "SELECT t.*, i.name FROM telemetry t JOIN inverters i ON i.id = t.inverter_id WHERE t.ts >= ?"
    params = [start]
    if inverter_id:
        query += " AND t.inverter_id = ?"
        params.append(inverter_id)
    query += " ORDER BY t.ts"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None)
    return df


def df_latest_reading() -> pd.DataFrame:
    """Última leitura de cada inversor (para os cards/status em tempo real)."""
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT t.*, i.name, i.site_id FROM telemetry t "
        "JOIN inverters i ON i.id = t.inverter_id "
        "WHERE t.id IN (SELECT MAX(id) FROM telemetry GROUP BY inverter_id) "
        "ORDER BY i.name",
        conn,
    )
    conn.close()
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None)
    return df


def df_faults(days: int = 30, only_active: bool = False) -> pd.DataFrame:
    conn = get_conn()
    start = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    query = "SELECT f.*, i.name FROM faults f JOIN inverters i ON i.id = f.inverter_id WHERE f.ts >= ?"
    params = [start]
    if only_active:
        query += " AND f.active = 1"
    query += " ORDER BY f.ts DESC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None)
    return df


def df_connectivity(limit: int = 40) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM connectivity_log ORDER BY ts DESC LIMIT ?", conn, params=[limit])
    conn.close()
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_localize(None)
    return df


def kpis_now() -> dict:
    latest = df_latest_reading()
    if latest.empty:
        return {"inversores": 0, "online": 0, "falhas_ativas": 0, "corrente_total": 0.0}
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2)
    online = latest[(latest["ts"] >= cutoff) & (latest["comm_error"] == 0)]
    falhas_ativas = int((latest["fault_code"].fillna(0) > 0).sum())
    return {
        "inversores": len(latest),
        "online": len(online),
        "falhas_ativas": falhas_ativas,
        "corrente_total": round(float(online["current_A"].fillna(0).sum()), 1),
    }
