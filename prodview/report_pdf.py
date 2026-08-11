"""
ProdView - geração de relatório em PDF.

Isolado num módulo próprio para não pesar o app.py. Usa reportlab (layout,
tabelas, tipografia) + matplotlib só para renderizar os gráficos como imagem
(nenhum dos dois precisa de binário externo tipo wkhtmltopdf/kaleido/chrome).
"""

from io import BytesIO
from datetime import datetime
from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable, Image,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER

BASE_DIR = Path(__file__).resolve().parent
LOGO_PATH = BASE_DIR / "assets" / "nacional_gas_logo.png"

# paleta - mesma identidade do app (ENDTECH / Nacional Gás)
BLUE = colors.HexColor("#14487D")
BLUE_2 = colors.HexColor("#1D6FB8")
BLUE_SOFT = colors.HexColor("#E8F1FA")
RED = colors.HexColor("#D62839")
RED_SOFT = colors.HexColor("#FBEAEC")
GREEN = colors.HexColor("#1E9E5A")
ORANGE = colors.HexColor("#F2782F")
LIGHT = colors.HexColor("#F0F4F9")
BORDER = colors.HexColor("#E3E7EF")
MUTED = colors.HexColor("#6B7280")
TEXT = colors.HexColor("#1C2430")

# mesmas cores hexadecimais (para os gráficos matplotlib, que não usam reportlab.colors)
HEX_BLUE = "#14487D"
HEX_RED = "#D62839"
HEX_MUTED = "#8A93A3"
HEX_BORDER = "#E3E7EF"
CAT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]

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


def _chart_units_by_line(report_df) -> Image:
    agg = (report_df.groupby("Linha", as_index=False)["Botijões"].sum()
           .sort_values("Botijões", ascending=True))
    color_map = {name: CAT_COLORS[i % len(CAT_COLORS)] for i, name in
                 enumerate(sorted(report_df["Linha"].unique()))}
    fig, ax = plt.subplots(figsize=(7.0, 0.55 * len(agg) + 0.6))
    bars = ax.barh(agg["Linha"], agg["Botijões"], color=[color_map[n] for n in agg["Linha"]], height=0.55)
    for b, v in zip(bars, agg["Botijões"]):
        ax.text(b.get_width() + agg["Botijões"].max() * 0.015, b.get_y() + b.get_height() / 2,
                 f"{int(v):,}".replace(",", "."), va="center", fontsize=8.5, color="#1C2430")
    ax.set_xlim(0, agg["Botijões"].max() * 1.18)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(left=False, bottom=False, labelbottom=False)
    ax.set_xlabel("")
    fig.tight_layout()
    return _fig_to_image(fig)


def _chart_daily_trend(report_df) -> Image:
    agg = report_df.groupby("Data", as_index=False)["Botijões"].sum().sort_values("Data")
    fig, ax = plt.subplots(figsize=(7.0, 2.6))
    ax.plot(agg["Data"], agg["Botijões"], color=HEX_BLUE, linewidth=2.0, marker="o", markersize=3.5)
    ax.fill_between(agg["Data"], agg["Botijões"], color=HEX_BLUE, alpha=0.10)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color=HEX_BORDER, linewidth=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=8)
    fig.autofmt_xdate(rotation=30, ha="right")
    fig.tight_layout()
    return _fig_to_image(fig)


def _chart_downtime_causes(downtime_df) -> Image:
    agg = (downtime_df.groupby("category", as_index=False)["duration_min"].sum()
           .sort_values("duration_min", ascending=True))
    fig, ax = plt.subplots(figsize=(7.0, 0.5 * len(agg) + 0.6))
    bars = ax.barh(agg["category"], agg["duration_min"], color=HEX_RED, height=0.55)
    for b, v in zip(bars, agg["duration_min"]):
        ax.text(b.get_width() + agg["duration_min"].max() * 0.015, b.get_y() + b.get_height() / 2,
                 f"{v:.0f} min", va="center", fontsize=8.5, color="#1C2430")
    ax.set_xlim(0, agg["duration_min"].max() * 1.2)
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


def build_pdf(report_df, kpis: dict, start_date, end_date, downtime_df=None) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=14 * mm, bottomMargin=16 * mm, leftMargin=16 * mm, rightMargin=16 * mm,
        title="ProdView - Relatorio de Producao",
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

    # --- faixa decorativa (ecoa as proporções da logo: barra vermelha + bloco azul) ---
    strip = Table([["", ""]], colWidths=[CONTENT_WIDTH * 0.8, CONTENT_WIDTH * 0.2], rowHeights=[3 * mm])
    strip.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), RED),
        ("BACKGROUND", (1, 0), (1, 0), BLUE),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(strip)
    story.append(Spacer(1, 10))

    # --- cabeçalho: logo Nacional Gás + título ENDTECH/ProdView ---
    if LOGO_PATH.exists():
        logo = Image(str(LOGO_PATH), width=62 * mm, height=62 * mm * (76 / 413))
    else:
        logo = Paragraph("NACIONAL GÁS", h1)
    title_block = [
        Paragraph("ENDTECH &middot; ProdView", h1),
        Paragraph("Relatório de Produção", tag),
    ]
    header = Table([[logo, title_block]], colWidths=[70 * mm, CONTENT_WIDTH - 70 * mm])
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header)
    story.append(Spacer(1, 12))

    # --- faixa "período analisado" com fundo colorido ---
    period_cell = [
        Paragraph("PERÍODO ANALISADO", period_lbl),
        Paragraph(f"{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}", period_val),
    ]
    gen_cell = Paragraph(
        f"Gerado em<br/><b>{datetime.now().strftime('%d/%m/%Y %H:%M')}</b>", period_gen,
    )
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

    # --- KPIs (cards) -----------------------------------------------------
    total_fmt = f"{int(kpis.get('total', 0)):,}".replace(",", ".")
    kpi_row = Table([[
        _kpi_card("TOTAL DE BOTIJÕES", total_fmt, BLUE),
        _kpi_card("OEE MÉDIO", f"{kpis.get('oee', 0):.1f}%", ORANGE),
        _kpi_card("MINUTOS PARADOS", f"{kpis.get('downtime', 0):.0f}", RED),
    ]], colWidths=[59.3 * mm] * 3)
    kpi_row.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(kpi_row)

    has_data = report_df is not None and not report_df.empty

    # --- gráfico + tabela: produção por linha -----------------------------
    story.append(Paragraph("Produção por linha", h2))
    if has_data:
        story.append(_chart_units_by_line(report_df))
        story.append(Spacer(1, 6))
        by_line = (
            report_df.groupby("Linha", as_index=False)
            .agg(Botijoes=("Botijões", "sum"), OEE=("OEE (%)", "mean"), Parada=("Parada (min)", "sum"))
        )
        data = [["Linha", "Botijões", "OEE médio", "Parada (min)"]]
        for _, r in by_line.iterrows():
            data.append([
                r["Linha"], f"{int(r['Botijoes']):,}".replace(",", "."),
                f"{r['OEE']:.1f}%", f"{r['Parada']:.0f}",
            ])
        tt = Table(data, colWidths=[55 * mm, 40 * mm, 35 * mm, 41 * mm])
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
        story.append(Paragraph("Sem dados para o período selecionado.", sub))

    # --- gráfico: tendência diária -----------------------------------------
    if has_data and report_df["Data"].nunique() > 1:
        story.append(Paragraph("Tendência diária de produção", h2))
        story.append(_chart_daily_trend(report_df))

    # --- paradas: gráfico + tabela ------------------------------------------
    if downtime_df is not None and not downtime_df.empty:
        story.append(Paragraph("Principais causas de parada no período", h2))
        story.append(_chart_downtime_causes(downtime_df))
        story.append(Spacer(1, 6))
        agg = downtime_df.groupby("category", as_index=False)["duration_min"].sum()
        agg = agg.sort_values("duration_min", ascending=False)
        data = [["Categoria", "Minutos parados"]]
        for _, r in agg.iterrows():
            data.append([r["category"], f"{r['duration_min']:.0f}"])
        tt = Table(data, colWidths=[100 * mm, 60 * mm])
        tt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), RED),
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

    # --- detalhe diário (limitado) -------------------------------------------
    story.append(Paragraph("Detalhe diário (máx. 40 registros)", h2))
    if has_data:
        detail = report_df.sort_values("Data", ascending=False).head(40)
        data = [["Data", "Linha", "Turno", "Botijões", "OEE (%)", "Parada (min)"]]
        for _, r in detail.iterrows():
            data.append([
                pd_fmt_date(r["Data"]), r["Linha"], str(r["Turno"]),
                f"{int(r['Botijões']):,}".replace(",", "."), f"{r['OEE (%)']:.1f}",
                f"{r['Parada (min)']:.0f}",
            ])
        tt = Table(data, colWidths=[24 * mm, 48 * mm, 16 * mm, 26 * mm, 22 * mm, 26 * mm], repeatRows=1)
        tt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), TEXT),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("ALIGN", (2, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(tt)

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", color=BORDER, thickness=0.8))
    story.append(Spacer(1, 4))
    story.append(Paragraph("ENDTECH &middot; Soluções em Engenharia - Sistema ProdView (dados de demonstração)", small))

    doc.build(story)
    return buf.getvalue()


def pd_fmt_date(v) -> str:
    try:
        return v.strftime("%d/%m/%Y")
    except Exception:
        return str(v)
