"""
MotorView - Monitoramento de Motores e Inversores - Nacional Gás
====================================================================
ENDTECH

Recebe telemetria dos inversores (corrente, tensão, frequência, rpm,
torque, falhas, corrente rápida) publicada via MQTT pelo gateway do
Raspberry Pi (motorview/gateway) e mostra em tempo real, com histórico
gravado em banco (SQLite nesta demo - ver db.py para trocar pela base
definitiva/Postgres).

Segue a MESMA linguagem visual do ProdView (prodview/app.py) - mesma
paleta, mesmos helpers (icon/style_fig/stat_card), mesmo padrão de menu
em cards com página ativa via type="primary"/"secondary".

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
# Paleta - IDÊNTICA ao ProdView (prodview/app.py) - mesma suíte ENDTECH.
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
ORANGE = "#F2782F"

CAT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#8456d8", "#2ab6c9"]

NAV_ITEMS = [
    ("overview", "dashboard", "Visão Geral"),
    ("motors", "precision_manufacturing", "Motores"),
    ("current", "bolt", "Corrente"),
    ("faults", "report_problem", "Falhas"),
    ("history", "history", "Histórico"),
    ("connectivity", "wifi_tethering", "Conectividade"),
    ("reports", "description", "Relatórios"),
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

# ---------------------------------------------------------------------
# CSS - mesmo estilo Power BI / Material UI do ProdView (cards brancos,
# menu em cards no topo, sem sidebar) + variações de estado do MotorView.
# ---------------------------------------------------------------------
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
  div.block-container {{ padding-top: 1.4rem; padding-bottom: 2rem; max-width: 1360px; }}
  h1, h2, h3 {{ font-family: 'Space Grotesk', sans-serif !important; letter-spacing: -0.01em; color:{TEXT}; }}

  .mi {{
      font-family: 'Material Symbols Rounded'; font-weight: normal; font-style: normal;
      font-size: 20px; line-height: 1; letter-spacing: normal; text-transform: none;
      display: inline-block; white-space: nowrap; word-wrap: normal; direction: ltr;
      -webkit-font-smoothing: antialiased; vertical-align: middle;
      font-variation-settings: 'FILL' 0, 'wght' 450, 'GRAD' 0, 'opsz' 24;
  }}

  .card {{
      background:{PANEL}; border:1px solid {BORDER}; border-radius:14px;
      padding:18px 20px; box-shadow:0 1px 2px rgba(16,24,40,.04), 0 4px 10px rgba(16,24,40,.05);
      height:100%;
  }}
  .card-title {{
      font-family:'Space Grotesk',sans-serif; font-weight:600; font-size:14px; color:{TEXT};
      margin-bottom:2px; display:flex; align-items:center; gap:8px;
  }}
  .card-title .mi {{ font-size:18px; color:{BLUE}; }}
  .card-sub {{ font-size:12px; color:{MUTED}; margin-bottom:12px; }}

  .stat-card {{ display:flex; align-items:center; gap:14px; }}
  .stat-icon {{ width:44px; height:44px; border-radius:11px; display:flex; align-items:center; justify-content:center; flex-shrink:0; }}
  .stat-icon .mi {{ font-size:24px; }}
  .stat-value {{ font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:22px; color:{TEXT}; line-height:1.15; }}
  .stat-label {{ font-size:12px; color:{MUTED}; margin-top:2px; }}

  div[data-testid="stMetric"] {{
      background:{PANEL}; border:1px solid {BORDER}; border-radius:14px;
      padding:14px 18px; box-shadow:0 1px 2px rgba(16,24,40,.04);
  }}
  div[data-testid="stMetricValue"] {{ color:{TEXT}; font-weight:700; }}
  div[data-testid="stMetricLabel"] {{ color:{MUTED}; }}

  div.stButton > button {{
      background:{BLUE}; color:#fff; border:none; border-radius:8px;
      font-weight:600; padding:0.5rem 1rem;
  }}
  div.stButton > button:hover {{ background:{BLUE_2}; color:#fff; }}
  div.stDownloadButton > button {{
      background:{PANEL}; color:{BLUE}; border:1.5px solid {BLUE}; border-radius:8px; font-weight:600;
  }}
  div.stDownloadButton > button:hover {{ background:{BLUE_SOFT}; }}

  /* hero cards (Visão Geral) - mesmo mecanismo do ProdView */
  .st-key-hero_a, .st-key-hero_b, .st-key-hero_c {{
      background:{PANEL}; border:1px solid {BORDER}; border-radius:14px;
      padding:16px 20px 20px; box-shadow:0 1px 2px rgba(16,24,40,.04), 0 4px 10px rgba(16,24,40,.05);
  }}

  /* menu principal - card buttons no topo, página ativa = type="primary" */
  .st-key-nav_row div[data-testid="stHorizontalBlock"] {{ gap: 10px; }}
  .st-key-nav_row button {{
      height:52px; border-radius:12px !important; font-weight:600 !important; font-size:14px !important;
      transition: all .15s ease; box-shadow:0 1px 2px rgba(16,24,40,.04);
  }}
  .st-key-nav_row button[kind="secondary"] {{
      background:{PANEL} !important; color:{MUTED} !important; border:1px solid {BORDER} !important;
  }}
  .st-key-nav_row button[kind="secondary"]:hover {{
      background:{BLUE_SOFT} !important; color:{BLUE} !important; border-color:{BLUE} !important;
  }}
  .st-key-nav_row button[kind="primary"] {{
      background:{BLUE} !important; color:#fff !important; border:1px solid {BLUE} !important;
      box-shadow:0 4px 14px rgba(20,72,125,.28);
  }}

  .badge {{
    display:inline-flex; align-items:center; gap:7px;
    background:{GREEN_SOFT}; border:1px solid #bfe9d2; color:{GREEN};
    font-size:12px; font-weight:600; padding:5px 12px; border-radius:999px;
  }}
  .badge .mi {{ font-size:15px; }}
  .badge-green {{ background:{GREEN_SOFT}; border-color:#bfe9d2; color:{GREEN}; }}
  .badge-red {{ background:{RED_SOFT}; border-color:#f4c2c9; color:{RED}; }}
  .badge-amber {{ background:{AMBER_SOFT}; border-color:#f6dcad; color:#8a5a10; }}
  .badge-muted {{ background:#EEF0F4; border-color:{BORDER}; color:{MUTED}; }}
  .badge-info {{ background:{BLUE_SOFT}; border-color:#cfe1f4; color:{BLUE}; }}

  .dot-on {{ display:inline-block; width:8px; height:8px; border-radius:50%; background:{GREEN}; }}
  .dot-off {{ display:inline-block; width:8px; height:8px; border-radius:50%; background:{RED}; }}

  .mini-stat-row {{ display:flex; justify-content:space-between; align-items:center; font-size:13px; padding:6px 0; border-bottom:1px dashed {BORDER}; }}
  .mini-stat-row:last-child {{ border-bottom:none; }}
  .hero-num-lbl {{ font-size:12px; color:{MUTED}; }}
  .hero-num-val {{ font-size:22px; font-weight:700; color:{TEXT}; font-family:'Space Grotesk',sans-serif; }}
  .hero-num-val.big {{ font-size:34px; }}

  /* card de motor - branco predominante, com borda de destaque conforme o
     estado (verde/âmbar/vermelho/cinza) e traço tracejado quando offline */
  .motor-card {{ border-left-width:5px; border-left-style:solid; }}
  .motor-card .name {{ font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:16px; color:{TEXT}; }}
  .motor-card .sub {{ font-size:12px; color:{MUTED}; margin-bottom:8px; }}
  .motor-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:4px 14px; font-size:13px; margin-top:10px; }}
  .motor-grid .k {{ color:{MUTED}; }}
  .motor-grid .v {{ font-weight:600; color:{TEXT}; text-align:right; }}
  .motor-last {{ font-size:11px; color:{MUTED}; margin-top:10px; }}
</style>
""", unsafe_allow_html=True)


def icon(name: str, size: int = 20, color: str | None = None) -> str:
    style = f"font-size:{size}px;" + (f"color:{color};" if color else "")
    return f'<span class="mi" style="{style}">{name}</span>'


def style_fig(fig, height=340, legend=True):
    """Mesma linguagem visual dos gráficos do ProdView (fundo transparente,
    fonte Inter, grid discreto, hover no tom do painel)."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color=TEXT, size=12),
        height=height,
        margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    bgcolor="rgba(0,0,0,0)") if legend else dict(),
        hoverlabel=dict(bgcolor=PANEL, font_color=TEXT, bordercolor=BORDER),
    )
    fig.update_xaxes(showgrid=True, gridcolor=BORDER, zeroline=False, linecolor=BORDER)
    fig.update_yaxes(showgrid=True, gridcolor=BORDER, zeroline=False, linecolor=BORDER)
    return fig


def stat_card(mi_icon: str, label: str, value: str, accent: str = BLUE) -> str:
    return f"""
    <div class="card stat-card">
      <div class="stat-icon" style="background:{accent}1A;">{icon(mi_icon, 24, accent)}</div>
      <div>
        <div class="stat-value">{value}</div>
        <div class="stat-label">{label}</div>
      </div>
    </div>
    """


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


def time_ago(ts) -> str:
    local = to_local(ts)
    if local is None:
        return "sem dados"
    delta = datetime.now(LOCAL_TZ) - local
    mins = int(delta.total_seconds() // 60)
    if mins < 1:
        return "agora mesmo"
    if mins < 60:
        return f"há {mins} min"
    hours = mins // 60
    if hours < 24:
        return f"há {hours}h"
    return f"há {hours // 24}d"


def motor_status(row) -> tuple[str, str, str, bool]:
    """(rótulo, cor_hex, ícone, tracejado) - estado visual do motor.
    verde=operando, âmbar=alerta, vermelho=falha, cinza=parado; offline
    é um estado à parte (mesma cor cinza, mas ícone + borda tracejada,
    pra ficar evidente e não se confundir com "parado")."""
    ts = row.get("ts")
    stale = ts is None or pd.isna(ts) or (
        datetime.now(timezone.utc).replace(tzinfo=None) - ts > timedelta(minutes=2)
    )
    if row.get("comm_error") or stale:
        return "OFFLINE", MUTED, "wifi_off", True
    if (row.get("fault_code") or 0) > 0:
        return "FALHA", RED, "report", False
    bits = db.decode_status_word(row.get("status_word"))
    if bits.get("alarm"):
        return "ALERTA", AMBER, "warning", False
    if bits.get("running"):
        return "OPERANDO", GREEN, "play_circle", False
    return "PARADO", MUTED, "pause_circle", False


def status_badge_html(label: str, color: str, mi_icon: str) -> str:
    return (f"<span class='badge' style='background:{color}1A;border-color:{color}55;color:{color};'>"
            f"{icon(mi_icon, 15)} {label}</span>")


def status_bits_badges(status_word) -> str:
    bits = db.decode_status_word(status_word)
    active = [BIT_LABELS.get(k, k.upper()) for k, v in bits.items() if v]
    if not active:
        return f"<span style='color:{MUTED};font-size:12px;'>sem bits ativos</span>"
    return "".join(f"<span class='badge badge-info' style='margin:2px 4px 2px 0;'>{b}</span>" for b in active)


def val_or_dash(row, col: str, fmt: str) -> str:
    if row.get("comm_error"):
        return "—"
    v = row.get(col)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return fmt.format(v)


def latest_current_fast(inverter_id: str) -> dict | None:
    """Última janela de current_fast desse motor (pra mostrar o pico
    'current_max_A' no card - usa só db.df_fast_current_recent(), que já
    existe, sem alterar db.py)."""
    df = db.df_fast_current_recent(minutes=10, inverter_id=inverter_id)
    if df.empty:
        return None
    return df.sort_values("ts").iloc[-1].to_dict()


# ---------------------------------------------------------------------
# Cabeçalho - mesmo layout do ProdView (logo + marca | status | relógio)
# ---------------------------------------------------------------------

hcol1, hcol2, hcol3 = st.columns([4.2, 2.0, 1.6])

with hcol1:
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:12px;">
          <div style="width:44px;height:44px;border-radius:10px;
               background:linear-gradient(135deg,{BLUE},{BLUE_2});
               display:flex;align-items:center;justify-content:center;
               font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:16px;color:#fff;">ET</div>
          <div>
            <div style="font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:20px;color:{TEXT};">
              ENDTECH <span style="color:{MUTED};font-weight:500;font-size:13px;">· MotorView</span></div>
            <div style="font-size:12.5px;color:{MUTED};">Monitoramento de Motores e Inversores - Nacional Gás</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with hcol2:
    if not mqtt_configured:
        st.markdown(
            f'<div style="text-align:right;padding-top:6px;">'
            f'<span class="badge badge-amber">{icon("warning", 15)} MQTT não configurado</span></div>',
            unsafe_allow_html=True,
        )
    else:
        badge_cls = "badge-green" if ingest_worker.connected else "badge-amber"
        mi = "cloud_done" if ingest_worker.connected else "cloud_sync"
        label = "MQTT conectado" if ingest_worker.connected else "Conectando ao MQTT..."
        st.markdown(
            f'<div style="text-align:right;padding-top:6px;">'
            f'<span class="badge {badge_cls}">{icon(mi, 15)} {label}</span></div>',
            unsafe_allow_html=True,
        )

with hcol3:
    st.markdown(
        f"""<div style="text-align:right;padding-top:10px;font-size:12.5px;color:{MUTED};">
        {icon('schedule', 14)} {datetime.now(LOCAL_TZ).strftime('%d/%m/%Y')}<br>
        <b style="color:{TEXT};">{datetime.now(LOCAL_TZ).strftime('%H:%M:%S')}</b></div>""",
        unsafe_allow_html=True,
    )

if not mqtt_configured:
    st.warning(
        "MQTT não configurado. Defina MOTORVIEW_MQTT_HOST/USERNAME/PASSWORD em "
        "`.streamlit/secrets.toml` (deploy) ou num `.env` local (veja `secrets.example.toml` "
        "e o README desta pasta)."
    )
auth.render_user_badge()

# ---------------------------------------------------------------------
# Menu principal - mesmo mecanismo do ProdView: st.container(key="nav_row")
# + type="primary" na página ativa (CSS já cuida da aparência).
# ---------------------------------------------------------------------
with st.container(key="nav_row"):
    nav_cols = st.columns(len(NAV_ITEMS))
    for col, (key, mi, label) in zip(nav_cols, NAV_ITEMS):
        is_active = st.session_state["page"] == key
        with col:
            if st.button(label, icon=f":material/{mi}:", key=f"nav_{key}", width="stretch",
                          type="primary" if is_active else "secondary"):
                st.session_state["page"] = key
                st.rerun()

st.markdown(f"<hr style='border:none;border-top:1px solid {BORDER};margin:14px 0 18px;'>", unsafe_allow_html=True)

page = st.session_state["page"]


# ---------------------------------------------------------------------
# Visão Geral
# ---------------------------------------------------------------------

if page == "overview":
    kpis = db.kpis_now()
    latest = db.df_latest_reading()
    parados = max(0, kpis["online"] - kpis["rodando"] - kpis["falhas_ativas"])
    offline = kpis["inversores"] - kpis["online"]

    hc1, hc2, hc3 = st.columns((1.1, 1.15, 1.15))

    with hc1, st.container(key="hero_a"):
        st.markdown(
            f'<div class="card-title">{icon("precision_manufacturing")} Frota de motores</div>'
            '<div class="card-sub">Estado atual de todos os inversores</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            "".join(f"<div class='mini-stat-row'><span>{lbl}</span><b style='color:{c};'>{v}</b></div>" for lbl, v, c in [
                ("Cadastrados", kpis["inversores"], TEXT),
                ("Online", kpis["online"], GREEN),
                ("Rodando", kpis["rodando"], GREEN),
                ("Parados", parados, MUTED),
                ("Em falha", kpis["falhas_ativas"], RED if kpis["falhas_ativas"] else MUTED),
                ("Offline", offline, MUTED if offline == 0 else RED),
            ]),
            unsafe_allow_html=True,
        )

    with hc2, st.container(key="hero_b"):
        st.markdown(
            f'<div class="card-title">{icon("bolt")} Corrente agora</div>'
            '<div class="card-sub">Soma dos motores online</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="hero-num-val big">{kpis["corrente_total"]:.1f}<span style="font-size:16px;color:{MUTED};"> A</span></div>',
            unsafe_allow_html=True,
        )
        if not latest.empty:
            top = latest.sort_values("current_A", ascending=False).iloc[0]
            st.markdown(
                f'<div style="color:{MUTED};font-size:12px;margin-top:6px;">Maior corrente: '
                f'<b style="color:{TEXT};">{val_or_dash(top, "current_A", "{:.1f} A")}</b> ({top["name"]})</div>',
                unsafe_allow_html=True,
            )

    with hc3, st.container(key="hero_c"):
        inv_df = db.df_inverters()
        site_id = inv_df["site_id"].iloc[0] if not inv_df.empty else "—"
        gw = db.latest_gateway_status(site_id) if not inv_df.empty else {"status": "desconhecido", "ts": None}
        gw_ts = pd.to_datetime(gw["ts"], utc=True).tz_localize(None) if gw["ts"] else None
        gw_dot = "dot-on" if gw["status"] == "online" else "dot-off"
        mqtt_dot = "dot-on" if ingest_worker.connected else "dot-off"
        st.markdown(
            f'<div class="card-title">{icon("cell_tower")} Gateway e MQTT</div>'
            f'<div class="card-sub">Site/planta: {site_id}</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f"<div class='mini-stat-row'><span><span class='{gw_dot}'></span>&nbsp; Gateway (Raspberry Pi)</span>"
            f"<b>{gw['status']}</b></div>"
            f"<div class='mini-stat-row'><span><span class='{mqtt_dot}'></span>&nbsp; MQTT (broker)</span>"
            f"<b>{'conectado' if ingest_worker.connected else 'desconectado'}</b></div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div style="color:{MUTED};font-size:12px;margin-top:6px;">Último status do gateway: {time_ago(gw_ts)}</div>',
            unsafe_allow_html=True,
        )

    st.write("")
    st.markdown(f'<div class="card-title" style="font-size:15px;">{icon("dashboard")} Status por motor</div>',
                 unsafe_allow_html=True)
    if latest.empty:
        st.info("Nenhuma leitura recebida ainda. Verifique se o gateway (Raspberry Pi) está publicando no MQTT.",
                 icon=":material/info:")
    else:
        cols = st.columns(3)
        for i, (_, row) in enumerate(latest.iterrows()):
            label, color, mi, dashed = motor_status(row)
            border_style = "dashed" if dashed else "solid"
            with cols[i % 3]:
                st.markdown(f"""
                <div class="card motor-card" style="border-left-color:{color};border-left-style:{border_style};">
                  <div class="name">{row['name']}</div>
                  <div class="sub">Inversor {row['inverter_id']}</div>
                  {status_badge_html(label, color, mi)}
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
        st.info("Nenhum motor cadastrado ainda - aguardando o gateway publicar telemetria.", icon=":material/info:")
    else:
        inv_id = st.selectbox(
            "Motor", options=inv_df["id"].tolist(),
            format_func=lambda i: inv_df.set_index("id").loc[i, "name"],
        )
        latest = db.df_latest_reading()
        row = latest[latest["inverter_id"] == inv_id]
        if row.empty:
            st.info("Sem leituras para esse motor ainda.", icon=":material/info:")
        else:
            row = row.iloc[0]
            label, color, mi, dashed = motor_status(row)
            fast = latest_current_fast(inv_id)

            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"### {row['name']}")
                st.caption(f"ID do inversor: `{row['inverter_id']}`  ·  Site: `{row['site_id']}`")
            with c2:
                st.markdown(status_badge_html(label, color, mi), unsafe_allow_html=True)

            st.caption(
                f"Comunicação: **{'offline' if row['comm_error'] else 'ok'}**  ·  "
                f"Última leitura: **{fmt_ts(row['ts'])}** ({time_ago(row['ts'])})"
            )

            g1, g2, g3, g4, g5, g6 = st.columns(6)
            g1.markdown(stat_card("bolt", "Corrente", val_or_dash(row, "current_A", "{:.1f} A"), BLUE),
                         unsafe_allow_html=True)
            g2.markdown(stat_card("speed", "Pico recente",
                         f"{fast['current_max_A']:.1f} A" if fast and pd.notna(fast.get("current_max_A")) else "—", ORANGE),
                         unsafe_allow_html=True)
            g3.markdown(stat_card("bolt", "Tensão de saída", val_or_dash(row, "voltage_V", "{:.0f} V"), BLUE_2),
                         unsafe_allow_html=True)
            g4.markdown(stat_card("power", "Barramento CC", val_or_dash(row, "dc_link_V", "{:.0f} V"), BLUE_2),
                         unsafe_allow_html=True)
            g5.markdown(stat_card("graphic_eq", "Frequência", val_or_dash(row, "frequency_Hz", "{:.1f} Hz"), BLUE),
                         unsafe_allow_html=True)
            g6.markdown(stat_card("rotate_right", "RPM", val_or_dash(row, "speed_rpm", "{:.0f}"), GREEN),
                         unsafe_allow_html=True)

            st.write("")
            sw = row.get("status_word")
            st.markdown(
                f'<div class="card-title">{icon("toggle_on")} Estados ativos (P0680) '
                f'<span style="color:{MUTED};font-weight:400;font-size:12px;">- word `{int(sw) if pd.notna(sw) else "—"}`</span></div>',
                unsafe_allow_html=True,
            )
            st.markdown(status_bits_badges(sw), unsafe_allow_html=True)

            last_code = row.get("last_fault_code")
            if pd.notna(last_code) and int(last_code or 0) > 0:
                st.write("")
                st.markdown(f'<div class="card-title">{icon("report_problem")} Última falha registrada no CFW-500</div>',
                             unsafe_allow_html=True)
                st.markdown(f"**F{int(last_code):04d}** - {row.get('last_fault_description') or ''}")


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
            s1.markdown(stat_card("bolt", "Corrente atual", f"{latest_row['current_A'].sum():.1f} A", BLUE),
                         unsafe_allow_html=True)
            s2.markdown(stat_card("speed", "Maior pico na janela", f"{fast['current_max_A'].max():.1f} A", ORANGE),
                         unsafe_allow_html=True)
            s3.markdown(stat_card("show_chart", "Corrente média", f"{fast['current_avg_A'].mean():.1f} A", BLUE_2),
                         unsafe_allow_html=True)
            s4.markdown(stat_card("dataset", "Amostras (últ. janela)", f"{int(latest_row['samples'].fillna(0).sum())}", GREEN),
                         unsafe_allow_html=True)
            st.write("")

            fig = go.Figure()
            for idx, (inv_id, sub) in enumerate(fast.groupby("inverter_id")):
                color = CAT_COLORS[idx % len(CAT_COLORS)]
                name = sub["name"].iloc[0] if pd.notna(sub["name"].iloc[0]) else inv_id
                fig.add_trace(go.Scatter(x=sub["ts_local"], y=sub["current_avg_A"], mode="lines",
                                           name=f"{name} · média", line=dict(color=color, width=2.5)))
                fig.add_trace(go.Scatter(x=sub["ts_local"], y=sub["current_max_A"], mode="lines",
                                           name=f"{name} · pico", line=dict(color=color, width=1.5, dash="dot")))
            fig.update_layout(yaxis_title="Corrente (A)")
            st.plotly_chart(style_fig(fig, height=420), width="stretch", key=f"live_fast_{range_minutes}")
            st.caption("Linha contínua = média da janela MQTT (`current_avg_A`); pontilhada = "
                        "maior pico local capturado (`current_max_A`).")
        else:
            st.info(
                "Ainda sem dados de `current_fast` pra esses motores no período - mostrando "
                "`telemetry` padrão (~2s) como alternativa.", icon=":material/info:",
            )
            slow = db.df_telemetry_recent(minutes=range_minutes)
            if not slow.empty and selected_ids:
                slow = slow[slow["inverter_id"].isin(selected_ids)]
            if slow.empty:
                st.info("Sem dados de corrente no período selecionado.", icon=":material/info:")
                return
            slow = slow.copy()
            slow["ts_local"] = series_to_local(slow["ts"])
            fig = px.line(slow, x="ts_local", y="current_A", color="name",
                           color_discrete_sequence=CAT_COLORS, labels={"current_A": "Corrente (A)", "ts_local": ""})
            st.plotly_chart(style_fig(fig, height=420), width="stretch", key=f"live_slow_{range_minutes}")

    live_current(range_minutes, selected)


# ---------------------------------------------------------------------
# Falhas (atual + histórico interno do CFW-500 P0050/60/70 + log)
# ---------------------------------------------------------------------

elif page == "faults":
    latest = db.df_latest_reading()
    st.markdown(f'<div class="card-title" style="font-size:15px;">{icon("report_problem")} Falha atual por motor</div>',
                 unsafe_allow_html=True)
    if latest.empty:
        st.info("Sem leituras ainda.", icon=":material/info:")
    else:
        active_faults = latest[latest["fault_code"].fillna(0) > 0]
        if not active_faults.empty:
            st.error(f"⚠ {len(active_faults)} motor(es) com falha ativa agora.", icon=":material/report:")
        for _, row in latest.iterrows():
            fault_code = int(row["fault_code"]) if pd.notna(row["fault_code"]) else 0
            accent = RED if fault_code else GREEN
            with st.container(border=True):
                st.markdown(f"<div style='border-left:4px solid {accent};margin:-1rem -1rem 0 -1rem;padding:1rem;'>",
                             unsafe_allow_html=True)
                cols = st.columns([2, 2, 2])
                cols[0].markdown(f"**{row['name']}**  ·  `{row['inverter_id']}`")
                if fault_code == 0:
                    cols[1].markdown(status_badge_html("SEM FALHA", GREEN, "check_circle"), unsafe_allow_html=True)
                else:
                    cols[1].markdown(status_badge_html(f"F{fault_code:04d}", RED, "report"), unsafe_allow_html=True)
                    cols[2].caption(row.get("fault_description") or "")
                cols[2].caption(f"detectado em {fmt_ts(row['ts'])}")
                st.markdown("</div>", unsafe_allow_html=True)

    st.write("")
    st.markdown(f'<div class="card-title" style="font-size:15px;">{icon("history_toggle_off")} Últimas falhas internas do CFW-500 (P0050/P0060/P0070)</div>',
                 unsafe_allow_html=True)
    if latest.empty:
        st.info("Nenhum motor cadastrado ainda.", icon=":material/info:")
    else:
        inv_df = db.df_inverters()
        inv_id = st.selectbox(
            "Motor", options=inv_df["id"].tolist(),
            format_func=lambda i: inv_df.set_index("id").loc[i, "name"], key="faults_inv_select",
        )
        row = latest[latest["inverter_id"] == inv_id]
        if row.empty:
            st.info("Sem leituras para esse motor ainda.", icon=":material/info:")
        else:
            row = row.iloc[0]
            last_code = row.get("last_fault_code")
            if pd.isna(last_code) or int(last_code or 0) == 0:
                st.info("Nenhuma falha registrada no histórico interno desse motor.", icon=":material/info:")
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

    st.write("")
    st.markdown(f'<div class="card-title" style="font-size:15px;">{icon("list_alt")} Histórico de eventos de falha (log)</div>',
                 unsafe_allow_html=True)
    days = st.slider("Período (dias)", 1, 90, 7, key="faults_days")
    only_active = st.checkbox("Só falhas ativas agora", value=False)
    faults = db.df_faults(days=days, only_active=only_active)
    if faults.empty:
        st.info("Nenhum evento de falha registrado no período.", icon=":material/info:")
    else:
        show = faults[["ts", "name", "fault_code", "fault_description", "active"]].copy()
        show["ts"] = show["ts"].apply(fmt_ts)
        show["active"] = show["active"].map({1: "ativa", 0: "resetada"})
        show.columns = ["Data/hora", "Motor", "Código", "Descrição", "Estado"]
        st.dataframe(show, width="stretch", hide_index=True)
        st.download_button(
            "Exportar CSV", show.to_csv(index=False).encode("utf-8"), icon=":material/download:",
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
            st.info("Nenhuma falha no período/filtro selecionado.", icon=":material/info:")
        else:
            show = faults[["ts", "name", "fault_code", "fault_description", "active"]].copy()
            show["ts"] = show["ts"].apply(fmt_ts)
            st.dataframe(show, width="stretch", hide_index=True)
            st.download_button("Exportar CSV", show.to_csv(index=False).encode("utf-8"), icon=":material/download:",
                                 file_name="motorview_historico_falhas.csv", mime="text/csv")
    else:
        source = db.df_fast_current_recent(minutes=minutes, inverter_id=inv_filter) if variable == "current_max_A" \
            else db.df_telemetry_recent(minutes=minutes, inverter_id=inv_filter)
        if not source.empty:
            source = source[(source["ts"].dt.date >= date_start) & (source["ts"].dt.date <= date_end)]
        if source.empty or variable not in source.columns:
            st.info("Sem dados para esse filtro. 'Pico de corrente' depende do gateway publicar `current_fast`.",
                     icon=":material/info:")
        else:
            source = source.copy()
            source["ts_local"] = series_to_local(source["ts"])
            fig = px.line(source, x="ts_local", y=variable, color="name", color_discrete_sequence=CAT_COLORS,
                           labels={variable: VAR_OPTIONS[variable], "ts_local": ""})
            st.plotly_chart(style_fig(fig, height=380), width="stretch")

            st.markdown(f'<div class="card-title" style="font-size:14px;">{icon("table_rows")} Dados brutos</div>',
                         unsafe_allow_html=True)
            show = source[["ts", "name", variable]].sort_values("ts", ascending=False).copy()
            show["ts"] = show["ts"].apply(fmt_ts)
            st.dataframe(show, width="stretch", hide_index=True)
            st.download_button("Exportar CSV", show.to_csv(index=False).encode("utf-8"), icon=":material/download:",
                                 file_name=f"motorview_historico_{variable}.csv", mime="text/csv")


# ---------------------------------------------------------------------
# Conectividade
# ---------------------------------------------------------------------

elif page == "connectivity":
    inv_df = db.df_inverters()
    site_id = inv_df["site_id"].iloc[0] if not inv_df.empty else None
    gw = db.latest_gateway_status(site_id) if site_id else {"status": "desconhecido", "ts": None}
    gw_ts = pd.to_datetime(gw["ts"], utc=True).tz_localize(None) if gw["ts"] else None

    c1, c2 = st.columns(2)
    with c1:
        dot = "dot-on" if gw["status"] == "online" else "dot-off"
        st.markdown(
            f'<div class="card"><div class="card-title">{icon("cell_tower")} Gateway (Raspberry Pi)</div>'
            f'<div style="display:flex;align-items:center;gap:8px;margin-top:6px;">'
            f'<span class="{dot}"></span><b style="font-size:16px;">{gw["status"]}</b></div>'
            f'<div style="color:{MUTED};font-size:12px;margin-top:6px;">Última atualização: {fmt_ts(gw_ts)}</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        dot = "dot-on" if ingest_worker.connected else "dot-off"
        st.markdown(
            f'<div class="card"><div class="card-title">{icon("dns")} MQTT (assinante do dashboard)</div>'
            f'<div style="display:flex;align-items:center;gap:8px;margin-top:6px;">'
            f'<span class="{dot}"></span><b style="font-size:16px;">{"conectado" if ingest_worker.connected else "desconectado"}</b></div>'
            f'<div style="color:{MUTED};font-size:12px;margin-top:6px;">Broker: {cfg.get("host") or "—"}</div></div>',
            unsafe_allow_html=True,
        )

    st.write("")
    st.markdown(f'<div class="card-title" style="font-size:15px;">{icon("precision_manufacturing")} Motores</div>',
                 unsafe_allow_html=True)
    latest = db.df_latest_reading()
    if latest.empty:
        st.info("Nenhum motor cadastrado ainda.", icon=":material/info:")
    else:
        for _, row in latest.iterrows():
            label, color, mi, dashed = motor_status(row)
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 1.4, 2])
                c1.markdown(f"**{row['name']}** · `{row['inverter_id']}`")
                c2.markdown(status_badge_html(label, color, mi), unsafe_allow_html=True)
                c3.caption(f"última leitura: {fmt_ts(row['ts'])} ({time_ago(row['ts'])})")
    st.caption("Um motor sem comunicação não afeta a exibição dos demais.")

    st.write("")
    st.markdown(f'<div class="card-title" style="font-size:15px;">{icon("list_alt")} Log de conectividade</div>',
                 unsafe_allow_html=True)
    conn = db.df_connectivity(limit=50)
    if conn.empty:
        st.info("Sem eventos de conectividade registrados ainda.", icon=":material/info:")
    else:
        show = conn[["ts", "site_id", "status"]].copy()
        show["ts"] = show["ts"].apply(fmt_ts)
        st.dataframe(show, width="stretch", hide_index=True)


# ---------------------------------------------------------------------
# Relatórios
# ---------------------------------------------------------------------

elif page == "reports":
    st.markdown(f'<div class="card-title" style="font-size:15px;">{icon("summarize")} Resumo do período</div>',
                 unsafe_allow_html=True)
    days = st.slider("Período (dias)", 1, 90, 7, key="report_days")
    telem = db.df_telemetry_recent(minutes=days * 24 * 60)
    if telem.empty:
        st.info("Sem dados suficientes no período para gerar o relatório.", icon=":material/info:")
    else:
        agg = telem.groupby("name").agg(
            corrente_media_A=("current_A", "mean"),
            corrente_max_A=("current_A", "max"),
            leituras=("current_A", "count"),
            leituras_com_erro=("comm_error", "sum"),
        ).reset_index()
        agg["disponibilidade_pct"] = (100 * (1 - agg["leituras_com_erro"] / agg["leituras"])).round(1)
        agg = agg.round(2)

        faults = db.df_faults(days=days)
        r1, r2, r3 = st.columns(3)
        r1.markdown(stat_card("inventory_2", "Motores no relatório", f"{len(agg)}", BLUE), unsafe_allow_html=True)
        r2.markdown(stat_card("insights", "Disponibilidade média", f"{agg['disponibilidade_pct'].mean():.1f}%", ORANGE),
                     unsafe_allow_html=True)
        r3.markdown(stat_card("report_problem", "Eventos de falha", f"{len(faults)}", RED), unsafe_allow_html=True)
        st.write("")

        st.dataframe(agg, width="stretch", hide_index=True)
        st.download_button(
            "Exportar CSV", agg.to_csv(index=False).encode("utf-8"), icon=":material/download:",
            file_name=f"motorview_relatorio_{datetime.now():%Y%m%d_%H%M}.csv", mime="text/csv",
        )
        st.caption("Exportação em PDF pode ser incluída depois, seguindo o mesmo padrão do report_pdf.py do ProdView.")


st.markdown(
    f"<div style='text-align:center;color:{MUTED};font-size:12px;padding:24px 0 8px;'>"
    "ENDTECH · Soluções em Engenharia - Sistema MotorView</div>",
    unsafe_allow_html=True,
)
