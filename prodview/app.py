"""
ProdView — Monitoramento de Produção (versão web / Python)
============================================================
ENDTECH · Nacional Gás

Base funcional do software: menu superior em cards (sem barra lateral,
sem abas padrão), ícones Material Symbols em vez de emoji, muitos
gráficos de produção no estilo Power BI, e conexão com banco de dados
(SQLite local nesta demo — ver db.py para trocar pela base real).

Rodar:
    pip install -r requirements.txt
    streamlit run app.py
"""

import time
from datetime import datetime, date, timedelta

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

import db
import report_pdf

# ---------------------------------------------------------------------
# Paleta — ENDTECH / Nacional Gás, estilo Power BI (fundo claro, cards)
# ---------------------------------------------------------------------
BG = "#EEF1F6"
PANEL = "#FFFFFF"
BORDER = "#E2E6EE"
TEXT = "#1C2430"
MUTED = "#6E7787"

BLUE = "#14487D"      # azul institucional (confiança / segurança do gás)
BLUE_2 = "#1D6FB8"
BLUE_SOFT = "#E8F1FA"
RED = "#D62839"        # vermelho da chama / criticidade
RED_SOFT = "#FBEAEC"
GREEN = "#1E9E5A"
GREEN_SOFT = "#E7F7EE"
AMBER = "#F2A93E"
ORANGE = "#F2782F"

# ordem fixa por linha (paleta categórica validada, degraus claros)
CAT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
LINE_COLOR_MAP = {
    "Linha 01 · P13": CAT_COLORS[0],
    "Linha 02 · P20": CAT_COLORS[1],
    "Linha 03 · P45": CAT_COLORS[2],
    "Linha 04 · P13": CAT_COLORS[3],
}

# Navegação principal — ícone Material Symbols + rótulo (vira "card button")
NAV_ITEMS = [
    ("overview", "dashboard", "Visão Geral"),
    ("prod", "factory", "Produção"),
    ("lines", "conveyor_belt", "Linhas"),
    ("conn", "wifi_tethering", "Conectividade"),
    ("reports", "description", "Relatórios"),
]

st.set_page_config(
    page_title="ProdView — ENDTECH · Nacional Gás",
    page_icon=":material/local_gas_station:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------
# CSS — visual estilo Power BI / Material UI, cards brancos, menu no topo
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

  /* ícones Material Symbols (uso em HTML customizado) */
  .mi {{
      font-family: 'Material Symbols Rounded'; font-weight: normal; font-style: normal;
      font-size: 20px; line-height: 1; letter-spacing: normal; text-transform: none;
      display: inline-block; white-space: nowrap; word-wrap: normal; direction: ltr;
      -webkit-font-smoothing: antialiased; vertical-align: middle;
      font-variation-settings: 'FILL' 0, 'wght' 450, 'GRAD' 0, 'opsz' 24;
  }}

  /* cards */
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

  /* stat tiles (KPIs) */
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

  /* botões padrão */
  div.stButton > button {{
      background:{BLUE}; color:#fff; border:none; border-radius:8px;
      font-weight:600; padding:0.5rem 1rem;
  }}
  div.stButton > button:hover {{ background:{BLUE_2}; color:#fff; }}
  div.stDownloadButton > button {{
      background:{PANEL}; color:{BLUE}; border:1.5px solid {BLUE}; border-radius:8px; font-weight:600;
  }}
  div.stDownloadButton > button:hover {{ background:{BLUE_SOFT}; }}

  /* cards construídos com st.container(key=...) — evita <div> aberta/fechada
     em chamadas st.markdown separadas (cada chamada gera um nó isolado no DOM,
     o que deixava uma caixa branca vazia acima do conteúdo real) */
  .st-key-hero_prod, .st-key-hero_lines, .st-key-hero_downtime,
  .st-key-gauge_oee, .st-key-gauge_avail, .st-key-gauge_perf, .st-key-gauge_qual {{
      background:{PANEL}; border:1px solid {BORDER}; border-radius:14px;
      padding:16px 20px 20px; box-shadow:0 1px 2px rgba(16,24,40,.04), 0 4px 10px rgba(16,24,40,.05);
  }}

  /* menu principal — card buttons no topo (substitui as abas padrão) */
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
  .dot-on{{ display:inline-block; width:8px; height:8px; border-radius:50%; background:{GREEN}; }}
  .dot-off{{ display:inline-block; width:8px; height:8px; border-radius:50%; background:{RED}; }}

  .rank-row {{ display:flex; align-items:center; gap:10px; margin:9px 0; }}
  .rank-name {{ width:110px; font-size:12.5px; color:{TEXT}; font-weight:500; flex-shrink:0; }}
  .rank-track {{ flex:1; background:{BORDER}; border-radius:6px; height:10px; overflow:hidden; }}
  .rank-fill {{ height:100%; border-radius:6px; }}
  .rank-pct {{ width:42px; text-align:right; font-size:12.5px; font-weight:700; flex-shrink:0; }}

  .top-row {{ display:flex; justify-content:space-between; align-items:center; margin:10px 0; font-size:13px; }}
  .top-bar {{ background:{BORDER}; border-radius:5px; height:7px; flex:1; margin:0 10px; overflow:hidden; }}
  .top-bar-fill {{ height:100%; background:{RED}; border-radius:5px; }}

  .hero-num-lbl {{ font-size:12px; color:{MUTED}; }}
  .hero-num-val {{ font-size:22px; font-weight:700; color:{TEXT}; font-family:'Space Grotesk',sans-serif; }}
  .hero-num-val.big {{ font-size:34px; }}

  .node-card {{
      background:{BLUE_SOFT}; border:1px solid {BORDER}; border-radius:12px; padding:12px; text-align:center;
  }}
  .node-card .mi {{ font-size:17px; color:{BLUE}; }}
</style>
""", unsafe_allow_html=True)


def icon(name: str, size: int = 20, color: str | None = None) -> str:
    style = f"font-size:{size}px;" + (f"color:{color};" if color else "")
    return f'<span class="mi" style="{style}">{name}</span>'


def style_fig(fig, height=340, legend=True):
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


def meta_badge_svg(pct: int, size=76) -> str:
    pct_clamped = max(0, min(100, pct))
    color = GREEN if pct >= 95 else (AMBER if pct >= 75 else RED)
    r = (size - 10) / 2
    circumference = 2 * 3.14159265 * r
    dash = circumference * pct_clamped / 100
    return f"""
    <svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">
      <circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="{BORDER}" stroke-width="7"/>
      <circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="{color}" stroke-width="7"
        stroke-dasharray="{dash:.1f} {circumference:.1f}" stroke-linecap="round"
        transform="rotate(-90 {size/2} {size/2})"/>
      <text x="50%" y="52%" text-anchor="middle" dominant-baseline="middle"
        font-family="Space Grotesk, sans-serif" font-weight="700" font-size="15" fill="{TEXT}">{pct}%</text>
    </svg>
    """


def gauge_fig(value, title, color, height=210):
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"suffix": "%", "font": {"color": TEXT, "family": "Space Grotesk", "size": 26}},
        title={"text": title, "font": {"color": MUTED, "size": 13}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": MUTED, "tickfont": {"size": 9}},
            "bar": {"color": color, "thickness": 0.28},
            "bgcolor": BG,
            "borderwidth": 0,
            "steps": [
                {"range": [0, 60], "color": "#F3F5F8"},
                {"range": [60, 85], "color": "#EAEDF3"},
            ],
        },
    ))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", height=height, margin=dict(l=18, r=18, t=40, b=6),
                       font=dict(family="Inter, sans-serif", color=TEXT))
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
# Banco de dados
# ---------------------------------------------------------------------
db.init_db()
db.seed_if_empty()

if "last_update" not in st.session_state:
    st.session_state.last_update = datetime.now()
if "active_tab" not in st.session_state:
    st.session_state.active_tab = "overview"

# ---------------------------------------------------------------------
# Cabeçalho (marca + status + ações — tudo no topo, sem menu lateral)
# ---------------------------------------------------------------------
hour = datetime.now().hour
turno = "1º turno" if 6 <= hour < 14 else ("2º turno" if 14 <= hour < 22 else "3º turno")

hcol1, hcol2, hcol3, hcol4, hcol5 = st.columns([4.2, 1.6, 1.1, 1.1, 1.6])

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
              ENDTECH <span style="color:{MUTED};font-weight:500;font-size:13px;">· ProdView</span></div>
            <div style="font-size:12.5px;color:{MUTED};">Monitoramento de Produção — Nacional Gás</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with hcol2:
    st.markdown(
        f"""<div style="text-align:right;padding-top:6px;">
        <span class="badge">{icon('storage', 15)} Banco conectado</span><br>
        <span style="font-size:11.5px;color:{MUTED};">{db.DB_PATH.name}</span>
        </div>""",
        unsafe_allow_html=True,
    )

with hcol3:
    st.markdown(
        f"""<div style="text-align:right;padding-top:10px;font-size:12.5px;color:{MUTED};">
        {icon('schedule', 14)} {turno}<br><b style="color:{TEXT};">{datetime.now().strftime('%H:%M:%S')}</b></div>""",
        unsafe_allow_html=True,
    )

with hcol4:
    if st.button("Atualizar", icon=":material/refresh:", width="stretch"):
        db.simulate_tick()
        st.session_state.last_update = datetime.now()
        st.rerun()

with hcol5:
    if st.button("Regerar dados", icon=":material/restart_alt:", width="stretch"):
        db.seed_if_empty(force=True)
        st.rerun()

auto = st.toggle("Atualização automática a cada 8s", value=False)

# ---------------------------------------------------------------------
# Menu principal — card buttons no topo (substitui st.tabs)
# ---------------------------------------------------------------------
with st.container(key="nav_row"):
    nav_cols = st.columns(len(NAV_ITEMS))
    for col, (key, mi, label) in zip(nav_cols, NAV_ITEMS):
        is_active = st.session_state.active_tab == key
        with col:
            if st.button(
                label, icon=f":material/{mi}:", key=f"nav_{key}", width="stretch",
                type="primary" if is_active else "secondary",
            ):
                st.session_state.active_tab = key
                st.rerun()

st.markdown(f"<hr style='border:none;border-top:1px solid {BORDER};margin:14px 0 18px;'>", unsafe_allow_html=True)

# ---------------------------------------------------------------------
# Dados
# ---------------------------------------------------------------------
lines_df = db.df_lines()
kpis = db.kpis_today()
period = db.kpis_period()
target_progress = db.df_line_target_progress()
downtime_top = db.df_downtime_top(days=7, n=4)

# ---------------------------------------------------------------------
# Linha de destaque (hero) — estilo cards Power BI
# ---------------------------------------------------------------------
hc1, hc2, hc3 = st.columns((1.15, 1.3, 1.1))

with hc1, st.container(key="hero_prod"):
    top_a, top_b = st.columns((1.6, 1))
    with top_a:
        st.markdown(
            f'<div class="card-title">{icon("payments")} Produção</div>'
            '<div class="card-sub">Botijões contabilizados</div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
            <div class="hero-num-lbl">Hoje</div>
            <div class="hero-num-val big">{period['hoje']:,}</div>
            <div style="height:8px;"></div>
            <div class="hero-num-lbl">Semana</div>
            <div class="hero-num-val">{period['semana']:,}</div>
            <div style="height:6px;"></div>
            <div class="hero-num-lbl">Mês</div>
            <div class="hero-num-val">{period['mes']:,}</div>
            """.replace(",", "."),
            unsafe_allow_html=True,
        )
    with top_b:
        st.markdown(
            meta_badge_svg(period["meta_pct"])
            + f'<div style="font-size:11.5px;color:{MUTED};text-align:center;margin-top:4px;">Meta do dia</div>',
            unsafe_allow_html=True,
        )

with hc2, st.container(key="hero_lines"):
    st.markdown(
        f'<div class="card-title">{icon("flag")} Linhas por meta</div>'
        '<div class="card-sub">% da velocidade-alvo atingida hoje</div>',
        unsafe_allow_html=True,
    )
    if target_progress.empty or target_progress["avg_speed"].sum() == 0:
        st.markdown(f'<div style="color:{MUTED};font-size:13px;">Sem leituras suficientes ainda hoje.</div>', unsafe_allow_html=True)
    else:
        for _, row in target_progress.iterrows():
            pct = max(0, min(130, row["pct"]))
            color = GREEN if pct >= 95 else (AMBER if pct >= 75 else RED)
            st.markdown(
                f"""<div class="rank-row">
                  <div class="rank-name">{row['name']}</div>
                  <div class="rank-track"><div class="rank-fill" style="width:{min(pct,100)}%;background:{color};"></div></div>
                  <div class="rank-pct" style="color:{color};">{int(row['pct'])}%</div>
                </div>""",
                unsafe_allow_html=True,
            )

with hc3, st.container(key="hero_downtime"):
    st.markdown(
        f'<div class="card-title">{icon("report_problem")} Paradas — principais causas</div>'
        '<div class="card-sub">Últimos 7 dias</div>',
        unsafe_allow_html=True,
    )
    if downtime_top is None or downtime_top.empty:
        st.markdown(f'<div style="color:{MUTED};font-size:13px;">Sem paradas registradas.</div>', unsafe_allow_html=True)
    else:
        maxv = downtime_top["duration_min"].max()
        for _, row in downtime_top.iterrows():
            width = 100 * row["duration_min"] / maxv if maxv else 0
            st.markdown(
                f"""<div class="top-row">
                  <div style="width:150px;">{row['category']}</div>
                  <div class="top-bar"><div class="top-bar-fill" style="width:{width:.0f}%;"></div></div>
                  <div style="font-weight:700;color:{TEXT};">{row['duration_min']:.0f} min</div>
                </div>""",
                unsafe_allow_html=True,
            )

st.write("")

# ---------------------------------------------------------------------
# KPIs — stat cards com ícones Material
# ---------------------------------------------------------------------
k1, k2, k3, k4 = st.columns(4)
k1.markdown(stat_card("inventory_2", "Botijões contabilizados hoje", f"{kpis['total_hoje']:,}".replace(",", "."), BLUE), unsafe_allow_html=True)
k2.markdown(stat_card("insights", "OEE médio (últimas 24h)", f"{kpis['oee_medio']:.1f}%", ORANGE), unsafe_allow_html=True)
k3.markdown(stat_card("factory", "Linhas ativas", f"{kpis['linhas_ativas']}/{kpis['linhas_total']}", GREEN), unsafe_allow_html=True)
k4.markdown(stat_card("speed", "Velocidade atual (total)", f"{kpis['velocidade_total']:.0f} un/min", BLUE_2), unsafe_allow_html=True)

st.write("")

# ===================== VISÃO GERAL =====================
if st.session_state.active_tab == "overview":
    oee = db.oee_breakdown(days=1)
    g1, g2, g3, g4 = st.columns(4)
    with g1, st.container(key="gauge_oee"):
        st.plotly_chart(gauge_fig(oee["oee"], "OEE geral", BLUE), width="stretch", config={"displayModeBar": False})
    with g2, st.container(key="gauge_avail"):
        st.plotly_chart(gauge_fig(oee["availability"], "Disponibilidade", ORANGE), width="stretch", config={"displayModeBar": False})
    with g3, st.container(key="gauge_perf"):
        st.plotly_chart(gauge_fig(oee["performance"], "Performance", BLUE_2), width="stretch", config={"displayModeBar": False})
    with g4, st.container(key="gauge_qual"):
        st.plotly_chart(gauge_fig(oee["quality"], "Qualidade", GREEN), width="stretch", config={"displayModeBar": False})

    st.write("")
    readings = db.df_readings_today()
    today_readings = readings[readings["ts"].dt.date == date.today()] if not readings.empty else readings

    col1, col2 = st.columns((2, 1))
    with col1:
        st.markdown("##### Produção acumulada hoje, por linha")
        if today_readings.empty:
            st.info("Sem leituras registradas para hoje ainda. Clique em **Atualizar** no topo da página.", icon=":material/info:")
        else:
            fig = px.line(
                today_readings, x="ts", y="cumulative_count", color="name",
                color_discrete_map=LINE_COLOR_MAP,
                labels={"ts": "Horário", "cumulative_count": "Botijões (acumulado)", "name": "Linha"},
            )
            fig.update_traces(line=dict(width=2.5))
            st.plotly_chart(style_fig(fig), width="stretch")

    with col2:
        st.markdown("##### Participação por linha (hoje)")
        if today_readings.empty:
            st.info("Sem dados ainda.", icon=":material/info:")
        else:
            latest = today_readings.sort_values("ts").groupby("name").tail(1)
            fig = px.pie(
                latest, names="name", values="cumulative_count", hole=0.55,
                color="name", color_discrete_map=LINE_COLOR_MAP,
            )
            fig.update_traces(textinfo="percent", textfont_color=TEXT)
            st.plotly_chart(style_fig(fig, height=340, legend=True), width="stretch")

    col3, col4 = st.columns((1, 1))
    with col3:
        st.markdown("##### Produção total hoje, por linha")
        if today_readings.empty:
            st.info("Sem dados ainda.", icon=":material/info:")
        else:
            latest = today_readings.sort_values("ts").groupby("name").tail(1).sort_values("name")
            fig = px.bar(
                latest, x="name", y="cumulative_count", color="name",
                color_discrete_map=LINE_COLOR_MAP,
                labels={"name": "", "cumulative_count": "Botijões"},
            )
            fig.update_layout(showlegend=False)
            st.plotly_chart(style_fig(fig, height=300, legend=False), width="stretch")

    with col4:
        st.markdown("##### Produção diária (7 dias) — total geral")
        daily7 = db.df_daily_production(days=7)
        if daily7.empty:
            st.info("Sem histórico ainda.", icon=":material/info:")
        else:
            agg = daily7.groupby("prod_date", as_index=False)["units"].sum()
            fig = px.area(agg, x="prod_date", y="units", labels={"prod_date": "Data", "units": "Botijões"})
            fig.update_traces(line_color=BLUE, fillcolor="rgba(20,72,125,0.12)")
            st.plotly_chart(style_fig(fig, height=300, legend=False), width="stretch")

# ===================== PRODUÇÃO =====================
elif st.session_state.active_tab == "prod":
    period_label = st.radio(
        "Período", ["Últimos 7 dias", "Últimos 15 dias", "Últimos 30 dias"],
        horizontal=True, label_visibility="collapsed",
    )
    days = {"Últimos 7 dias": 7, "Últimos 15 dias": 15, "Últimos 30 dias": 30}[period_label]

    daily = db.df_daily_production(days=days)
    downtime = db.df_downtime(days=days)

    st.markdown("##### Produção diária por linha")
    if daily.empty:
        st.info("Sem histórico ainda.", icon=":material/info:")
    else:
        agg = daily.groupby(["prod_date", "name"], as_index=False)["units"].sum()
        fig = px.bar(
            agg, x="prod_date", y="units", color="name", barmode="group",
            color_discrete_map=LINE_COLOR_MAP,
            labels={"prod_date": "Data", "units": "Botijões", "name": "Linha"},
        )
        st.plotly_chart(style_fig(fig, height=380), width="stretch")

    c1, c2 = st.columns((1, 1))
    with c1:
        st.markdown("##### OEE médio por linha, ao longo do tempo")
        if daily.empty:
            st.info("Sem histórico ainda.", icon=":material/info:")
        else:
            agg_oee = daily.groupby(["prod_date", "name"], as_index=False)["oee_pct"].mean()
            fig = px.line(
                agg_oee, x="prod_date", y="oee_pct", color="name", markers=True,
                color_discrete_map=LINE_COLOR_MAP,
                labels={"prod_date": "Data", "oee_pct": "OEE (%)", "name": "Linha"},
            )
            fig.add_hline(y=85, line_dash="dot", line_color=RED, annotation_text="meta 85%",
                           annotation_font_color=RED)
            st.plotly_chart(style_fig(fig, height=340), width="stretch")

    with c2:
        st.markdown("##### Paradas — causas (Pareto)")
        if downtime.empty:
            st.info("Sem paradas registradas no período.", icon=":material/info:")
        else:
            pareto = downtime.groupby("category", as_index=False)["duration_min"].sum()
            pareto = pareto.sort_values("duration_min", ascending=False)
            pareto["cum_pct"] = 100 * pareto["duration_min"].cumsum() / pareto["duration_min"].sum()
            fig = go.Figure()
            fig.add_bar(x=pareto["category"], y=pareto["duration_min"], name="Minutos parados",
                        marker_color=BLUE)
            fig.add_trace(go.Scatter(x=pareto["category"], y=pareto["cum_pct"], name="% acumulado",
                                      yaxis="y2", mode="lines+markers", line=dict(color=RED, width=2)))
            fig.update_layout(
                yaxis=dict(title="Minutos parados"),
                yaxis2=dict(title="% acumulado", overlaying="y", side="right", range=[0, 105],
                            showgrid=False),
            )
            st.plotly_chart(style_fig(fig, height=340), width="stretch")

    st.markdown("##### Minutos parados por linha, por categoria")
    if downtime.empty:
        st.info("Sem paradas registradas no período.", icon=":material/info:")
    else:
        heat = downtime.groupby(["name", "category"], as_index=False)["duration_min"].sum()
        pivot = heat.pivot(index="name", columns="category", values="duration_min").fillna(0)
        fig = px.imshow(
            pivot, color_continuous_scale=["#F3F5F8", "#8fb9dd", BLUE],
            labels=dict(x="Categoria", y="Linha", color="min parado"),
            aspect="auto",
        )
        st.plotly_chart(style_fig(fig, height=320, legend=False), width="stretch")

# ===================== LINHAS =====================
elif st.session_state.active_tab == "lines":
    readings = db.df_readings_today()
    if readings.empty:
        st.info("Sem leituras ainda. Clique em **Atualizar** no topo da página para simular uma nova leitura do CLP.", icon=":material/info:")
        latest = pd.DataFrame()
    else:
        latest = readings.sort_values("ts").groupby("line_id").tail(1).sort_values("line_id")

    st.markdown("##### Status atual das linhas")
    if not latest.empty:
        cols = st.columns(len(latest))
        for col, (_, row) in zip(cols, latest.iterrows()):
            dot = "dot-on" if row["status"] == "on" else "dot-off"
            with col:
                st.markdown(
                    f"""
                    <div class="card">
                      <div style="display:flex;justify-content:space-between;align-items:center;">
                        <b style="font-size:13px;">{row['name']}</b><span class="{dot}"></span>
                      </div>
                      <div style="font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:26px;margin-top:8px;color:{TEXT};">{row['speed']:.0f}</div>
                      <div style="color:{MUTED};font-size:12px;">un/min · {row['cumulative_count']:,} hoje</div>
                    </div>
                    """.replace(",", "."),
                    unsafe_allow_html=True,
                )

    st.write("")
    line_pick = st.selectbox("Detalhar linha", lines_df["name"].tolist())
    line_id = int(lines_df.loc[lines_df["name"] == line_pick, "id"].iloc[0])

    hist = readings[readings["line_id"] == line_id] if not readings.empty else readings
    c1, c2 = st.columns((2, 1))
    with c1:
        st.markdown(f"##### Velocidade — {line_pick}")
        if hist.empty:
            st.info("Sem leituras para esta linha ainda.", icon=":material/info:")
        else:
            fig = px.area(hist, x="ts", y="speed", labels={"ts": "Horário", "speed": "un/min"})
            fig.update_traces(line_color=LINE_COLOR_MAP.get(line_pick, BLUE),
                               fillcolor="rgba(20,72,125,0.10)")
            st.plotly_chart(style_fig(fig, height=320, legend=False), width="stretch")

    with c2:
        st.markdown("##### Registrar ação")
        with st.form("form_leitura", clear_on_submit=True):
            st.caption("Lançamento manual (grava direto no banco)")
            speed_in = st.number_input("Velocidade (un/min)", min_value=0.0, max_value=60.0, value=15.0, step=0.5)
            status_in = st.selectbox("Status", ["on", "off"], format_func=lambda s: "Em produção" if s == "on" else "Parada")
            submitted = st.form_submit_button("Registrar leitura", icon=":material/save:", width="stretch")
            if submitted:
                db.insert_manual_reading(line_id, speed_in, status_in)
                st.success("Leitura registrada no banco de dados.", icon=":material/check_circle:")
                st.rerun()

        with st.form("form_parada", clear_on_submit=True):
            st.caption("Registrar parada de linha")
            cat_in = st.selectbox("Categoria", [c for c, _ in db.DOWNTIME_CATEGORIES])
            dur_in = st.number_input("Duração (min)", min_value=1.0, max_value=480.0, value=10.0, step=1.0)
            reason_in = st.text_input("Motivo", placeholder="Descreva brevemente...")
            submitted2 = st.form_submit_button("Registrar parada", icon=":material/block:", width="stretch")
            if submitted2:
                db.insert_downtime(line_id, dur_in, cat_in, reason_in or "Não informado")
                st.success("Parada registrada no banco de dados.", icon=":material/check_circle:")
                st.rerun()

# ===================== CONECTIVIDADE =====================
elif st.session_state.active_tab == "conn":
    st.markdown("##### Conectividade e redundância")
    st.caption(
        "Link primário via Ethernet/fibra da planta, com contingência automática por 4G "
        "homologado — sem intervenção manual em caso de queda."
    )

    conn_log = db.df_connectivity(limit=1)
    link_down = not conn_log.empty and conn_log.iloc[0]["event"] == "queda"

    nodes = [("sensors", "Sensores"), ("router", "Gateway local"), ("wifi", "Roteador WAN"), ("dns", "Servidor / VPN")]
    node_labels = ["Campo", "Painel", "Saída", "Destino"]
    ncols = st.columns(len(nodes) * 2 - 1)
    for i, (mi, n) in enumerate(nodes):
        with ncols[i * 2]:
            st.markdown(
                f"""
                <div class="node-card">
                  <div style="color:{MUTED};font-size:11px;">{node_labels[i]}</div>
                  <div style="font-weight:600;font-size:13px;margin-top:4px;color:{TEXT};
                       display:flex;align-items:center;justify-content:center;gap:6px;">
                    {icon(mi)}{n}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        if i < len(nodes) - 1:
            with ncols[i * 2 + 1]:
                st.markdown(f"<div style='text-align:center;color:{MUTED};padding-top:20px;'>{icon('arrow_forward', 18)}</div>", unsafe_allow_html=True)

    st.write("")
    lc1, lc2 = st.columns(2)
    eth_dot = "dot-off" if link_down else "dot-on"
    g4_dot = "dot-on" if link_down else "dot-off"
    lc1.markdown(
        f'<div style="background:{PANEL};border:1px solid {BORDER};border-radius:10px;padding:10px 14px;">'
        f'<span class="{eth_dot}"></span>&nbsp; {icon("settings_ethernet", 16)} Ethernet / fibra (primário) — '
        f'<span style="color:{MUTED};font-size:12px;">'
        f'{"indisponível" if link_down else "ativo"}</span></div>',
        unsafe_allow_html=True,
    )
    lc2.markdown(
        f'<div style="background:{PANEL};border:1px solid {BORDER};border-radius:10px;padding:10px 14px;">'
        f'<span class="{g4_dot}"></span>&nbsp; {icon("signal_cellular_alt", 16)} 4G homologado (contingência) — '
        f'<span style="color:{MUTED};font-size:12px;">'
        f'{"ativo (contingência)" if link_down else "standby"}</span></div>',
        unsafe_allow_html=True,
    )

    st.write("")
    if st.button("Simular queda do link principal", icon=":material/wifi_off:"):
        ph = st.empty()
        db.log_connectivity("ethernet", "queda", "Link Ethernet/fibra indisponível.")
        ph.warning("Link Ethernet/fibra indisponível.", icon=":material/wifi_off:")
        time.sleep(1.2)
        db.log_connectivity("4g", "ativo", "Chaveamento automático para 4G concluído — coleta de dados não interrompida.")
        ph.success("Chaveamento automático para 4G concluído — coleta de dados não interrompida.", icon=":material/wifi:")
        time.sleep(1.6)
        db.log_connectivity("ethernet", "restabelecido", "Link Ethernet/fibra restabelecido — rota primária retomada.")
        ph.success("Link Ethernet/fibra restabelecido — rota primária retomada.", icon=":material/check_circle:")
        time.sleep(0.8)
        st.rerun()

    st.markdown("##### Histórico de eventos")
    log_df = db.df_connectivity(limit=40)
    if log_df.empty:
        st.info("Sem eventos registrados.", icon=":material/info:")
    else:
        show = log_df[["ts", "link", "event", "note"]].rename(
            columns={"ts": "Data/hora", "link": "Link", "event": "Evento", "note": "Observação"}
        )
        st.dataframe(show, width="stretch", hide_index=True)

# ===================== RELATÓRIOS =====================
elif st.session_state.active_tab == "reports":
    st.markdown("##### Relatório de produção")
    dcol1, dcol2, dcol3 = st.columns((1, 1, 1))
    start_default = date.today() - timedelta(days=7)
    start_date = dcol1.date_input("De", value=start_default)
    end_date = dcol2.date_input("Até", value=date.today())
    line_filter = dcol3.multiselect("Linhas", lines_df["name"].tolist(), default=lines_df["name"].tolist())

    daily_all = db.df_daily_production(days=(date.today() - start_date).days + 1)
    if not daily_all.empty:
        mask = (
            (daily_all["prod_date"].dt.date >= start_date)
            & (daily_all["prod_date"].dt.date <= end_date)
            & (daily_all["name"].isin(line_filter))
        )
        report = daily_all.loc[mask].copy()
    else:
        report = daily_all

    if report.empty:
        st.info("Nenhum dado para o período/linhas selecionados.", icon=":material/info:")
    else:
        r1, r2, r3 = st.columns(3)
        r1.markdown(stat_card("inventory_2", "Total de botijões", f"{int(report['units'].sum()):,}".replace(",", "."), BLUE), unsafe_allow_html=True)
        r2.markdown(stat_card("insights", "OEE médio", f"{report['oee_pct'].mean():.1f}%", ORANGE), unsafe_allow_html=True)
        r3.markdown(stat_card("report_problem", "Minutos parados", f"{report['downtime_min'].sum():.0f}", RED), unsafe_allow_html=True)
        st.write("")

        show = report[["prod_date", "name", "shift", "units", "oee_pct", "downtime_min"]].rename(
            columns={"prod_date": "Data", "name": "Linha", "shift": "Turno",
                     "units": "Botijões", "oee_pct": "OEE (%)", "downtime_min": "Parada (min)"}
        ).sort_values(["Data", "Linha"])
        st.dataframe(show, width="stretch", hide_index=True)

        dl1, dl2 = st.columns(2)
        csv = show.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
        dl1.download_button(
            "Exportar CSV", data=csv, icon=":material/download:",
            file_name=f"prodview_relatorio_{start_date}_{end_date}.csv",
            mime="text/csv", width="stretch",
        )

        dt_period = db.df_downtime(days=(date.today() - start_date).days + 1)
        pdf_bytes = report_pdf.build_pdf(
            report_df=show,
            kpis={
                "total": int(report["units"].sum()),
                "oee": float(report["oee_pct"].mean()),
                "downtime": float(report["downtime_min"].sum()),
            },
            start_date=start_date, end_date=end_date,
            downtime_df=dt_period,
        )
        dl2.download_button(
            "Exportar PDF", data=pdf_bytes, icon=":material/picture_as_pdf:",
            file_name=f"prodview_relatorio_{start_date}_{end_date}.pdf",
            mime="application/pdf", width="stretch",
        )

st.markdown(
    f"<div style='text-align:center;color:{MUTED};font-size:12px;padding:24px 0 8px;'>"
    "ENDTECH · Soluções em Engenharia — Sistema ProdView</div>",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------
# Atualização automática (opcional)
# ---------------------------------------------------------------------
if auto:
    time.sleep(8)
    db.simulate_tick()
    st.session_state.last_update = datetime.now()
    st.rerun()
