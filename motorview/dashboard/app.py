"""
MotorView - Monitoramento de Motores e Inversores - Nacional Gás
====================================================================
ENDTECH

Recebe telemetria dos inversores (corrente, tensão, frequência, rpm,
torque, falhas, corrente rápida) publicada via MQTT pelo gateway do
Raspberry Pi (motorview/gateway) e mostra em tempo real, com histórico
gravado em banco (SQLite nesta demo - ver db.py para trocar pela base
definitiva/Postgres).

Rodar:
    pip install -r requirements.txt
    streamlit run app.py
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import auth
import db
from config import mqtt_config
from mqtt_ingest import MqttIngestWorker

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

# ---------------------------------------------------------------------
# Paleta - mesma linha visual do ProdView (ENDTECH, estilo Power BI)
# ---------------------------------------------------------------------
BG = "#EEF1F6"
PANEL = "#FFFFFF"
BORDER = "#E2E6EE"
TEXT = "#1C2430"
MUTED = "#6E7787"

BLUE = "#14487D"
BLUE_2 = "#1D6FB8"
BLUE_SOFT = "#E8F1FA"
RED = "#D62839"
RED_SOFT = "#FBEAEC"
GREEN = "#1E9E5A"
GREEN_SOFT = "#E7F7EE"
AMBER = "#F2A93E"
AMBER_SOFT = "#FDF3E3"

CAT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#8456d8", "#2ab6c9"]

NAV_ITEMS = [
    ("overview", "Visão Geral"),
    ("motors", "Motores"),
    ("current", "Corrente"),
    ("faults", "Falhas"),
    ("history", "Histórico"),
    ("connectivity", "Conectividade"),
    ("reports", "Relatórios"),
]

# Nomes em português dos bits do status_word (P0680) - ver
# db.STATUS_WORD_BITS / gateway/registers_weg_cfw500.yaml.
BIT_LABELS = {
    "run_command": "COMANDO GIRO", "quick_stop": "PARADA RÁPIDA", "second_ramp": "2ª RAMPA",
    "config_state": "CONFIGURAÇÃO", "alarm": "ALARME", "running": "RUN", "enabled": "HABILITADO",
    "forward": "HORÁRIO", "jog": "JOG", "remote": "REMOTO", "undervoltage": "SUBTENSÃO",
    "automatic_pid": "PID AUTO", "general_fault": "FALHA",
}

st.set_page_config(
    page_title="MotorView - ENDTECH",
    page_icon=":material/settings_input_component:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(f"""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700&family=Inter:wght@400;500;600;700&display=swap');
  @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,300..500,0..1,0&display=swap');

  html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; }}
  .stApp {{ background: {BG}; }}
  #MainMenu, footer {{ visibility: hidden; }}
  header[data-testid="stHeader"] {{ display: none !important; }}
  div[data-testid="stDecoration"] {{ display: none !important; }}
  div[data-testid="stSidebar"] {{ display: none !important; }}
  div.block-container {{ padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1400px; }}
  h1, h2, h3, h4 {{ font-family: 'Space Grotesk', sans-serif !important; letter-spacing: -0.01em; color:{TEXT}; }}

  div[data-testid="stMetric"] {{
      background:{PANEL}; border:1px solid {BORDER}; border-radius:14px;
      padding:14px 18px; box-shadow:0 1px 2px rgba(16,24,40,.04);
  }}
  div[data-testid="stMetricValue"] {{ color:{TEXT}; font-weight:700; }}
  div[data-testid="stMetricLabel"] {{ color:{MUTED}; }}

  .badge {{ display:inline-flex; align-items:center; gap:5px; font-weight:700; font-size:12px;
            padding:3px 10px; border-radius:999px; white-space:nowrap; }}
  .badge-green {{ background:{GREEN_SOFT}; color:{GREEN}; }}
  .badge-red {{ background:{RED_SOFT}; color:{RED}; }}
  .badge-amber {{ background:{AMBER_SOFT}; color:#8a5a10; }}
  .badge-muted {{ background:#EEF0F4; color:{MUTED}; }}
  .badge-blue {{ background:{BLUE_SOFT}; color:{BLUE}; }}

  .brand {{ font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:26px; color:{TEXT}; }}
  .brand span {{ color:{BLUE}; }}

  .motor-card {{
      background:{PANEL}; border:1px solid {BORDER}; border-radius:14px;
      padding:16px 20px; box-shadow:0 1px 2px rgba(16,24,40,.04), 0 4px 10px rgba(16,24,40,.05);
      height:100%;
  }}
  .motor-card .name {{ font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:16px; color:{TEXT}; }}
  .motor-card .sub {{ font-size:12px; color:{MUTED}; margin-bottom:8px; }}
  .motor-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:4px 14px; font-size:13px; margin-top:8px; }}
  .motor-grid .k {{ color:{MUTED}; }}
  .motor-grid .v {{ font-weight:600; color:{TEXT}; text-align:right; }}
  .motor-last {{ font-size:11px; color:{MUTED}; margin-top:10px; }}

  div.stButton > button {{
      background:{PANEL}; color:{TEXT}; border:1px solid {BORDER}; border-radius:10px;
      font-weight:600; padding:0.45rem 0.9rem; width:100%;
  }}
  div.stButton > button:hover {{ background:{BLUE_SOFT}; border-color:{BLUE}; color:{BLUE}; }}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------
# Login/autorização (Microsoft Entra ID) - ver auth.py. Em modo aberto
# (sem Secrets [auth]) só avisa, a menos que MOTORVIEW_REQUIRE_AUTH=true.
# ---------------------------------------------------------------------
auth.require_login()


# ---------------------------------------------------------------------
# Setup: banco + assinante MQTT (uma única instância por processo)
# ---------------------------------------------------------------------

@st.cache_resource
def bootstrap():
    db.init_db()
    cfg = mqtt_config()
    worker = MqttIngestWorker(cfg)
    if cfg.get("host"):
        worker.start()
    return worker


ingest_worker = bootstrap()
cfg = mqtt_config()
mqtt_configured = bool(cfg.get("host"))

st.session_state.setdefault("page", "overview")


# ---------------------------------------------------------------------
# Helpers de fuso horário / formatação / status
# ---------------------------------------------------------------------

def to_local(ts):
    if ts is None or pd.isna(ts):
        return None
    return ts.tz_localize("UTC").tz_convert(LOCAL_TZ)


def fmt_ts(ts, with_ms: bool = True) -> str:
    local = to_local(ts)
    if local is None:
        return "—"
    s = local.strftime("%d/%m/%Y %H:%M:%S.%f")
    return s[:-3] if with_ms else s[:-7]


def series_to_local(series: pd.Series) -> pd.Series:
    if series.empty:
        return series
    return series.dt.tz_localize("UTC").dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)


def motor_status(row) -> tuple[str, str]:
    """(classe_css, rótulo) - verde=operando, vermelho=falha, cinza=sem
    comunicação, âmbar=alerta, azul=parado (comunicando, sem falha/rodando)."""
    ts = row.get("ts")
    stale = ts is None or pd.isna(ts) or (
        datetime.now(timezone.utc).replace(tzinfo=None) - ts > timedelta(minutes=2)
    )
    if row.get("comm_error") or stale:
        return "badge-muted", "SEM COMUNICAÇÃO"
    if (row.get("fault_code") or 0) > 0:
        return "badge-red", "FALHA"
    bits = db.decode_status_word(row.get("status_word"))
    if bits.get("alarm"):
        return "badge-amber", "ALERTA"
    if bits.get("running"):
        return "badge-green", "OPERANDO"
    return "badge-blue", "PARADO"


def status_bits_badges(status_word) -> str:
    bits = db.decode_status_word(status_word)
    active = [BIT_LABELS.get(k, k.upper()) for k, v in bits.items() if v]
    if not active:
        return f"<span style='color:{MUTED};font-size:12px;'>sem bits ativos</span>"
    return "".join(f"<span class='badge badge-blue' style='margin:2px 4px 2px 0;'>{b}</span>" for b in active)


def val_or_dash(row, col: str, fmt: str) -> str:
    if row.get("comm_error"):
        return "—"
    v = row.get(col)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return fmt.format(v)


# ---------------------------------------------------------------------
# Cabeçalho + menu superior em cards (sem sidebar, sem st.tabs)
# ---------------------------------------------------------------------

header_l, header_r = st.columns([4, 2])
with header_l:
    st.markdown(
        f"<div class='brand'>Motor<span>View</span> "
        f"<span style='color:{MUTED};font-weight:500;font-size:14px;'>· ENDTECH · Monitoramento de "
        f"Motores e Inversores – Nacional Gás</span></div>",
        unsafe_allow_html=True,
    )
with header_r:
    auth.render_user_badge()

if not mqtt_configured:
    st.warning(
        "MQTT não configurado. Defina MOTORVIEW_MQTT_HOST/USERNAME/PASSWORD em "
        "`.streamlit/secrets.toml` (deploy) ou num `.env` local (veja `secrets.example.toml` "
        "e o README desta pasta)."
    )
else:
    badge = "badge-green" if ingest_worker.connected else "badge-amber"
    label = "MQTT conectado" if ingest_worker.connected else "Conectando ao MQTT..."
    st.markdown(f"<span class='badge {badge}'>● {label}</span>", unsafe_allow_html=True)

nav_cols = st.columns(len(NAV_ITEMS))
for col, (key, label) in zip(nav_cols, NAV_ITEMS):
    with col:
        if st.button(label, key=f"nav_{key}", use_container_width=True):
            st.session_state["page"] = key
st.divider()

page = st.session_state["page"]


# ---------------------------------------------------------------------
# Visão Geral
# ---------------------------------------------------------------------

if page == "overview":
    kpis = db.kpis_now()
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Motores cadastrados", kpis["inversores"])
    c2.metric("Motores online", kpis["online"])
    c3.metric("Motores rodando", kpis["rodando"])
    c4.metric("Motores em falha", kpis["falhas_ativas"])
    c5.metric("Corrente total (A)", kpis["corrente_total"])
    gw_badge = "badge-green" if kpis["gateway_status"] == "online" else "badge-muted"
    with c6:
        st.markdown(f"**Gateway**<br><span class='badge {gw_badge}'>● {kpis['gateway_status']}</span>",
                     unsafe_allow_html=True)

    inv_df = db.df_inverters()
    site_id = inv_df["site_id"].iloc[0] if not inv_df.empty else "—"
    mqtt_status = "conectado" if ingest_worker.connected else "desconectado"
    st.caption(
        f"Site/planta: **{site_id}**  ·  Status MQTT (dashboard): **{mqtt_status}**  ·  "
        f"Status do gateway: **{kpis['gateway_status']}**"
    )

    st.markdown("#### Status por motor")
    latest = db.df_latest_reading()
    if latest.empty:
        st.info("Nenhuma leitura recebida ainda. Verifique se o gateway (Raspberry Pi) está publicando no MQTT.")
    else:
        cols = st.columns(3)
        for i, (_, row) in enumerate(latest.iterrows()):
            css, label = motor_status(row)
            with cols[i % 3]:
                st.markdown(f"""
                <div class="motor-card">
                  <div class="name">{row['name']}</div>
                  <div class="sub">Inversor {row['inverter_id']}</div>
                  <span class="badge {css}">● {label}</span>
                  <div class="motor-grid">
                    <div class="k">Corrente</div><div class="v">{val_or_dash(row, 'current_A', '{:.1f} A')}</div>
                    <div class="k">Frequência</div><div class="v">{val_or_dash(row, 'frequency_Hz', '{:.1f} Hz')}</div>
                    <div class="k">Rotação</div><div class="v">{val_or_dash(row, 'speed_rpm', '{:.0f} rpm')}</div>
                    <div class="k">Tensão</div><div class="v">{val_or_dash(row, 'voltage_V', '{:.0f} V')}</div>
                    <div class="k">Torque</div><div class="v">{val_or_dash(row, 'torque_pct', '{:.1f} %')}</div>
                    <div class="k">Barramento CC</div><div class="v">{val_or_dash(row, 'dc_link_V', '{:.0f} V')}</div>
                  </div>
                  <div class="motor-last">Última leitura: {fmt_ts(row['ts'])}</div>
                </div>
                """, unsafe_allow_html=True)


# ---------------------------------------------------------------------
# Motores (detalhe por inversor)
# ---------------------------------------------------------------------

elif page == "motors":
    inv_df = db.df_inverters()
    if inv_df.empty:
        st.info("Nenhum motor cadastrado ainda - aguardando o gateway publicar telemetria.")
    else:
        inv_id = st.selectbox(
            "Motor", options=inv_df["id"].tolist(),
            format_func=lambda i: inv_df.set_index("id").loc[i, "name"],
        )
        latest = db.df_latest_reading()
        row = latest[latest["inverter_id"] == inv_id]
        if row.empty:
            st.info("Sem leituras para esse motor ainda.")
        else:
            row = row.iloc[0]
            css, label = motor_status(row)
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"### {row['name']}")
                st.caption(f"ID do inversor: `{row['inverter_id']}`  ·  Site: `{row['site_id']}`")
            with c2:
                st.markdown(f"<span class='badge {css}' style='font-size:14px;padding:6px 14px;'>● {label}</span>",
                             unsafe_allow_html=True)

            st.caption(
                f"Status comunicação: **{'sem comunicação' if row['comm_error'] else 'ok'}**  ·  "
                f"Última leitura: **{fmt_ts(row['ts'])}**"
            )

            g1, g2, g3, g4, g5, g6 = st.columns(6)
            g1.metric("Corrente", val_or_dash(row, "current_A", "{:.1f} A"))
            g2.metric("Tensão de saída", val_or_dash(row, "voltage_V", "{:.0f} V"))
            g3.metric("Barramento CC", val_or_dash(row, "dc_link_V", "{:.0f} V"))
            g4.metric("Frequência", val_or_dash(row, "frequency_Hz", "{:.1f} Hz"))
            g5.metric("RPM", val_or_dash(row, "speed_rpm", "{:.0f}"))
            g6.metric("Torque", val_or_dash(row, "torque_pct", "{:.1f} %"))

            sw = row.get("status_word")
            st.caption(f"Palavra de status (P0680): `{int(sw) if pd.notna(sw) else '—'}`")
            st.markdown("**Estados ativos:**")
            st.markdown(status_bits_badges(sw), unsafe_allow_html=True)

            last_code = row.get("last_fault_code")
            if pd.notna(last_code) and int(last_code or 0) > 0:
                st.markdown("**Última falha registrada no CFW-500:**")
                st.caption(f"F{int(last_code):04d} - {row.get('last_fault_description') or ''}")


# ---------------------------------------------------------------------
# Corrente em tempo real (fast_current, com fallback pra telemetry)
# ---------------------------------------------------------------------

elif page == "current":
    range_minutes = st.select_slider(
        "Janela de tempo", options=[5, 15, 30, 60, 180], value=15, format_func=lambda m: f"{m} min"
    )
    inv_df = db.df_inverters()
    selected = st.multiselect(
        "Motores", options=inv_df["id"].tolist() if not inv_df.empty else [],
        default=inv_df["id"].tolist() if not inv_df.empty else [],
        format_func=lambda i: inv_df.set_index("id").loc[i, "name"] if not inv_df.empty else i,
    )

    @st.fragment(run_every="1s")
    def live_current(range_minutes: int, selected_ids: list):
        fast = db.df_fast_current_recent(minutes=range_minutes)
        if not fast.empty and selected_ids:
            fast = fast[fast["inverter_id"].isin(selected_ids)]

        if not fast.empty:
            fast = fast.copy()
            fast["ts_local"] = series_to_local(fast["ts"])
            latest_row = fast.sort_values("ts").groupby("inverter_id").tail(1)
            s1, s2, s3, s4 = st.columns(4)
            s1.metric("Corrente atual", f"{latest_row['current_A'].sum():.1f} A")
            s2.metric("Maior pico na janela", f"{fast['current_max_A'].max():.1f} A")
            s3.metric("Corrente média", f"{fast['current_avg_A'].mean():.1f} A")
            s4.metric("Amostras (últ. janela)", int(latest_row["samples"].fillna(0).sum()))

            fig = go.Figure()
            for idx, (inv_id, sub) in enumerate(fast.groupby("inverter_id")):
                color = CAT_COLORS[idx % len(CAT_COLORS)]
                name = sub["name"].iloc[0] if pd.notna(sub["name"].iloc[0]) else inv_id
                fig.add_trace(go.Scatter(x=sub["ts_local"], y=sub["current_avg_A"], mode="lines",
                                           name=f"{name} · média", line=dict(color=color, width=2)))
                fig.add_trace(go.Scatter(x=sub["ts_local"], y=sub["current_max_A"], mode="lines",
                                           name=f"{name} · pico", line=dict(color=color, width=1.5, dash="dot")))
            fig.update_layout(
                height=440, margin=dict(l=10, r=10, t=30, b=10), plot_bgcolor=PANEL, paper_bgcolor=PANEL,
                legend=dict(orientation="h", yanchor="bottom", y=1.02), yaxis_title="Corrente (A)",
            )
            st.plotly_chart(fig, use_container_width=True, key=f"live_fast_{range_minutes}")
            st.caption("Linha contínua = média da janela MQTT (`current_avg_A`); pontilhada = "
                        "maior pico local capturado (`current_max_A`).")
        else:
            st.info(
                "Ainda sem dados de `current_fast` pra esses motores no período - mostrando "
                "`telemetry` padrão (~2s) como alternativa."
            )
            slow = db.df_telemetry_recent(minutes=range_minutes)
            if not slow.empty and selected_ids:
                slow = slow[slow["inverter_id"].isin(selected_ids)]
            if slow.empty:
                st.info("Sem dados de corrente no período selecionado.")
                return
            slow = slow.copy()
            slow["ts_local"] = series_to_local(slow["ts"])
            fig = px.line(slow, x="ts_local", y="current_A", color="name",
                           color_discrete_sequence=CAT_COLORS, labels={"current_A": "Corrente (A)", "ts_local": ""})
            fig.update_layout(height=420, margin=dict(l=10, r=10, t=20, b=10), plot_bgcolor=PANEL, paper_bgcolor=PANEL)
            st.plotly_chart(fig, use_container_width=True, key=f"live_slow_{range_minutes}")

    live_current(range_minutes, selected)


# ---------------------------------------------------------------------
# Falhas (atual + histórico interno do CFW-500 P0050/60/70 + log)
# ---------------------------------------------------------------------

elif page == "faults":
    latest = db.df_latest_reading()
    st.markdown("#### Falha atual por motor")
    if latest.empty:
        st.info("Sem leituras ainda.")
    else:
        for _, row in latest.iterrows():
            fault_code = int(row["fault_code"]) if pd.notna(row["fault_code"]) else 0
            with st.container(border=True):
                cols = st.columns([2, 2, 2])
                cols[0].markdown(f"**{row['name']}**  ·  `{row['inverter_id']}`")
                if fault_code == 0:
                    cols[1].markdown("<span class='badge badge-green'>● SEM FALHA</span>", unsafe_allow_html=True)
                else:
                    cols[1].markdown(f"<span class='badge badge-red'>● F{fault_code:04d}</span>", unsafe_allow_html=True)
                    cols[2].caption(row.get("fault_description") or "")
                cols[2].caption(f"detectado em {fmt_ts(row['ts'])}")

    st.markdown("#### Últimas falhas internas do CFW-500 (P0050/P0060/P0070)")
    if latest.empty:
        st.info("Nenhum motor cadastrado ainda.")
    else:
        inv_df = db.df_inverters()
        inv_id = st.selectbox(
            "Motor", options=inv_df["id"].tolist(),
            format_func=lambda i: inv_df.set_index("id").loc[i, "name"], key="faults_inv_select",
        )
        row = latest[latest["inverter_id"] == inv_id]
        if row.empty:
            st.info("Sem leituras para esse motor ainda.")
        else:
            row = row.iloc[0]
            last_code = row.get("last_fault_code")
            if pd.isna(last_code) or int(last_code or 0) == 0:
                st.info("Nenhuma falha registrada no histórico interno desse motor.")
            else:
                with st.container(border=True):
                    st.markdown("**Última falha**")
                    st.markdown(f"### F{int(last_code):04d}")
                    st.caption(row.get("last_fault_description") or "")
                    fc = st.columns(4)
                    fc[0].metric("Corrente", val_or_dash(row, "last_fault_current_A", "{:.1f} A"))
                    fc[1].metric("Barramento CC", val_or_dash(row, "last_fault_dc_link_V", "{:.0f} V"))
                    fc[2].metric("Frequência", val_or_dash(row, "last_fault_frequency_Hz", "{:.1f} Hz"))
                    fc[3].metric("Temp. IGBT", val_or_dash(row, "last_fault_igbt_temp_C", "{:.0f} °C"))
                    st.caption(f"Detectada pelo MotorView em: {fmt_ts(row['ts'])}")

            second = row.get("second_fault_code")
            third = row.get("third_fault_code")
            for label, code, desc in (
                ("2ª última falha", second, row.get("second_fault_description")),
                ("3ª última falha", third, row.get("third_fault_description")),
            ):
                if pd.notna(code) and int(code or 0) > 0:
                    with st.container(border=True):
                        st.markdown(f"**{label}**")
                        st.markdown(f"### F{int(code):04d}")
                        st.caption(desc or "")

    st.markdown("#### Histórico de eventos de falha (log)")
    days = st.slider("Período (dias)", 1, 90, 7, key="faults_days")
    only_active = st.checkbox("Só falhas ativas agora", value=False)
    faults = db.df_faults(days=days, only_active=only_active)
    if faults.empty:
        st.info("Nenhum evento de falha registrado no período.")
    else:
        show = faults[["ts", "name", "fault_code", "fault_description", "active"]].copy()
        show["ts"] = show["ts"].apply(fmt_ts)
        show["active"] = show["active"].map({1: "ativa", 0: "resetada"})
        show.columns = ["Data/hora", "Motor", "Código", "Descrição", "Estado"]
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.download_button(
            "Exportar CSV", show.to_csv(index=False).encode("utf-8"),
            file_name=f"motorview_falhas_{datetime.now():%Y%m%d_%H%M}.csv", mime="text/csv",
        )


# ---------------------------------------------------------------------
# Histórico (filtros por motor / período / variável + export)
# ---------------------------------------------------------------------

elif page == "history":
    inv_df = db.df_inverters()
    VAR_OPTIONS = {
        "current_A": "Corrente", "frequency_Hz": "Frequência", "speed_rpm": "RPM",
        "voltage_V": "Tensão", "dc_link_V": "Barramento CC", "torque_pct": "Torque",
        "current_max_A": "Pico de corrente (current_fast)", "fault": "Falha (log de eventos)",
    }
    c1, c2, c3, c4 = st.columns(4)
    hist_inv = c1.selectbox(
        "Motor", options=["(todos)"] + (inv_df["id"].tolist() if not inv_df.empty else []),
        format_func=lambda i: "Todos" if i == "(todos)" else inv_df.set_index("id").loc[i, "name"],
    )
    date_start = c2.date_input("Data inicial", value=datetime.now(LOCAL_TZ).date() - timedelta(days=7))
    date_end = c3.date_input("Data final", value=datetime.now(LOCAL_TZ).date())
    variable = c4.selectbox("Variável", options=list(VAR_OPTIONS.keys()), format_func=lambda k: VAR_OPTIONS[k])

    minutes = max(60, (datetime.now(LOCAL_TZ).date() - date_start).days * 24 * 60 + 24 * 60)
    inv_filter = None if hist_inv == "(todos)" else hist_inv

    if variable == "fault":
        faults = db.df_faults(days=(datetime.now(LOCAL_TZ).date() - date_start).days + 1)
        if inv_filter:
            faults = faults[faults["inverter_id"] == inv_filter]
        if not faults.empty:
            faults = faults[(faults["ts"].dt.date >= date_start) & (faults["ts"].dt.date <= date_end)]
        if faults.empty:
            st.info("Nenhuma falha no período/filtro selecionado.")
        else:
            show = faults[["ts", "name", "fault_code", "fault_description", "active"]].copy()
            show["ts"] = show["ts"].apply(fmt_ts)
            st.dataframe(show, use_container_width=True, hide_index=True)
            st.download_button("Exportar CSV", show.to_csv(index=False).encode("utf-8"),
                                 file_name="motorview_historico_falhas.csv", mime="text/csv")
    else:
        source = db.df_fast_current_recent(minutes=minutes, inverter_id=inv_filter) if variable == "current_max_A" \
            else db.df_telemetry_recent(minutes=minutes, inverter_id=inv_filter)
        if not source.empty:
            source = source[(source["ts"].dt.date >= date_start) & (source["ts"].dt.date <= date_end)]
        if source.empty or variable not in source.columns:
            st.info("Sem dados para esse filtro. 'Pico de corrente' depende do gateway publicar `current_fast`.")
        else:
            source = source.copy()
            source["ts_local"] = series_to_local(source["ts"])
            fig = px.line(source, x="ts_local", y=variable, color="name", color_discrete_sequence=CAT_COLORS,
                           labels={variable: VAR_OPTIONS[variable], "ts_local": ""})
            fig.update_layout(height=380, margin=dict(l=10, r=10, t=20, b=10), plot_bgcolor=PANEL, paper_bgcolor=PANEL)
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("#### Dados brutos")
            show = source[["ts", "name", variable]].sort_values("ts", ascending=False).copy()
            show["ts"] = show["ts"].apply(fmt_ts)
            st.dataframe(show, use_container_width=True, hide_index=True)
            st.download_button("Exportar CSV", show.to_csv(index=False).encode("utf-8"),
                                 file_name=f"motorview_historico_{variable}.csv", mime="text/csv")


# ---------------------------------------------------------------------
# Conectividade
# ---------------------------------------------------------------------

elif page == "connectivity":
    inv_df = db.df_inverters()
    site_id = inv_df["site_id"].iloc[0] if not inv_df.empty else None
    gw = db.latest_gateway_status(site_id) if site_id else {"status": "desconhecido", "ts": None}

    with st.container(border=True):
        c1, c2 = st.columns([3, 1])
        c1.markdown("**Gateway (Raspberry Pi)**")
        badge = "badge-green" if gw["status"] == "online" else "badge-muted"
        c2.markdown(f"<span class='badge {badge}'>● {gw['status']}</span>", unsafe_allow_html=True)
        gw_ts = pd.to_datetime(gw["ts"], utc=True).tz_localize(None) if gw["ts"] else None
        st.caption(f"Última atualização de status: {fmt_ts(gw_ts) if gw_ts is not None else '—'}")

    with st.container(border=True):
        c1, c2 = st.columns([3, 1])
        c1.markdown("**MQTT (assinante do dashboard)**")
        badge = "badge-green" if ingest_worker.connected else "badge-red"
        c2.markdown(f"<span class='badge {badge}'>● {'conectado' if ingest_worker.connected else 'desconectado'}</span>",
                     unsafe_allow_html=True)

    st.markdown("#### Motores")
    latest = db.df_latest_reading()
    if latest.empty:
        st.info("Nenhum motor cadastrado ainda.")
    else:
        for _, row in latest.iterrows():
            css, label = motor_status(row)
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 1, 2])
                c1.markdown(f"**{row['name']}** · `{row['inverter_id']}`")
                c2.markdown(f"<span class='badge {css}'>● {label}</span>", unsafe_allow_html=True)
                c3.caption(f"última leitura: {fmt_ts(row['ts'])}")
    st.caption("Um motor sem comunicação não afeta a exibição dos demais.")

    st.markdown("#### Log de conectividade")
    conn = db.df_connectivity(limit=50)
    if conn.empty:
        st.info("Sem eventos de conectividade registrados ainda.")
    else:
        show = conn[["ts", "site_id", "status"]].copy()
        show["ts"] = show["ts"].apply(fmt_ts)
        st.dataframe(show, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------
# Relatórios
# ---------------------------------------------------------------------

elif page == "reports":
    st.markdown("#### Resumo do período")
    days = st.slider("Período (dias)", 1, 90, 7, key="report_days")
    telem = db.df_telemetry_recent(minutes=days * 24 * 60)
    if telem.empty:
        st.info("Sem dados suficientes no período para gerar o relatório.")
    else:
        agg = telem.groupby("name").agg(
            corrente_media_A=("current_A", "mean"),
            corrente_max_A=("current_A", "max"),
            leituras=("current_A", "count"),
            leituras_com_erro=("comm_error", "sum"),
        ).reset_index()
        agg["disponibilidade_pct"] = (100 * (1 - agg["leituras_com_erro"] / agg["leituras"])).round(1)
        agg = agg.round(2)
        st.dataframe(agg, use_container_width=True, hide_index=True)

        faults = db.df_faults(days=days)
        st.markdown(f"**Total de eventos de falha no período:** {len(faults)}")

        st.download_button(
            "Exportar CSV", agg.to_csv(index=False).encode("utf-8"),
            file_name=f"motorview_relatorio_{datetime.now():%Y%m%d_%H%M}.csv", mime="text/csv",
        )
        st.caption("Exportação em PDF pode ser incluída depois, seguindo o mesmo padrão do report_pdf.py do ProdView.")
