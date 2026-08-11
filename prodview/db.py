"""
ProdView — camada de dados
==========================
Hoje esta camada fala com um SQLite local (arquivo `data/prodview.db`),
gerado e populado automaticamente na primeira execução, só para servir
de base de demonstração.

Quando a base real (SQL Server, PostgreSQL, MQTT/OPC-UA -> banco, API do
CLP, etc.) estiver disponível, o ponto de troca é UM SÓ: a função
`get_conn()` abaixo. Troque a conexão sqlite3 por pyodbc/psycopg2/etc.,
mantenha os nomes de tabela e colunas (ou ajuste as queries) e o resto
do app (app.py) não precisa mudar, porque ele só conhece as funções
públicas deste módulo.
"""

import sqlite3
import random
from datetime import datetime, timedelta, date
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "prodview.db"

# ---------------------------------------------------------------------
# Conexão
# ---------------------------------------------------------------------

def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS lines (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    product TEXT NOT NULL,
    target_speed REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    line_id INTEGER NOT NULL REFERENCES lines(id),
    ts TEXT NOT NULL,
    speed REAL NOT NULL,
    cumulative_count INTEGER NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_production (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    line_id INTEGER NOT NULL REFERENCES lines(id),
    prod_date TEXT NOT NULL,
    shift INTEGER NOT NULL,
    units INTEGER NOT NULL,
    oee_pct REAL NOT NULL,
    availability_pct REAL NOT NULL DEFAULT 95,
    performance_pct REAL NOT NULL DEFAULT 90,
    quality_pct REAL NOT NULL DEFAULT 98,
    downtime_min REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS downtime_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    line_id INTEGER NOT NULL REFERENCES lines(id),
    ts TEXT NOT NULL,
    duration_min REAL NOT NULL,
    category TEXT NOT NULL,
    reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS connectivity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    link TEXT NOT NULL,
    event TEXT NOT NULL,
    note TEXT NOT NULL
);
"""

LINES_SEED = [
    (1, "L01", "Linha 01 · P13", "P13", 18),
    (2, "L02", "Linha 02 · P20", "P20", 16),
    (3, "L03", "Linha 03 · P45", "P45", 12),
    (4, "L04", "Linha 04 · P13", "P13", 19),
]

DOWNTIME_CATEGORIES = [
    ("Mecânica", "Ajuste de garra na estação de cravação"),
    ("Elétrica", "Atuação de disjuntor no painel da linha"),
    ("Troca de produto", "Setup para mudança de botijão P13 -> P20"),
    ("Manutenção preventiva", "Lubrificação programada do transportador"),
    ("Falta de insumo", "Aguardando reposição de válvulas"),
    ("Qualidade", "Parada para inspeção de solda"),
]


def init_db():
    conn = get_conn()
    with conn:
        conn.executescript(SCHEMA)
    conn.close()


def _is_empty() -> bool:
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) AS n FROM lines").fetchone()["n"]
    conn.close()
    return n == 0


def seed_if_empty(force: bool = False):
    if not force and not _is_empty():
        return

    random.seed(42)
    conn = get_conn()
    with conn:
        # tabelas filhas primeiro — "lines" tem FOREIGN KEY apontando pra ela
        conn.execute("DELETE FROM readings")
        conn.execute("DELETE FROM daily_production")
        conn.execute("DELETE FROM downtime_events")
        conn.execute("DELETE FROM connectivity_log")
        conn.execute("DELETE FROM lines")

        conn.executemany(
            "INSERT INTO lines (id, code, name, product, target_speed) VALUES (?,?,?,?,?)",
            LINES_SEED,
        )

        # --- 30 dias de produção diária (3 turnos) ---------------------
        today = date.today()
        for day_offset in range(30, 0, -1):
            d = today - timedelta(days=day_offset)
            for line in LINES_SEED:
                line_id, _, _, _, target = line
                for shift in (1, 2, 3):
                    base = target * 60 * 7.5  # unidades/turno em ritmo alvo
                    factor = random.uniform(0.72, 1.02)
                    units = max(0, round(base * factor))
                    # OEE clássico = Disponibilidade x Performance x Qualidade
                    availability = round(max(70, min(99.5, 92 + random.uniform(-10, 7))), 1)
                    performance = round(max(65, min(98, 88 + random.uniform(-14, 9))), 1)
                    quality = round(max(85, min(99.9, 97 + random.uniform(-6, 2.5))), 1)
                    oee = round(availability * performance * quality / 10000, 1)
                    downtime = round(max(0, (1 - factor) * 300 + random.uniform(-10, 25)), 1)
                    conn.execute(
                        "INSERT INTO daily_production "
                        "(line_id, prod_date, shift, units, oee_pct, availability_pct, performance_pct, "
                        "quality_pct, downtime_min) VALUES (?,?,?,?,?,?,?,?,?)",
                        (line_id, d.isoformat(), shift, units, oee, availability, performance, quality, downtime),
                    )

        # --- eventos de parada nos últimos 30 dias ---------------------
        for _ in range(24):
            line = random.choice(LINES_SEED)
            cat, reason = random.choice(DOWNTIME_CATEGORIES)
            ts = datetime.now() - timedelta(
                days=random.uniform(0, 30), hours=random.uniform(0, 23)
            )
            duration = round(random.uniform(4, 55), 1)
            conn.execute(
                "INSERT INTO downtime_events (line_id, ts, duration_min, category, reason) "
                "VALUES (?,?,?,?,?)",
                (line[0], ts.isoformat(timespec="seconds"), duration, cat, reason),
            )

        # --- leituras "hoje" (últimas 6h, de 5 em 5 min) ----------------
        now = datetime.now()
        start = now - timedelta(hours=6)
        n_steps = int((now - start).total_seconds() // 300)
        cumulative = {line[0]: random.randint(400, 900) for line in LINES_SEED}
        for step in range(n_steps + 1):
            ts = start + timedelta(minutes=5 * step)
            for line in LINES_SEED:
                line_id, _, _, _, target = line
                speed = max(4, round(target + random.uniform(-3, 3), 1))
                cumulative[line_id] += max(0, round(speed * 5))
                status = "on" if random.random() > 0.03 else "off"
                conn.execute(
                    "INSERT INTO readings (line_id, ts, speed, cumulative_count, status) "
                    "VALUES (?,?,?,?,?)",
                    (line_id, ts.isoformat(timespec="seconds"), speed, cumulative[line_id], status),
                )

        conn.execute(
            "INSERT INTO connectivity_log (ts, link, event, note) VALUES (?,?,?,?)",
            (now.isoformat(timespec="seconds"), "sistema", "iniciado", "Sistema iniciado — link primário ativo."),
        )
    conn.close()


# ---------------------------------------------------------------------
# Simulação de "tempo real" (grava novas linhas a cada atualização)
# ---------------------------------------------------------------------

def simulate_tick():
    """Gera uma nova leitura por linha, como se um CLP tivesse acabado
    de reportar dados — grava direto no banco (INSERT real)."""
    conn = get_conn()
    now = datetime.now()
    with conn:
        for line in LINES_SEED:
            line_id, _, _, _, target = line
            last = conn.execute(
                "SELECT cumulative_count FROM readings WHERE line_id=? ORDER BY ts DESC LIMIT 1",
                (line_id,),
            ).fetchone()
            base_count = last["cumulative_count"] if last else 0
            speed = max(4, round(target + random.uniform(-3, 3), 1))
            status = "on" if random.random() > 0.03 else "off"
            new_count = base_count + (0 if status == "off" else max(0, round(speed)))
            conn.execute(
                "INSERT INTO readings (line_id, ts, speed, cumulative_count, status) VALUES (?,?,?,?,?)",
                (line_id, now.isoformat(timespec="seconds"), speed, new_count, status),
            )
    conn.close()


def log_connectivity(link: str, event: str, note: str):
    conn = get_conn()
    with conn:
        conn.execute(
            "INSERT INTO connectivity_log (ts, link, event, note) VALUES (?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), link, event, note),
        )
    conn.close()


def insert_downtime(line_id: int, duration_min: float, category: str, reason: str):
    conn = get_conn()
    with conn:
        conn.execute(
            "INSERT INTO downtime_events (line_id, ts, duration_min, category, reason) VALUES (?,?,?,?,?)",
            (line_id, datetime.now().isoformat(timespec="seconds"), duration_min, category, reason),
        )
    conn.close()


def insert_manual_reading(line_id: int, speed: float, status: str):
    conn = get_conn()
    now = datetime.now()
    last = conn.execute(
        "SELECT cumulative_count FROM readings WHERE line_id=? ORDER BY ts DESC LIMIT 1",
        (line_id,),
    ).fetchone()
    base_count = last["cumulative_count"] if last else 0
    new_count = base_count + (0 if status == "off" else max(0, round(speed)))
    with conn:
        conn.execute(
            "INSERT INTO readings (line_id, ts, speed, cumulative_count, status) VALUES (?,?,?,?,?)",
            (line_id, now.isoformat(timespec="seconds"), speed, new_count, status),
        )
    conn.close()


# ---------------------------------------------------------------------
# Consultas (DataFrames prontos pro Streamlit)
# ---------------------------------------------------------------------

def df_lines() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM lines ORDER BY id", conn)
    conn.close()
    return df


def df_readings_today() -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT r.*, l.name, l.code, l.product FROM readings r "
        "JOIN lines l ON l.id = r.line_id "
        "WHERE datetime(r.ts) >= datetime(?) ORDER BY r.ts",
        conn,
        params=[(datetime.now() - timedelta(hours=8)).isoformat(timespec="seconds")],
    )
    conn.close()
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"])
    return df


def df_daily_production(days: int = 30) -> pd.DataFrame:
    conn = get_conn()
    start = (date.today() - timedelta(days=days)).isoformat()
    df = pd.read_sql_query(
        "SELECT d.*, l.name, l.code, l.product FROM daily_production d "
        "JOIN lines l ON l.id = d.line_id "
        "WHERE d.prod_date >= ? ORDER BY d.prod_date",
        conn,
        params=[start],
    )
    conn.close()
    if not df.empty:
        df["prod_date"] = pd.to_datetime(df["prod_date"])
    return df


def df_downtime(days: int = 30) -> pd.DataFrame:
    conn = get_conn()
    start = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    df = pd.read_sql_query(
        "SELECT e.*, l.name, l.code FROM downtime_events e "
        "JOIN lines l ON l.id = e.line_id "
        "WHERE e.ts >= ? ORDER BY e.ts DESC",
        conn,
        params=[start],
    )
    conn.close()
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"])
    return df


def df_connectivity(limit: int = 40) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql_query(
        "SELECT * FROM connectivity_log ORDER BY ts DESC LIMIT ?", conn, params=[limit]
    )
    conn.close()
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"])
    return df


def oee_breakdown(days: int = 1) -> dict:
    """Médias de Disponibilidade / Performance / Qualidade / OEE — para os
    gauges no estilo 'torre de controle'."""
    daily = df_daily_production(days=days)
    if daily.empty:
        return {"availability": 92.0, "performance": 88.0, "quality": 97.0, "oee": 78.0}
    return {
        "availability": round(daily["availability_pct"].mean(), 1),
        "performance": round(daily["performance_pct"].mean(), 1),
        "quality": round(daily["quality_pct"].mean(), 1),
        "oee": round(daily["oee_pct"].mean(), 1),
    }


def df_line_target_progress() -> pd.DataFrame:
    """% da velocidade-alvo atingida hoje, por linha — para o ranking
    'melhores/piores linhas' (equivalente ao 'stores by goal')."""
    readings = df_readings_today()
    lines = df_lines()
    if readings.empty:
        out = lines.copy()
        out["avg_speed"] = 0.0
        out["pct"] = 0.0
        return out[["id", "name", "target_speed", "avg_speed", "pct"]]

    today_r = readings[readings["ts"].dt.date == date.today()]
    on_r = today_r[today_r["status"] == "on"] if not today_r.empty else today_r
    avg_speed = on_r.groupby("line_id")["speed"].mean() if not on_r.empty else pd.Series(dtype=float)

    out = lines.copy()
    out["avg_speed"] = out["id"].map(avg_speed).fillna(0.0)
    out["pct"] = (100 * out["avg_speed"] / out["target_speed"]).round(0)
    return out.sort_values("pct", ascending=False)[["id", "name", "target_speed", "avg_speed", "pct"]]


def df_downtime_top(days: int = 7, n: int = 4) -> pd.DataFrame:
    dt = df_downtime(days=days)
    if dt.empty:
        return dt
    agg = dt.groupby("category", as_index=False)["duration_min"].sum()
    agg = agg.sort_values("duration_min", ascending=False).head(n)
    total = agg["duration_min"].sum()
    agg["pct"] = (100 * agg["duration_min"] / total).round(0) if total else 0
    return agg


def kpis_period() -> dict:
    """Totais estilo 'Daily / Weekly / Monthly' + % de meta do dia."""
    today_total = kpis_today()["total_hoje"]

    week = df_daily_production(days=7)
    week_total = int(week["units"].sum()) if not week.empty else 0

    month = df_daily_production(days=date.today().day)
    if not month.empty:
        month = month[month["prod_date"].dt.month == date.today().month]
    month_total = int(month["units"].sum()) if not month.empty else 0

    hist = df_daily_production(days=14)
    if not hist.empty:
        by_day = hist.groupby(hist["prod_date"].dt.date)["units"].sum()
        avg_daily = by_day.mean()
    else:
        avg_daily = 0
    meta_pct = int(round(100 * today_total / avg_daily)) if avg_daily else 100
    meta_pct = max(0, min(150, meta_pct))

    return {
        "hoje": today_total,
        "semana": week_total,
        "mes": month_total,
        "meta_pct": meta_pct,
    }


def kpis_today() -> dict:
    readings = df_readings_today()
    lines = df_lines()
    if readings.empty:
        return {
            "total_hoje": 0, "oee_medio": 0, "linhas_ativas": 0,
            "linhas_total": len(lines), "velocidade_total": 0,
        }
    latest = readings.sort_values("ts").groupby("line_id").tail(1)
    start_of_day = readings[readings["ts"].dt.date == date.today()]
    total_hoje = 0
    if not start_of_day.empty:
        first = start_of_day.sort_values("ts").groupby("line_id")["cumulative_count"].first()
        last = start_of_day.sort_values("ts").groupby("line_id")["cumulative_count"].last()
        total_hoje = int((last - first).clip(lower=0).sum())
        # soma absoluta também é razoável de mostrar; usamos o total acumulado hoje
        total_hoje = int(last.sum() - first.sum() + first.sum())  # = last.sum()
        total_hoje = int(last.sum())
    linhas_ativas = int((latest["status"] == "on").sum())
    velocidade_total = float(latest.loc[latest["status"] == "on", "speed"].sum())

    daily = df_daily_production(days=1)
    oee_medio = round(daily["oee_pct"].mean(), 1) if not daily.empty else 96.0

    return {
        "total_hoje": total_hoje,
        "oee_medio": oee_medio if oee_medio == oee_medio else 96.0,  # NaN guard
        "linhas_ativas": linhas_ativas,
        "linhas_total": len(lines),
        "velocidade_total": round(velocidade_total, 1),
    }


# ---------------------------------------------------------------------
# Extras — dão conteúdo diferente ao "hero" de cada aba do menu
# ---------------------------------------------------------------------

def production_period_comparison(days: int = 7) -> dict:
    """Total do período atual (N dias) vs. o período imediatamente anterior."""
    cur = df_daily_production(days=days)
    prev_all = df_daily_production(days=days * 2)
    cutoff = pd.Timestamp(date.today() - timedelta(days=days))
    prev = prev_all[prev_all["prod_date"] < cutoff] if not prev_all.empty else prev_all

    cur_total = int(cur["units"].sum()) if not cur.empty else 0
    prev_total = int(prev["units"].sum()) if not prev.empty else 0
    delta_pct = round(100 * (cur_total - prev_total) / prev_total, 1) if prev_total else 0.0
    return {"current": cur_total, "previous": prev_total, "delta_pct": delta_pct, "days": days}


def df_line_units_ranking(days: int = 7) -> pd.DataFrame:
    """Ranking de linhas por total produzido no período — para o hero da aba Produção."""
    daily = df_daily_production(days=days)
    if daily.empty:
        return daily
    agg = daily.groupby("name", as_index=False)["units"].sum().sort_values("units", ascending=False)
    maxv = agg["units"].max()
    agg["pct"] = (100 * agg["units"] / maxv).round(0) if maxv else 0
    return agg


def df_line_oee_ranking(days: int = 7) -> pd.DataFrame:
    daily = df_daily_production(days=days)
    if daily.empty:
        return daily
    return daily.groupby("name", as_index=False)["oee_pct"].mean().sort_values("oee_pct", ascending=False)


def df_line_uptime_today() -> pd.DataFrame:
    """% do tempo hoje que cada linha ficou em produção (status 'on')."""
    readings = df_readings_today()
    lines = df_lines()
    if readings.empty:
        out = lines.copy()
        out["uptime_pct"] = 0.0
        return out[["id", "name", "uptime_pct"]]
    today_r = readings[readings["ts"].dt.date == date.today()]
    if today_r.empty:
        out = lines.copy()
        out["uptime_pct"] = 0.0
        return out[["id", "name", "uptime_pct"]]
    grp = today_r.groupby("line_id")["status"].apply(lambda s: 100 * (s == "on").mean())
    out = lines.copy()
    out["uptime_pct"] = out["id"].map(grp).fillna(0).round(0)
    return out.sort_values("uptime_pct", ascending=False)[["id", "name", "uptime_pct"]]


def fastest_line_now() -> dict:
    """Linha com maior velocidade na leitura mais recente de hoje."""
    readings = df_readings_today()
    if readings.empty:
        return {"name": "—", "speed": 0.0}
    latest = readings.sort_values("ts").groupby("line_id").tail(1)
    on = latest[latest["status"] == "on"]
    if on.empty:
        return {"name": "—", "speed": 0.0}
    top = on.sort_values("speed", ascending=False).iloc[0]
    return {"name": top["name"], "speed": float(top["speed"])}


def last_activity() -> dict:
    """Último evento registrado no banco (leitura manual ou parada) — o mais recente entre os dois."""
    conn = get_conn()
    r1 = conn.execute(
        "SELECT r.ts AS ts, l.name AS name, 'leitura' AS kind, CAST(r.speed AS TEXT) AS val "
        "FROM readings r JOIN lines l ON l.id = r.line_id ORDER BY r.ts DESC LIMIT 1"
    ).fetchone()
    r2 = conn.execute(
        "SELECT e.ts AS ts, l.name AS name, 'parada' AS kind, e.category AS val "
        "FROM downtime_events e JOIN lines l ON l.id = e.line_id ORDER BY e.ts DESC LIMIT 1"
    ).fetchone()
    conn.close()
    candidates = [dict(r) for r in (r1, r2) if r is not None]
    if not candidates:
        return {}
    candidates.sort(key=lambda d: d["ts"], reverse=True)
    return candidates[0]


def connectivity_stats(days: int = 30) -> dict:
    conn = get_conn()
    start = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    quedas = conn.execute(
        "SELECT COUNT(*) AS n FROM connectivity_log WHERE event='queda' AND ts >= ?", (start,)
    ).fetchone()["n"]
    last_queda = conn.execute(
        "SELECT ts FROM connectivity_log WHERE event='queda' ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    total_eventos = conn.execute(
        "SELECT COUNT(*) AS n FROM connectivity_log WHERE ts >= ?", (start,)
    ).fetchone()["n"]
    conn.close()
    return {
        "quedas": quedas,
        "last_queda": last_queda["ts"] if last_queda else None,
        "total_eventos": total_eventos,
        "days": days,
    }


def db_totals() -> dict:
    """Contagens gerais do banco — para o hero da aba Relatórios."""
    conn = get_conn()
    out = {}
    for t in ("readings", "daily_production", "downtime_events", "connectivity_log"):
        out[t] = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
    span = conn.execute("SELECT MIN(prod_date) AS a, MAX(prod_date) AS b FROM daily_production").fetchone()
    conn.close()
    out["span_start"] = span["a"]
    out["span_end"] = span["b"]
    return out
