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

# Identificadores técnicos permanecem estáveis no banco para preservar todo
# o histórico. Estes nomes são apenas a apresentação amigável ao cliente.
INVERTER_DISPLAY_NAMES = {
    "inv01": "MOTOR 42",
    "inv02": "MOTOR 43",
}
SITE_DISPLAY_NAMES = {
    "suape": "SUAPE",
    "planta1": "SUAPE",  # legado
}


def site_display_name(site_id) -> str:
    if site_id is None or pd.isna(site_id):
        return "—"
    return SITE_DISPLAY_NAMES.get(str(site_id), str(site_id))


def _clientize(df: pd.DataFrame) -> pd.DataFrame:
    """Aplica nomes comerciais sem alterar as chaves internas."""
    if df.empty:
        return df
    df = df.copy()
    if "inverter_id" in df.columns:
        mapped = df["inverter_id"].astype(str).map(INVERTER_DISPLAY_NAMES)
        if "name" in df.columns:
            df["name"] = mapped.fillna(df["name"])
        else:
            df["name"] = mapped.fillna(df["inverter_id"].astype(str))
    if "site_id" in df.columns:
        df["site_name"] = df["site_id"].apply(site_display_name)
    return df


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
    return _clientize(_query("""
        SELECT inverter_id AS id, inverter_id, site_id, name, active
        FROM motorview.inverters
        WHERE active = TRUE
        ORDER BY name
    """))


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
    return _clientize(_naive_utc(_query(sql, params), "ts"))


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
    return _clientize(_naive_utc(_query(sql, params), "ts", "window_start", "window_end"))


def df_current_history(minutes: int = 1440, inverter_id: str | None = None) -> pd.DataFrame:
    """Corrente histórica agregada no PostgreSQL para janelas longas.

    Evita transferir milhares/milhões de amostras ao Streamlit. O bucket é
    escolhido para manter detalhe suficiente sem sobrecarregar Neon/dashboard.
    """
    start = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    if minutes <= 360:
        bucket_seconds = 30
    elif minutes <= 1440:
        bucket_seconds = 120
    elif minutes <= 10080:
        bucket_seconds = 600
    else:
        bucket_seconds = 1800

    sql = """
        SELECT
            MIN(t.id) AS id,
            t.site_id,
            t.inverter_id,
            date_bin(make_interval(secs => %s), t.ts,
                     TIMESTAMPTZ '2000-01-01 00:00:00+00') AS ts,
            AVG(t.current_a) AS "current_A",
            MIN(t.current_a) AS "current_min_A",
            MAX(t.current_a) AS "current_max_A",
            AVG(t.current_a) AS "current_avg_A",
            COUNT(*)::int AS samples,
            (%s * 1000)::int AS sample_interval_ms,
            i.name
        FROM motorview.telemetry t
        JOIN motorview.inverters i
          ON i.site_id=t.site_id AND i.inverter_id=t.inverter_id
        WHERE t.ts >= %s
          AND t.current_a IS NOT NULL
    """
    params = [bucket_seconds, bucket_seconds, start]
    if inverter_id:
        sql += " AND t.inverter_id = %s"
        params.append(inverter_id)
    # Agrupa pela posição das expressões já selecionadas. Isso é
    # importante porque repetir o bucket como outro placeholder (%s) faria o
    # PostgreSQL enxergar duas expressões parametrizadas distintas e rejeitar
    # o SELECT com GroupingError.
    sql += """
        GROUP BY 2, 3, 4, 11
        ORDER BY 4
    """
    return _clientize(_naive_utc(_query(sql, params), "ts"))


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
    return _clientize(_naive_utc(df, "ts"))


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
    return _clientize(_naive_utc(_query(sql, params), "ts"))


def df_connectivity(limit: int = 40) -> pd.DataFrame:
    df = _query("""
        SELECT id, site_id, ts, source, status, message
        FROM motorview.connectivity
        ORDER BY ts DESC
        LIMIT %s
    """, (limit,))
    return _clientize(_naive_utc(df, "ts"))


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



def df_report_summary(days: int = 7) -> pd.DataFrame:
    """Resumo por motor calculado no PostgreSQL, sem baixar milhões de leituras."""
    start = datetime.now(timezone.utc) - timedelta(days=days)
    df = _query("""
        SELECT
            t.site_id,
            t.inverter_id,
            i.name,
            AVG(t.current_a) AS "corrente_media_A",
            MAX(t.current_a) AS "corrente_max_telemetry_A",
            AVG(t.voltage_v) AS "tensao_media_V",
            AVG(t.frequency_hz) AS "frequencia_media_Hz",
            AVG(t.speed_rpm) AS "velocidade_media_rpm",
            AVG(t.torque_pct) AS "torque_medio_pct",
            AVG(t.dc_link_v) AS "link_cc_medio_V",
            COUNT(*) AS leituras,
            SUM(CASE WHEN t.comm_error THEN 1 ELSE 0 END) AS leituras_com_erro
        FROM motorview.telemetry t
        JOIN motorview.inverters i
          ON i.site_id=t.site_id AND i.inverter_id=t.inverter_id
        WHERE t.ts >= %s
        GROUP BY t.site_id, t.inverter_id, i.name
        ORDER BY i.name
    """, (start,))
    if df.empty:
        return df

    fast = _query("""
        SELECT
            inverter_id,
            AVG(current_avg_a) AS "corrente_fast_media_A",
            MAX(current_max_a) AS "corrente_fast_max_A",
            MIN(current_min_a) AS "corrente_fast_min_A"
        FROM motorview.current_fast
        WHERE ts >= %s
        GROUP BY inverter_id
    """, (start,))
    if not fast.empty:
        df = df.merge(fast, on="inverter_id", how="left")

    df = _clientize(df)
    df["corrente_media_A"] = df.get("corrente_fast_media_A", df["corrente_media_A"]).fillna(df["corrente_media_A"])
    df["corrente_max_A"] = df.get("corrente_fast_max_A", df["corrente_max_telemetry_A"]).fillna(df["corrente_max_telemetry_A"])
    df["corrente_min_A"] = df.get("corrente_fast_min_A", pd.Series(index=df.index, dtype=float))
    df["disponibilidade_pct"] = (
        100 * (1 - df["leituras_com_erro"].fillna(0) / df["leituras"].clip(lower=1))
    ).round(1)
    return df


def df_report_current_trend(days: int = 7) -> pd.DataFrame:
    """Série reduzida no servidor para gráficos de relatório."""
    start = datetime.now(timezone.utc) - timedelta(days=days)
    if days <= 1:
        bucket = "1 minute"
    elif days <= 7:
        bucket = "5 minutes"
    elif days <= 30:
        bucket = "30 minutes"
    else:
        bucket = "2 hours"

    df = _query(f"""
        SELECT
            f.site_id,
            f.inverter_id,
            i.name,
            date_bin(INTERVAL '{bucket}', f.ts, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS ts,
            AVG(f.current_avg_a) AS "current_avg_A",
            MAX(f.current_max_a) AS "current_max_A"
        FROM motorview.current_fast f
        JOIN motorview.inverters i
          ON i.site_id=f.site_id AND i.inverter_id=f.inverter_id
        WHERE f.ts >= %s
        GROUP BY f.site_id, f.inverter_id, i.name, 4
        ORDER BY 4, f.inverter_id
    """, (start,))
    return _clientize(_naive_utc(df, "ts"))


def df_report_daily(days: int = 7) -> pd.DataFrame:
    """Resumo diário por motor para tabela detalhada do PDF."""
    start = datetime.now(timezone.utc) - timedelta(days=days)
    df = _query("""
        SELECT
            t.site_id,
            t.inverter_id,
            i.name,
            (t.ts AT TIME ZONE 'America/Sao_Paulo')::date AS data,
            AVG(t.current_a) AS "corrente_media_A",
            MAX(t.current_a) AS "corrente_max_A",
            AVG(t.voltage_v) AS "tensao_media_V",
            AVG(t.frequency_hz) AS "frequencia_media_Hz",
            AVG(t.speed_rpm) AS "velocidade_media_rpm",
            SUM(CASE WHEN t.comm_error THEN 1 ELSE 0 END) AS erros_comunicacao,
            COUNT(*) AS leituras
        FROM motorview.telemetry t
        JOIN motorview.inverters i
          ON i.site_id=t.site_id AND i.inverter_id=t.inverter_id
        WHERE t.ts >= %s
        GROUP BY t.site_id, t.inverter_id, i.name, 4
        ORDER BY 4 DESC, i.name
    """, (start,))
    return _clientize(df)

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
