"""
MotorView - Monitoramento de Motores/Inversores em Tempo Real
=================================================================
ENDTECH

Recebe telemetria dos inversores (corrente, tensão, frequência, rpm,
torque, código de falha) publicada via MQTT pelo motorview/gateway.py
(Raspberry Pi + Modbus RTU) e mostra em tempo real, com histórico
gravado em banco (SQLite nesta demo - ver db.py para trocar pela base
definitiva).

Rodar:
    pip install -r requirements.txt
    streamlit run app.py
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import db
from config import mqtt_config
from mqtt_ingest import MqttIngestWorker

# ---------------------------------------------------------------------
# Paleta - ENDTECH, estilo industrial (mesma linha visual do ProdView)
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
  div.block-container {{ padding-top: 1.4rem; padding-bottom: 2rem; max-width: 1360px; }}
  h1, h2, h3 {{ font-family: 'Space Grotesk', sans-serif !important; letter-spacing: -0.01em; color:{TEXT}; }}

  div[data-testid="stMetric"] {{
      background:{PANEL}; border:1px solid {BORDER}; border-radius:14px;
      padding:14px 18px; box-shadow:0 1px 2px rgba(16,24,40,.04);
  }}
  div[data-testid="stMetricValue"] {{ color:{TEXT}; font-weight:700; }}
  div[data-testid="stMetricLabel"] {{ color:{MUTED}; }}

  .badge {{ display:inline-flex; align-items:center; gap:5px; font-weight:700; font-size:12px;
            padding:3px 10px; border-radius:999px; }}
  .badge-green {{ background:{GREEN_SOFT}; color:{GREEN}; }}
  .badge-red {{ background:{RED_SOFT}; color:{RED}; }}
  .badge-amber {{ background:{AMBER_SOFT}; color:#8a5a10; }}
  .badge-muted {{ background:#EEF0F4; color:{MUTED}; }}

  .header-row {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:1rem; }}
  .brand {{ font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:26px; color:{TEXT}; }}
  .brand span {{ color:{BLUE}; }}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------
# Setup: banco + assinante MQTT (uma única instância por processo)
# ---------------------------------------------------------------------

@st.cache_resource
def bootstrap():
    db.init_db()
    worker = MqttIngestWorker(mqtt_config())
    cfg = mqtt_config()
    if cfg.get("host"):
        worker.start()
    return worker


ingest_worker = bootstrap()

cfg = mqtt_config()
mqtt_configured = bool(cfg.get("host"))

st.markdown(f"""
<div class="header-row">
  <div class="brand">Motor<span>View</span> <span style="color:{MUTED};font-weight:500;font-size:14px;">· ENDTECH</span></div>
</div>
""", unsafe_allow_html=True)

if not mqtt_configured:
    st.warning(
        "MQTT não configurado. Defina MOTORVIEW_MQTT_HOST/USERNAME/PASSWORD em `.streamlit/secrets.toml` "
        "(deploy) ou num arquivo `.env` local (veja `secrets.example.toml` e o README desta pasta)."
    )
elif ingest_worker.connected:
    st.markdown('<span class="badge badge-green">● MQTT conectado</span>', unsafe_allow_html=True)
else:
    st.markdown('<span class="badge badge-amber">● Conectando ao MQTT...</span>', unsafe_allow_html=True)

tab_overview, tab_live, tab_faults, tab_history = st.tabs(
    ["Visão Geral", "Corrente em Tempo Real", "Falhas", "Histórico"]
)


def status_badge(row) -> str:
    if row.get("comm_error"):
        return '<span class="badge badge-muted">● sem leitura</span>'
    if (row.get("fault_code") or 0) > 0:
        return '<span class="badge badge-red">● em falha</span>'
    # db.py normaliza "ts" para UTC naive (tz_localize(None) após parse com utc=True)
    if datetime.now(timezone.utc).replace(tzinfo=None) - row["ts"].to_pydatetime() > timedelta(minutes=2):
        return '<span class="badge badge-muted">● offline</span>'
    return '<span class="badge badge-green">● operando</span>'


# ---------------------------------------------------------------------
# Aba: Visão Geral
# ---------------------------------------------------------------------

with tab_overview:
    kpis = db.kpis_now()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Inversores cadastrados", kpis["inversores"])
    c2.metric("Online agora", kpis["online"])
    c3.metric("Falhas ativas", kpis["falhas_ativas"])
    c4.metric("Corrente total (A)", kpis["corrente_total"])

    st.markdown("#### Status por inversor")
    latest = db.df_latest_reading()
    if latest.empty:
        st.info("Nenhuma leitura recebida ainda. Verifique se o gateway (Raspberry Pi) está publicando no MQTT.")
    else:
        for _, row in latest.iterrows():
            with st.container(border=True):
                cols = st.columns([3, 2, 2, 2, 2, 2])
                cols[0].markdown(f"**{row['name']}**  \n`{row['inverter_id']}`")
                cols[1].markdown(status_badge(row), unsafe_allow_html=True)
                cols[2].metric("Corrente", f"{row['current_A']:.1f} A" if pd.notna(row['current_A']) else "-")
                cols[3].metric("Frequência", f"{row['frequency_Hz']:.1f} Hz" if pd.notna(row['frequency_Hz']) else "-")
                cols[4].metric("Rotação", f"{row['speed_rpm']:.0f} rpm" if pd.notna(row['speed_rpm']) else "-")
                cols[5].markdown(f"<span style='color:{MUTED};font-size:12px;'>última leitura<br>{row['ts']}</span>",
                                  unsafe_allow_html=True)


# ---------------------------------------------------------------------
# Aba: Corrente em Tempo Real (auto-refresh via st.fragment)
# ---------------------------------------------------------------------

with tab_live:
    range_minutes = st.select_slider(
        "Janela de tempo", options=[5, 15, 30, 60, 180], value=15, format_func=lambda m: f"{m} min"
    )
    all_inv = db.df_inverters()
    selected = st.multiselect(
        "Inversores", options=all_inv["id"].tolist() if not all_inv.empty else [],
        default=all_inv["id"].tolist() if not all_inv.empty else [],
        format_func=lambda i: all_inv.set_index("id").loc[i, "name"] if not all_inv.empty else i,
    )

    @st.fragment(run_every="1s")
    def live_current_chart(range_minutes: int, selected_ids: list):
        fast = db.df_fast_current_recent(minutes=range_minutes)
        if not fast.empty and selected_ids:
            fast = fast[fast["inverter_id"].isin(selected_ids)]

        if not fast.empty:
            latest = fast.sort_values("ts").groupby("inverter_id").tail(1)
            c1, c2, c3 = st.columns(3)
            c1.metric("Maior pico na janela", f"{fast['current_max_A'].max():.1f} A")
            c2.metric("Corrente média", f"{fast['current_avg_A'].mean():.1f} A")
            c3.metric("Amostras representadas", f"{int(fast['samples'].fillna(0).sum()):,}".replace(",", "."))

            fig = go.Figure()
            for idx, (inv_id, sub) in enumerate(fast.groupby("inverter_id")):
                color = CAT_COLORS[idx % len(CAT_COLORS)]
                name = sub["name"].iloc[0] if pd.notna(sub["name"].iloc[0]) else inv_id
                fig.add_trace(go.Scatter(
                    x=sub["ts"], y=sub["current_avg_A"], mode="lines",
                    name=f"{name} · média",
                    line=dict(color=color, width=2),
                ))
                fig.add_trace(go.Scatter(
                    x=sub["ts"], y=sub["current_max_A"], mode="lines",
                    name=f"{name} · pico",
                    line=dict(color=color, width=1, dash="dot"),
                ))
            fig.update_layout(
                height=430, margin=dict(l=10, r=10, t=30, b=10),
                plot_bgcolor=PANEL, paper_bgcolor=PANEL,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                yaxis_title="Corrente (A)", xaxis_title=None,
            )
            st.plotly_chart(fig, use_container_width=True, key=f"live_current_fast_{range_minutes}")
            st.caption(
                "A linha contínua é a média de cada janela MQTT; a pontilhada preserva "
                "o maior pico visto nas amostras locais rápidas."
            )
        else:
            # Fallback para instalações sem fast_monitoring.
            df = db.df_telemetry_recent(minutes=range_minutes)
            if not df.empty and selected_ids:
                df = df[df["inverter_id"].isin(selected_ids)]
            if df.empty:
                st.info("Sem dados no período selecionado.")
                return

            fig = go.Figure()
            for idx, (inv_id, sub) in enumerate(df.groupby("inverter_id")):
                color = CAT_COLORS[idx % len(CAT_COLORS)]
                fig.add_trace(go.Scatter(
                    x=sub["ts"], y=sub["current_A"], mode="lines", name=sub["name"].iloc[0],
                    line=dict(color=color, width=2),
                ))
            fig.update_layout(
                height=420, margin=dict(l=10, r=10, t=30, b=10),
                plot_bgcolor=PANEL, paper_bgcolor=PANEL,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                yaxis_title="Corrente (A)", xaxis_title=None,
            )
            st.plotly_chart(fig, use_container_width=True, key=f"live_current_{range_minutes}")

        with st.expander("Outras variáveis (frequência, rotação, torque)"):
            df = db.df_telemetry_recent(minutes=range_minutes)
            if not df.empty and selected_ids:
                df = df[df["inverter_id"].isin(selected_ids)]
            if df.empty:
                st.info("Sem telemetria completa no período.")
                return
            metric = st.selectbox(
                "Variável", ["frequency_Hz", "speed_rpm", "torque_pct", "dc_link_V", "voltage_V"],
                format_func=lambda m: {
                    "frequency_Hz": "Frequência (Hz)", "speed_rpm": "Rotação (rpm)",
                    "torque_pct": "Torque (%)", "dc_link_V": "Tensão do link CC (V)",
                    "voltage_V": "Tensão de saída (V)",
                }[m],
                key="live_metric_select",
            )
            fig2 = px.line(df, x="ts", y=metric, color="name", color_discrete_sequence=CAT_COLORS)
            fig2.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor=PANEL, paper_bgcolor=PANEL)
            st.plotly_chart(fig2, use_container_width=True, key=f"live_other_{metric}")

    live_current_chart(range_minutes, selected)


# ---------------------------------------------------------------------
# Aba: Falhas
# ---------------------------------------------------------------------

with tab_faults:
    only_active = st.checkbox("Mostrar só falhas ativas agora", value=False)
    days = st.slider("Período (dias)", 1, 90, 7)
    faults = db.df_faults(days=days, only_active=only_active)

    active_now = db.df_faults(days=days, only_active=True)
    if not active_now.empty:
        st.error(f"⚠ {len(active_now)} inversor(es) com falha ativa agora.")
        for _, row in active_now.iterrows():
            description = row["fault_description"] or f"código {int(row['fault_code'])}"
            st.markdown(
                f"<span class='badge badge-red'>● {row['name']}</span> "
                f"— {description}"
                f" <span style='color:{MUTED};font-size:12px;'>({row['ts']})</span>",
                unsafe_allow_html=True,
            )

    st.markdown("#### Últimas falhas registradas nos inversores")
    latest_faults = db.df_latest_reading()
    if latest_faults.empty:
        st.info("Nenhuma leitura disponível para consultar o histórico interno dos inversores.")
    else:
        for _, row in latest_faults.iterrows():
            last_code = row.get("last_fault_code")
            if pd.isna(last_code) or int(last_code or 0) == 0:
                continue
            with st.container(border=True):
                st.markdown(f"**{row['name']}** · última falha: **F{int(last_code):04d}**")
                if row.get("last_fault_description"):
                    st.caption(str(row.get("last_fault_description")))
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Corrente na falha", f"{row.get('last_fault_current_A'):.1f} A" if pd.notna(row.get("last_fault_current_A")) else "-")
                c2.metric("Barramento CC", f"{row.get('last_fault_dc_link_V'):.0f} V" if pd.notna(row.get("last_fault_dc_link_V")) else "-")
                c3.metric("Frequência", f"{row.get('last_fault_frequency_Hz'):.1f} Hz" if pd.notna(row.get("last_fault_frequency_Hz")) else "-")
                c4.metric("Temp. IGBT", f"{row.get('last_fault_igbt_temp_C'):.0f} °C" if pd.notna(row.get("last_fault_igbt_temp_C")) else "-")

                history_parts = []
                second = row.get("second_fault_code")
                third = row.get("third_fault_code")
                if pd.notna(second) and int(second or 0) > 0:
                    history_parts.append(f"2ª: F{int(second):04d}")
                if pd.notna(third) and int(third or 0) > 0:
                    history_parts.append(f"3ª: F{int(third):04d}")
                if history_parts:
                    st.caption(" · ".join(history_parts))

    st.markdown("#### Histórico de falhas")
    if faults.empty:
        st.info("Nenhuma falha registrada no período selecionado.")
    else:
        show = faults[["ts", "name", "fault_code", "fault_description", "active"]].copy()
        show["active"] = show["active"].map({1: "ativa", 0: "resetada"})
        show.columns = ["Data/hora", "Inversor", "Código", "Descrição", "Estado"]
        st.dataframe(show, use_container_width=True, hide_index=True)
        st.download_button(
            "Exportar CSV", show.to_csv(index=False).encode("utf-8"),
            file_name=f"motorview_falhas_{datetime.now():%Y%m%d_%H%M}.csv", mime="text/csv",
        )


# ---------------------------------------------------------------------
# Aba: Histórico (dados brutos + gráfico de período + export)
# ---------------------------------------------------------------------

with tab_history:
    col1, col2 = st.columns(2)
    hist_minutes = col1.select_slider(
        "Janela de tempo", options=[60, 360, 1440, 4320, 10080], value=1440,
        format_func=lambda m: f"{m // 60} h" if m < 1440 else f"{m // 1440} d",
        key="hist_range",
    )
    inv_df = db.df_inverters()
    hist_inv = col2.selectbox(
        "Inversor", options=["(todos)"] + (inv_df["id"].tolist() if not inv_df.empty else []),
        format_func=lambda i: "Todos" if i == "(todos)" else inv_df.set_index("id").loc[i, "name"],
    )

    hist_df = db.df_telemetry_recent(minutes=hist_minutes, inverter_id=None if hist_inv == "(todos)" else hist_inv)
    if hist_df.empty:
        st.info("Sem dados registrados no período selecionado.")
    else:
        fig = px.line(hist_df, x="ts", y="current_A", color="name", color_discrete_sequence=CAT_COLORS,
                       labels={"current_A": "Corrente (A)", "ts": ""})
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=20, b=10), plot_bgcolor=PANEL, paper_bgcolor=PANEL)
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("#### Dados brutos")
        cols_show = ["ts", "name", "current_A", "voltage_V", "frequency_Hz", "speed_rpm",
                     "torque_pct", "dc_link_V", "fault_code", "fault_description", "comm_error"]
        st.dataframe(hist_df[cols_show].sort_values("ts", ascending=False), use_container_width=True, hide_index=True)
        st.download_button(
            "Exportar CSV", hist_df[cols_show].to_csv(index=False).encode("utf-8"),
            file_name=f"motorview_historico_{datetime.now():%Y%m%d_%H%M}.csv", mime="text/csv",
        )
