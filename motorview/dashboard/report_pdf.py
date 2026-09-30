"""
MotorView - geração de relatório em PDF.

Mesmo layout/identidade do report_pdf.py do ProdView (reportlab + matplotlib,
nenhum binário externo necessário) - só o conteúdo muda (motores/corrente/
falhas em vez de linhas/produção/paradas).
"""

from io import BytesIO
from datetime import datetime
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable, Image, KeepTogether,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER

BASE_DIR = Path(__file__).resolve().parent
# Reaproveita o mesmo logo oficial do ProdView (mesma suíte ENDTECH/Nacional Gás).
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
    height = width * (h / w)
    return Image(buf, width=width, height=height)


def _chart_availability_by_motor(agg: pd.DataFrame) -> Image:
    data = agg.sort_values("disponibilidade_pct", ascending=True)
    colors_bar = ["#1E9E5A" if v >= 95 else ("#F2A93E" if v >= 80 else "#D62839")
                  for v in data["disponibilidade_pct"]]
    fig, ax = plt.subplots(figsize=(7.0, 0.55 * len(data) + 0.6))
    bars = ax.barh(data["name"], data["disponibilidade_pct"], color=colors_bar, height=0.55)
    for b, v in zip(bars, data["disponibilidade_pct"]):
        ax.text(b.get_width() + 1.5, b.get_y() + b.get_height() / 2, f"{v:.0f}%", va="center", fontsize=8.5)
    ax.set_xlim(0, 108)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(left=False, bottom=False, labelbottom=False)
    fig.tight_layout()
    return _fig_to_image(fig)


def _chart_current_by_motor(agg: pd.DataFrame) -> Image:
    data = agg.sort_values("corrente_media_A", ascending=True)
    fig, ax = plt.subplots(figsize=(7.0, 0.55 * len(data) + 0.6))
    bars = ax.barh(data["name"], data["corrente_media_A"], color=HEX_BLUE, height=0.55)
    maxv = data["corrente_media_A"].max() or 1
    for b, v in zip(bars, data["corrente_media_A"]):
        ax.text(b.get_width() + maxv * 0.02, b.get_y() + b.get_height() / 2, f"{v:.1f} A", va="center", fontsize=8.5)
    ax.set_xlim(0, maxv * 1.2)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(left=False, bottom=False, labelbottom=False)
    fig.tight_layout()
    return _fig_to_image(fig)


def _chart_faults_by_motor(faults_df: pd.DataFrame) -> Image:
    agg = faults_df.groupby("name", as_index=False).size().rename(columns={"size": "eventos"})
    agg = agg.sort_values("eventos", ascending=True)
    fig, ax = plt.subplots(figsize=(7.0, 0.5 * len(agg) + 0.6))
    bars = ax.barh(agg["name"], agg["eventos"], color=HEX_RED, height=0.55)
    for b, v in zip(bars, agg["eventos"]):
        ax.text(b.get_width() + agg["eventos"].max() * 0.02, b.get_y() + b.get_height() / 2,
                 f"{int(v)}", va="center", fontsize=8.5)
    ax.set_xlim(0, agg["eventos"].max() * 1.2)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(left=False, bottom=False, labelbottom=False)
    fig.tight_layout()
    return _fig_to_image(fig)


def _kpi_card(label: str, value: str, accent) -> Table:
    t = Table([[label], [value]], colWidths=[56 * mm], rowHeights=[7 * mm, 15 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("LINEABOVE", (0, 0), (-1, 0), 3, accent),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5),
        ("TEXTCOLOR", (0, 1), (-1, 1), TEXT),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, 1), 17),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, 0), "BOTTOM"),
        ("VALIGN", (0, 1), (-1, 1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
    ]))
    return t


def build_pdf(agg_df: pd.DataFrame, kpis: dict, start_date, end_date, faults_df: pd.DataFrame | None = None) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=14 * mm, bottomMargin=16 * mm, leftMargin=16 * mm, rightMargin=16 * mm,
        title="MotorView - Relatorio de Motores",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=BLUE, fontSize=19, alignment=TA_RIGHT, spaceAfter=1, leading=22)
    tag = ParagraphStyle("tag", parent=styles["Normal"], textColor=MUTED, fontSize=10, alignment=TA_RIGHT)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=TEXT, fontSize=13, spaceBefore=16, spaceAfter=6)
    sub = ParagraphStyle("sub", parent=styles["Normal"], textColor=MUTED, fontSize=9.5)
    period_lbl = ParagraphStyle("period_lbl", parent=styles["Normal"], textColor=BLUE, fontSize=8.5,
                                 fontName="Helvetica-Bold", leading=11)
    period_val = ParagraphStyle("period_val", parent=styles["Normal"], textColor=TEXT, fontSize=13,
                                 fontName="Helvetica-Bold", leading=16)
    period_gen = ParagraphStyle("period_gen", parent=styles["Normal"], textColor=MUTED, fontSize=8.5,
                                 alignment=TA_RIGHT, leading=11)
    small = ParagraphStyle("small", parent=styles["Normal"], textColor=MUTED, fontSize=8, alignment=TA_CENTER)

    story = []

    strip = Table([["", ""]], colWidths=[CONTENT_WIDTH * 0.8, CONTENT_WIDTH * 0.2], rowHeights=[3 * mm])
    strip.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), RED),
        ("BACKGROUND", (1, 0), (1, 0), BLUE),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(strip)
    story.append(Spacer(1, 10))

    if LOGO_PATH.exists():
        logo = Image(str(LOGO_PATH), width=62 * mm, height=62 * mm * (76 / 413))
    else:
        logo = Paragraph("NACIONAL GÁS", h1)
    title_block = [
        Paragraph("ENDTECH &middot; MotorView", h1),
        Paragraph("Relatório de Motores e Inversores", tag),
    ]
    header = Table([[logo, title_block]], colWidths=[70 * mm, CONTENT_WIDTH - 70 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 12))

    period_cell = [
        Paragraph("PERÍODO ANALISADO", period_lbl),
        Paragraph(f"{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}", period_val),
    ]
    gen_cell = Paragraph(f"Gerado em<br/><b>{datetime.now().strftime('%d/%m/%Y %H:%M')}</b>", period_gen)
    period_row = Table([[period_cell, gen_cell]], colWidths=[CONTENT_WIDTH - 55 * mm, 55 * mm])
    period_row.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLUE_SOFT),
        ("ROUNDEDCORNERS", [8, 8, 8, 8]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 14), ("RIGHTPADDING", (0, 0), (0, 0), 8),
        ("LEFTPADDING", (1, 0), (1, 0), 8), ("RIGHTPADDING", (1, 0), (1, 0), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.append(period_row)
    story.append(Spacer(1, 14))

    kpi_row = Table([[
        _kpi_card("MOTORES NO RELATÓRIO", str(int(kpis.get("motores", 0))), BLUE),
        _kpi_card("DISPONIBILIDADE MÉDIA", f"{kpis.get('disponibilidade', 0):.1f}%", ORANGE),
        _kpi_card("EVENTOS DE FALHA", str(int(kpis.get("falhas", 0))), RED),
    ]], colWidths=[59.3 * mm] * 3)
    kpi_row.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(kpi_row)

    has_data = agg_df is not None and not agg_df.empty

    if has_data:
        story.append(KeepTogether([Paragraph("Disponibilidade por motor", h2), _chart_availability_by_motor(agg_df)]))
        story.append(Spacer(1, 10))
        story.append(KeepTogether([Paragraph("Corrente média por motor", h2), _chart_current_by_motor(agg_df)]))
        story.append(Spacer(1, 6))

        data = [["Motor", "Corrente média", "Corrente máx.", "Leituras", "Disponibilidade"]]
        for _, r in agg_df.iterrows():
            data.append([
                r["name"], f"{r['corrente_media_A']:.1f} A", f"{r['corrente_max_A']:.1f} A",
                f"{int(r['leituras'])}", f"{r['disponibilidade_pct']:.1f}%",
            ])
        tt = Table(data, colWidths=[50 * mm, 32 * mm, 32 * mm, 28 * mm, 36 * mm])
        tt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(tt)
    else:
        story.append(Paragraph("Disponibilidade por motor", h2))
        story.append(Paragraph("Sem dados para o período selecionado.", sub))

    if faults_df is not None and not faults_df.empty:
        story.append(KeepTogether([
            Paragraph("Eventos de falha por motor", h2),
            _chart_faults_by_motor(faults_df),
        ]))
        story.append(Spacer(1, 6))

        story.append(Paragraph("Últimos eventos de falha (máx. 40)", h2))
        detail = faults_df.sort_values("ts", ascending=False).head(40)
        data = [["Data/hora", "Motor", "Código", "Descrição"]]
        for _, r in detail.iterrows():
            ts_val = r["ts"]
            ts_fmt = ts_val.strftime("%d/%m/%Y %H:%M") if hasattr(ts_val, "strftime") else str(ts_val)
            data.append([ts_fmt, r["name"], f"F{int(r['fault_code']):04d}", (r.get("fault_description") or "")[:60]])
        tt = Table(data, colWidths=[32 * mm, 40 * mm, 20 * mm, 86 * mm], repeatRows=1)
        tt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), TEXT),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("ALIGN", (2, 0), (2, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(tt)
    else:
        story.append(Paragraph("Eventos de falha", h2))
        story.append(Paragraph("Nenhuma falha registrada no período selecionado.", sub))

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", color=BORDER, thickness=0.8))
    story.append(Spacer(1, 4))
    story.append(Paragraph("ENDTECH &middot; Soluções em Engenharia - Sistema MotorView", small))

    doc.build(story)
    return buf.getvalue()
