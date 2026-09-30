"""MotorView Dashboard - leitura PostgreSQL/Neon.

O dashboard é somente leitura. A ingestão MQTT roda fora do Streamlit e grava
no schema motorview; esta camada consulta esse schema usando DATABASE_URL.
"""

from datetime import datetime, timedelta, timezone
import threading

import pandas as pd
from psycopg_pool import ConnectionPool

import config

_pool = None
_pool_lock = threading.Lock()


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                url = config.database_url()
                if not url:
                    raise RuntimeError("DATABASE_URL não configurada")
                _pool = ConnectionPool(
                    conninfo=url,
                    min_size=0,
                    max_size=4,
                    timeout=10,
                    kwargs={
                        "autocommit": True,
                        "connect_timeout": 10,
                        "application_name": "motorview-dashboard",
                    },
                )
    return _pool


def _query(sql: str, params=()) -> pd.DataFrame:
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description] if cur.description else []
            rows = cur.fetchall() if cols else []
    return pd.DataFrame(rows, columns=cols)


def _naive_utc(df: pd.DataFrame, *cols: str) -> pd.DataFrame:
    if df.empty:
        return df
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True).dt.tz_localize(None)
    return df


def init_db():
    """Valida a conexão. O dashboard não cria nem altera tabelas."""
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()


def database_status() -> dict:
    """Estado do Neon + idade da telemetria mais recente."""
    try:
        df = _query("SELECT MAX(ts) AS latest_ts FROM motorview.telemetry")
        latest = None if df.empty else df.iloc[0]["latest_ts"]
        if pd.isna(latest):
            latest = None
        fresh = False
        if latest is not None:
            latest_utc = pd.Timestamp(latest)
            if latest_utc.tzinfo is None:
                latest_utc = latest_utc.tz_localize("UTC")
            else:
                latest_utc = latest_utc.tz_convert("UTC")
            fresh = (pd.Timestamp.now(tz="UTC") - latest_utc) <= pd.Timedelta(minutes=2)
        return {"connected": True, "fresh": bool(fresh), "latest_ts": latest, "error": None}
    except Exception as exc:
        return {"connected": False, "fresh": False, "latest_ts": None, "error": str(exc)}


def df_inverters() -> pd.DataFrame:
    return _query("""
        SELECT inverter_id AS id, inverter_id, site_id, name, active, created_at, updated_at
        FROM motorview.inverters
        WHERE active = TRUE
        ORDER BY name
    """)


_TELEMETRY_SELECT = """
    t.id, t.site_id, t.inverter_id, t.ts,
    t.current_a AS "current_A",
    t.voltage_v AS "voltage_V",
    t.dc_link_v AS "dc_link_V",
    t.frequency_hz AS "frequency_Hz",
    t.speed_rpm, t.torque_pct, t.status_word, t.fault_code,
    COALESCE(t.payload->>'fault_description', '') AS fault_description,
    t.last_fault_code, t.last_fault_description,
    t.last_fault_current_a AS "last_fault_current_A",
    t.last_fault_dc_link_v AS "last_fault_dc_link_V",
    t.last_fault_frequency_hz AS "last_fault_frequency_Hz",
    t.last_fault_igbt_temp_c AS "last_fault_igbt_temp_C",
    t.last_fault_status_word,
    t.second_fault_code, t.second_fault_description,
    t.third_fault_code, t.third_fault_description,
    t.comm_error, i.name
"""


def df_telemetry_recent(minutes: int = 60, inverter_id: str | None = None) -> pd.DataFrame:
    start = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    sql = f"""
        SELECT {_TELEMETRY_SELECT}
        FROM motorview.telemetry t
        JOIN motorview.inverters i
          ON i.site_id=t.site_id AND i.inverter_id=t.inverter_id
        WHERE t.ts >= %s
    """
    params = [start]
    if inverter_id:
        sql += " AND t.inverter_id = %s"
        params.append(inverter_id)
    sql += " ORDER BY t.ts"
    return _naive_utc(_query(sql, params), "ts")


def df_fast_current_recent(minutes: int = 15, inverter_id: str | None = None) -> pd.DataFrame:
    start = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    sql = """
        SELECT f.id, f.site_id, f.inverter_id, f.ts, f.window_start, f.window_end,
               f.current_a AS "current_A",
               f.current_min_a AS "current_min_A",
               f.current_max_a AS "current_max_A",
               f.current_avg_a AS "current_avg_A",
               f.samples, f.sample_interval_ms, i.name
        FROM motorview.current_fast f
        JOIN motorview.inverters i
          ON i.site_id=f.site_id AND i.inverter_id=f.inverter_id
        WHERE f.ts >= %s
    """
    params = [start]
    if inverter_id:
        sql += " AND f.inverter_id = %s"
        params.append(inverter_id)
    sql += " ORDER BY f.ts"
    return _naive_utc(_query(sql, params), "ts", "window_start", "window_end")


def df_latest_reading() -> pd.DataFrame:
    df = _query(f"""
        SELECT {_TELEMETRY_SELECT}
        FROM motorview.telemetry t
        JOIN motorview.inverters i
          ON i.site_id=t.site_id AND i.inverter_id=t.inverter_id
        JOIN (
            SELECT site_id, inverter_id, MAX(ts) AS max_ts
            FROM motorview.telemetry
            GROUP BY site_id, inverter_id
        ) latest
          ON latest.site_id=t.site_id
         AND latest.inverter_id=t.inverter_id
         AND latest.max_ts=t.ts
        ORDER BY i.name
    """)
    return _naive_utc(df, "ts")


def df_faults(days: int = 30, only_active: bool = False) -> pd.DataFrame:
    start = datetime.now(timezone.utc) - timedelta(days=days)
    sql = """
        SELECT f.id, f.site_id, f.inverter_id, f.ts, f.fault_code,
               f.fault_description,
               CASE WHEN f.event_type='fault_active' THEN 1 ELSE 0 END AS active,
               f.event_type,
               f.current_a AS "current_A",
               f.dc_link_v AS "dc_link_V",
               f.frequency_hz AS "frequency_Hz",
               f.igbt_temp_c AS "igbt_temp_C",
               f.status_word, i.name
        FROM motorview.faults f
        JOIN motorview.inverters i
          ON i.site_id=f.site_id AND i.inverter_id=f.inverter_id
        WHERE f.ts >= %s
    """
    params = [start]
    if only_active:
        sql += " AND f.event_type = 'fault_active'"
    sql += " ORDER BY f.ts DESC"
    return _naive_utc(_query(sql, params), "ts")


def df_connectivity(limit: int = 40) -> pd.DataFrame:
    df = _query("""
        SELECT id, site_id, ts, source, status, message
        FROM motorview.connectivity
        ORDER BY ts DESC
        LIMIT %s
    """, (limit,))
    return _naive_utc(df, "ts")


def latest_gateway_status(site_id: str) -> dict:
    df = _query("""
        SELECT ts, status
        FROM motorview.connectivity
        WHERE site_id=%s
        ORDER BY ts DESC
        LIMIT 1
    """, (site_id,))
    if df.empty:
        return {"status": "desconhecido", "ts": None}
    row = df.iloc[0]
    return {"status": row["status"], "ts": row["ts"]}


STATUS_WORD_BITS = {
    1: "run_command", 4: "quick_stop", 5: "second_ramp", 6: "config_state",
    7: "alarm", 8: "running", 9: "enabled", 10: "forward", 11: "jog",
    12: "remote", 13: "undervoltage", 14: "automatic_pid", 15: "general_fault",
}


def decode_status_word(word) -> dict:
    if word is None or pd.isna(word):
        return {}
    word = int(word)
    return {name: bool(word & (1 << bit)) for bit, name in STATUS_WORD_BITS.items()}


def kpis_now() -> dict:
    latest = df_latest_reading()
    if latest.empty:
        return {
            "inversores": 0, "online": 0, "rodando": 0, "falhas_ativas": 0,
            "corrente_total": 0.0, "gateway_status": "desconhecido",
        }
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=2)
    online = latest[(latest["ts"] >= cutoff) & (~latest["comm_error"].fillna(False))]
    falhas_ativas = int((latest["fault_code"].fillna(0) > 0).sum())
    rodando = sum(1 for w in online["status_word"] if decode_status_word(w).get("running"))

    inv_df = df_inverters()
    site_id = inv_df["site_id"].iloc[0] if not inv_df.empty else None
    gw = latest_gateway_status(site_id) if site_id else {"status": "desconhecido"}

    return {
        "inversores": len(latest),
        "online": len(online),
        "rodando": rodando,
        "falhas_ativas": falhas_ativas,
        "corrente_total": round(float(online["current_A"].fillna(0).sum()), 1),
        "gateway_status": gw["status"],
    }
