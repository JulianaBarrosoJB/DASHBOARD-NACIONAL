"""MotorView - relatório PDF completo para cliente.

Layout inspirado no ProdView: resumo executivo, gráficos, tabelas por motor,
tendência de corrente, resumo diário e histórico de falhas.
"""

from io import BytesIO
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
    Image, KeepTogether, PageBreak,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER

BASE_DIR = Path(__file__).resolve().parent
LOGO_PATH = BASE_DIR.parent.parent / "prodview" / "assets" / "nacional_gas_logo.png"

BLUE = colors.HexColor("#14487D")
BLUE_2 = colors.HexColor("#1D6FB8")
BLUE_SOFT = colors.HexColor("#E8F1FA")
RED = colors.HexColor("#D62839")
GREEN = colors.HexColor("#1E9E5A")
ORANGE = colors.HexColor("#F2782F")
LIGHT = colors.HexColor("#F0F4F9")
BORDER = colors.HexColor("#E3E7EF")
MUTED = colors.HexColor("#6B7280")
TEXT = colors.HexColor("#1C2430")

HEX_BLUE = "#14487D"
HEX_RED = "#D62839"
HEX_BORDER = "#E3E7EF"
CAT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#8456d8", "#2ab6c9"]
CONTENT_WIDTH = 178 * mm
LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Arial"],
    "axes.edgecolor": HEX_BORDER,
    "axes.linewidth": 0.8,
    "text.color": "#1C2430",
    "axes.labelcolor": "#6B7280",
    "xtick.color": "#6B7280",
    "ytick.color": "#1C2430",
    "font.size": 9,
})


def _fig_to_image(fig, width=CONTENT_WIDTH) -> Image:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=170, bbox_inches="tight", transparent=True)
    plt.close(fig)
    buf.seek(0)
    from PIL import Image as PILImage
    w, h = PILImage.open(buf).size
    buf.seek(0)
    return Image(buf, width=width, height=width * (h / w))


def _chart_availability_by_motor(agg: pd.DataFrame) -> Image:
    data = agg.sort_values("disponibilidade_pct", ascending=True)
    colors_bar = ["#1E9E5A" if v >= 95 else ("#F2A93E" if v >= 80 else "#D62839")
                  for v in data["disponibilidade_pct"]]
    fig, ax = plt.subplots(figsize=(7.0, 0.55 * len(data) + 0.6))
    bars = ax.barh(data["name"], data["disponibilidade_pct"], color=colors_bar, height=0.55)
    for b, v in zip(bars, data["disponibilidade_pct"]):
        ax.text(b.get_width() + 1.2, b.get_y() + b.get_height()/2, f"{v:.1f}%", va="center", fontsize=8.5)
    ax.set_xlim(0, 108)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(left=False, bottom=False, labelbottom=False)
    fig.tight_layout()
    return _fig_to_image(fig)


def _chart_current_by_motor(agg: pd.DataFrame) -> Image:
    data = agg.sort_values("corrente_media_A", ascending=True)
    fig, ax = plt.subplots(figsize=(7.0, 0.62 * len(data) + 0.7))
    y = range(len(data))
    ax.barh(y, data["corrente_media_A"], color=HEX_BLUE, height=0.42, label="Média")
    ax.scatter(data["corrente_max_A"], y, color="#F2782F", s=30, zorder=3, label="Pico")
    maxv = max(float(data["corrente_max_A"].max() or 0), 1)
    for pos, (_, r) in zip(y, data.iterrows()):
        ax.text(float(r["corrente_media_A"]) + maxv*0.015, pos, f"{r['corrente_media_A']:.1f} A",
                va="center", fontsize=8)
        ax.text(float(r["corrente_max_A"]) + maxv*0.015, pos+0.16, f"pico {r['corrente_max_A']:.1f} A",
                va="center", fontsize=7.2, color="#F2782F")
    ax.set_yticks(list(y), data["name"])
    ax.set_xlim(0, maxv * 1.22)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.grid(axis="x", color=HEX_BORDER, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower right", fontsize=8)
    fig.tight_layout()
    return _fig_to_image(fig)


def _chart_current_trend(df: pd.DataFrame) -> Image:
    data = df.copy()
    # db.py entrega UTC sem tz para manter compatibilidade com o dashboard.
    # No relatório convertemos explicitamente para o horário local de SUAPE.
    data["ts"] = (
        pd.to_datetime(data["ts"], utc=True)
        .dt.tz_convert(LOCAL_TZ)
    )
    fig, ax = plt.subplots(figsize=(7.0, 3.0))
    for idx, (name, sub) in enumerate(data.groupby("name")):
        sub = sub.sort_values("ts")
        color = CAT_COLORS[idx % len(CAT_COLORS)]
        ax.plot(
            sub["ts"], sub["current_avg_A"],
            color=color, linewidth=1.9, label=f"{name} - média",
        )
        ax.plot(
            sub["ts"], sub["current_max_A"],
            color="#F2782F", linewidth=1.15, alpha=0.85,
            linestyle="--", label=f"{name} - pico",
        )
    ax.set_ylim(bottom=0)
    ax.set_ylabel("Corrente (A)")
    ax.set_xlabel("Data / hora (Brasília)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m\n%H:%M", tz=LOCAL_TZ))
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color=HEX_BORDER, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=7.5, ncol=2, loc="upper left")
    ax.tick_params(axis="x", labelrotation=0)
    fig.tight_layout()
    return _fig_to_image(fig)


def _chart_current_area(df: pd.DataFrame, label: str | None = None) -> Image:
    """Tendência suavizada de um único motor.

    O dataframe deve estar filtrado para um motor. Paradas reais continuam
    em zero e lacunas de aquisição quebram visualmente a linha.
    """
    data = df.copy()
    data["ts"] = pd.to_datetime(data["ts"], utc=True).dt.tz_convert(LOCAL_TZ)
    data = data.sort_values("ts")
    series = pd.to_numeric(
        data.set_index("ts")["current_avg_A"], errors="coerce"
    ).astype(float)

    if label is None:
        label = data["name"].iloc[0] if "name" in data.columns and not data.empty else "Motor"

    if len(series) >= 5:
        smooth = series.rolling(window=5, center=True, min_periods=1).median()
        smooth = smooth.rolling(window=3, center=True, min_periods=1).mean()
    elif len(series) >= 3:
        smooth = series.rolling(window=3, center=True, min_periods=1).median()
    else:
        smooth = series.copy()

    if len(smooth) >= 2:
        diffs = smooth.index.to_series().diff().dropna().dt.total_seconds()
        typical = float(diffs.median()) if not diffs.empty else 0.0
        gap_limit = max(typical * 2.5, 90.0)
        smooth = smooth.copy()
        gap_mask = smooth.index.to_series().diff().dt.total_seconds().gt(gap_limit).to_numpy()
        smooth.iloc[gap_mask] = float("nan")

    fig, ax = plt.subplots(figsize=(7.15, 2.65))
    x = smooth.index.to_pydatetime()
    y = smooth.to_numpy(dtype=float)

    ax.plot(
        x, y, color=HEX_BLUE, linewidth=2.15,
        solid_capstyle="round", solid_joinstyle="round",
        antialiased=True, label=label,
    )
    ax.fill_between(x, y, 0, where=~pd.isna(y), color=HEX_BLUE, alpha=0.075)

    finite = smooth.dropna()
    ymax = float(finite.max()) if not finite.empty else 1.0
    ax.set_ylim(0, max(ymax * 1.14, 1.0))
    ax.set_ylabel("Corrente (A)", labelpad=8)
    ax.set_xlabel("")

    locator = mdates.AutoDateLocator(minticks=4, maxticks=7, tz=LOCAL_TZ)
    formatter = mdates.ConciseDateFormatter(locator, tz=LOCAL_TZ)
    formatter.formats = ["%Y", "%b", "%d/%m", "%H:%M", "%H:%M", "%S"]
    formatter.zero_formats = ["", "%Y", "%d/%m", "%d/%m", "%H:%M", "%H:%M"]
    formatter.offset_formats = ["", "%Y", "%Y", "%d/%m/%Y", "%d/%m/%Y", "%d/%m/%Y %H:%M"]
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(formatter)

    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(HEX_BORDER)
    ax.grid(axis="both", color=HEX_BORDER, linewidth=0.55, alpha=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", labelsize=8.2, length=0)
    ax.legend(
        frameon=False, fontsize=8, loc="lower left",
        bbox_to_anchor=(0, 1.01), borderaxespad=0, handlelength=2.2,
    )
    fig.tight_layout(pad=0.8)
    return _fig_to_image(fig)

def _chart_faults_by_motor(faults_df: pd.DataFrame) -> Image:
    agg = faults_df.groupby("name", as_index=False).size().rename(columns={"size": "eventos"})
    agg = agg.sort_values("eventos", ascending=True)
    fig, ax = plt.subplots(figsize=(7.0, 0.5 * len(agg) + 0.6))
    bars = ax.barh(agg["name"], agg["eventos"], color=HEX_RED, height=0.55)
    maxv = max(float(agg["eventos"].max() or 0), 1)
    for b, v in zip(bars, agg["eventos"]):
        ax.text(b.get_width() + maxv*0.02, b.get_y()+b.get_height()/2, f"{int(v)}", va="center", fontsize=8.5)
    ax.set_xlim(0, maxv * 1.2)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(left=False, bottom=False, labelbottom=False)
    fig.tight_layout()
    return _fig_to_image(fig)


def _kpi_card(label: str, value: str, accent, width=43.5*mm) -> Table:
    t = Table([[label], [value]], colWidths=[width], rowHeights=[7*mm, 14*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), colors.white),
        ("LINEABOVE", (0,0), (-1,0), 3, accent),
        ("BOX", (0,0), (-1,-1), 0.6, BORDER),
        ("TEXTCOLOR", (0,0), (-1,0), MUTED),
        ("FONTSIZE", (0,0), (-1,0), 7.6),
        ("TEXTCOLOR", (0,1), (-1,1), TEXT),
        ("FONTNAME", (0,1), (-1,1), "Helvetica-Bold"),
        ("FONTSIZE", (0,1), (-1,1), 14.5),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ]))
    return t


def _standard_table(data, widths, header_color=BLUE, font_size=8.2, repeat_rows=1):
    t = Table(data, colWidths=widths, repeatRows=repeat_rows)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), header_color),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE", (0,0), (-1,-1), font_size),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LIGHT]),
        ("GRID", (0,0), (-1,-1), 0.45, BORDER),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    return t


def _fmt(v, pattern="{:.1f}", suffix=""):
    try:
        if pd.isna(v):
            return "-"
        return pattern.format(float(v)) + suffix
    except Exception:
        return "-"


def build_pdf(
    agg_df: pd.DataFrame,
    kpis: dict,
    start_date,
    end_date,
    faults_df: pd.DataFrame | None = None,
    current_trend_df: pd.DataFrame | None = None,
    daily_df: pd.DataFrame | None = None,
    site_name: str = "SUAPE",
) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=14*mm, bottomMargin=16*mm, leftMargin=16*mm, rightMargin=16*mm,
        title="MotorView - Relatorio de Motores",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=BLUE, fontSize=20,
                        alignment=TA_RIGHT, spaceAfter=1, leading=22)
    tag = ParagraphStyle("tag", parent=styles["Normal"], textColor=MUTED, fontSize=10, alignment=TA_RIGHT)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=TEXT, fontSize=13, spaceBefore=14, spaceAfter=6)
    sub = ParagraphStyle("sub", parent=styles["Normal"], textColor=MUTED, fontSize=9.2)
    period_lbl = ParagraphStyle("period_lbl", parent=styles["Normal"], textColor=BLUE, fontSize=8.5,
                                fontName="Helvetica-Bold", leading=11)
    period_val = ParagraphStyle("period_val", parent=styles["Normal"], textColor=TEXT, fontSize=13,
                                fontName="Helvetica-Bold", leading=16)
    period_gen = ParagraphStyle("period_gen", parent=styles["Normal"], textColor=MUTED, fontSize=8.5,
                                alignment=TA_RIGHT, leading=11)
    small = ParagraphStyle("small", parent=styles["Normal"], textColor=MUTED, fontSize=8, alignment=TA_CENTER)

    story = []
    strip = Table([["",""]], colWidths=[CONTENT_WIDTH*0.8, CONTENT_WIDTH*0.2], rowHeights=[3*mm])
    strip.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(0,0),RED), ("BACKGROUND",(1,0),(1,0),BLUE),
        ("TOPPADDING",(0,0),(-1,-1),0), ("BOTTOMPADDING",(0,0),(-1,-1),0),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
    ]))
    story += [strip, Spacer(1,10)]

    logo = Image(str(LOGO_PATH), width=62*mm, height=62*mm*(76/413)) if LOGO_PATH.exists() else Paragraph("NACIONAL GÁS", h1)
    title_block = [
        Paragraph("MotorView", h1),
        Paragraph(f"Relatório de Motores e Inversores · {site_name}", tag),
    ]
    header = Table([[logo, title_block]], colWidths=[70*mm, CONTENT_WIDTH-70*mm])
    header.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),0),
        ("TOPPADDING",(0,0),(-1,-1),0), ("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]))
    story += [header, Spacer(1,12)]

    start_fmt = start_date.strftime("%d/%m/%Y %H:%M") if hasattr(start_date, "hour") else start_date.strftime("%d/%m/%Y")
    end_fmt = end_date.strftime("%d/%m/%Y %H:%M") if hasattr(end_date, "hour") else end_date.strftime("%d/%m/%Y")
    period_cell = [
        Paragraph("PERÍODO ANALISADO", period_lbl),
        Paragraph(f"{start_fmt} - {end_fmt}", period_val),
    ]
    gen_cell = Paragraph(f"Gerado em<br/><b>{datetime.now(LOCAL_TZ).strftime('%d/%m/%Y %H:%M')}</b>", period_gen)
    period_row = Table([[period_cell, gen_cell]], colWidths=[CONTENT_WIDTH-55*mm, 55*mm])
    period_row.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,-1),BLUE_SOFT), ("ROUNDEDCORNERS",[8,8,8,8]),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(0,0),14), ("RIGHTPADDING",(1,0),(1,0),14),
        ("TOPPADDING",(0,0),(-1,-1),10), ("BOTTOMPADDING",(0,0),(-1,-1),10),
    ]))
    story += [period_row, Spacer(1,14)]

    kpi_row = Table([[
        _kpi_card("MOTORES", str(int(kpis.get("motores",0))), BLUE),
        _kpi_card("DISPONIBILIDADE", f"{kpis.get('disponibilidade',0):.1f}%", GREEN),
        _kpi_card("MAIOR PICO", f"{kpis.get('corrente_max',0):.1f} A", ORANGE),
        _kpi_card("EVENTOS DE FALHA", str(int(kpis.get("falhas",0))), RED),
    ]], colWidths=[44.5*mm]*4)
    kpi_row.setStyle(TableStyle([
        ("LEFTPADDING",(0,0),(-1,-1),0), ("RIGHTPADDING",(0,0),(-1,-1),1.5),
        ("TOPPADDING",(0,0),(-1,-1),0), ("BOTTOMPADDING",(0,0),(-1,-1),0),
    ]))
    story.append(kpi_row)

    has_data = agg_df is not None and not agg_df.empty
    if has_data:
        story.append(KeepTogether([Paragraph("Corrente por motor", h2), _chart_current_by_motor(agg_df)]))
        story.append(Spacer(1,5))
        data = [["Motor","Média","Pico","Tensão","Frequência","Disponib."]]
        for _,r in agg_df.iterrows():
            data.append([
                r["name"], _fmt(r.get("corrente_media_A"), suffix=" A"),
                _fmt(r.get("corrente_max_A"), suffix=" A"),
                _fmt(r.get("tensao_media_V"), pattern="{:.0f}", suffix=" V"),
                _fmt(r.get("frequencia_media_Hz"), suffix=" Hz"),
                _fmt(r.get("disponibilidade_pct"), suffix="%"),
            ])
        story.append(_standard_table(data, [42*mm,25*mm,25*mm,25*mm,29*mm,32*mm]))
        story.append(KeepTogether([Paragraph("Disponibilidade por motor", h2), _chart_availability_by_motor(agg_df)]))

        story.append(PageBreak())
        story.append(Paragraph("Tendência de corrente por motor", h2))
        story.append(Paragraph(
            "Lacunas representam intervalos sem dados de monitoramento.",
            sub,
        ))
        if current_trend_df is not None and not current_trend_df.empty:
            motors = (
                current_trend_df[["inverter_id", "name"]]
                .drop_duplicates()
                .sort_values("name")
            )
            for pos, (_, motor) in enumerate(motors.iterrows()):
                motor_df = current_trend_df[
                    current_trend_df["inverter_id"] == motor["inverter_id"]
                ].copy()
                story.append(KeepTogether([
                    Paragraph(str(motor["name"]), h2),
                    _chart_current_area(motor_df, str(motor["name"])),
                ]))

                summary_row = agg_df[
                    agg_df["inverter_id"] == motor["inverter_id"]
                ]
                if not summary_row.empty:
                    r = summary_row.iloc[0]
                    motor_data = [[
                        "Corrente média", "Maior pico", "Tensão média",
                        "Frequência média", "Disponibilidade",
                    ], [
                        _fmt(r.get("corrente_media_A"), suffix=" A"),
                        _fmt(r.get("corrente_max_A"), suffix=" A"),
                        _fmt(r.get("tensao_media_V"), pattern="{:.0f}", suffix=" V"),
                        _fmt(r.get("frequencia_media_Hz"), suffix=" Hz"),
                        _fmt(r.get("disponibilidade_pct"), suffix="%"),
                    ]]
                    story.append(_standard_table(
                        motor_data,
                        [35.6*mm, 35.6*mm, 35.6*mm, 35.6*mm, 35.6*mm],
                        font_size=7.8,
                    ))

                if pos < len(motors) - 1:
                    story.append(Spacer(1, 10))
        else:
            story.append(Paragraph("Sem série de corrente disponível para o período.", sub))

        story.append(PageBreak())
        story.append(Paragraph("Corrente média e picos por intervalo", h2))
        story.append(Paragraph(
            "Linha contínua: corrente média por intervalo. Linha tracejada: maior pico capturado no mesmo intervalo.",
            sub,
        ))
        if current_trend_df is not None and not current_trend_df.empty:
            motors_peak = (
                current_trend_df[["inverter_id", "name"]]
                .drop_duplicates()
                .sort_values("name")
            )
            for pos, (_, motor) in enumerate(motors_peak.iterrows()):
                motor_df = current_trend_df[
                    current_trend_df["inverter_id"] == motor["inverter_id"]
                ].copy()
                story.append(KeepTogether([
                    Paragraph(str(motor["name"]), h2),
                    _chart_current_trend(motor_df),
                ]))
                if pos < len(motors_peak) - 1:
                    story.append(Spacer(1, 10))
        else:
            story.append(Paragraph("Sem série de corrente disponível para o período.", sub))

        story.append(Paragraph("Parâmetros elétricos médios", h2))
        data = [["Motor","Tensão","Freq.","Velocidade","Torque","Link CC"]]
        for _,r in agg_df.iterrows():
            data.append([
                r["name"],
                _fmt(r.get("tensao_media_V"), pattern="{:.0f}", suffix=" V"),
                _fmt(r.get("frequencia_media_Hz"), suffix=" Hz"),
                _fmt(r.get("velocidade_media_rpm"), pattern="{:.0f}", suffix=" rpm"),
                _fmt(r.get("torque_medio_pct"), suffix="%"),
                _fmt(r.get("link_cc_medio_V"), pattern="{:.0f}", suffix=" V"),
            ])
        story.append(_standard_table(data, [42*mm,27*mm,27*mm,31*mm,24*mm,27*mm]))

        if daily_df is not None and not daily_df.empty:
            story.append(Paragraph("Resumo diário por motor", h2))
            detail = daily_df.sort_values(["data","name"], ascending=[False,True]).head(40)
            data = [["Data","Motor","I média","I máx.","Tensão","Freq.","Disponib."]]
            for _,r in detail.iterrows():
                availability = 100*(1-float(r.get("erros_comunicacao",0) or 0)/max(float(r.get("leituras",1) or 1),1))
                date_val = r["data"].strftime("%d/%m/%Y") if hasattr(r["data"],"strftime") else str(r["data"])
                data.append([
                    date_val, r["name"],
                    _fmt(r.get("corrente_media_A"), suffix=" A"),
                    _fmt(r.get("corrente_max_A"), suffix=" A"),
                    _fmt(r.get("tensao_media_V"), pattern="{:.0f}", suffix=" V"),
                    _fmt(r.get("frequencia_media_Hz"), suffix=" Hz"),
                    f"{availability:.1f}%",
                ])
            story.append(_standard_table(data, [23*mm,35*mm,24*mm,24*mm,23*mm,24*mm,25*mm], font_size=7.3))

    if faults_df is not None and not faults_df.empty:
        story.append(PageBreak())
        story.append(KeepTogether([Paragraph("Eventos de falha por motor", h2), _chart_faults_by_motor(faults_df)]))
        story.append(Paragraph("Últimos eventos de falha (máx. 40)", h2))
        detail = faults_df.sort_values("ts", ascending=False).head(40)
        data = [["Data/hora","Motor","Código","Descrição"]]
        for _,r in detail.iterrows():
            ts_val = r["ts"]
            if ts_val is not None and not pd.isna(ts_val):
                ts_local = pd.Timestamp(ts_val)
                if ts_local.tzinfo is None:
                    ts_local = ts_local.tz_localize("UTC")
                ts_local = ts_local.tz_convert(LOCAL_TZ)
                ts_fmt = ts_local.strftime("%d/%m/%Y %H:%M")
            else:
                ts_fmt = "-"
            code = f"F{int(r['fault_code']):04d}" if pd.notna(r.get("fault_code")) else "-"
            data.append([ts_fmt,r["name"],code,(r.get("fault_description") or "")[:70]])
        story.append(_standard_table(data,[33*mm,35*mm,20*mm,90*mm],header_color=RED,font_size=7.6))
    else:
        story.append(Paragraph("Eventos de falha", h2))
        story.append(Paragraph("Nenhuma falha registrada no período selecionado.", sub))

    story += [Spacer(1,16), HRFlowable(width="100%",color=BORDER,thickness=0.8), Spacer(1,4)]
    story.append(Paragraph(f"ENDTECH · Soluções em Engenharia - Sistema MotorView · Nacional Gás · Unidade {site_name}", small))

    doc.build(story)
    return buf.getvalue()
