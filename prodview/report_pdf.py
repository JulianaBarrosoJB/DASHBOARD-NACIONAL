"""
ProdView — geração de relatório em PDF.

Isolado num módulo próprio para não pesar o app.py. Usa reportlab (puro
Python, sem dependências binárias pesadas tipo wkhtmltopdf/kaleido).
"""

from io import BytesIO
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT

BLUE = colors.HexColor("#14487D")
RED = colors.HexColor("#D62839")
LIGHT = colors.HexColor("#F0F4F9")
MUTED = colors.HexColor("#6B7280")
TEXT = colors.HexColor("#1C2430")


def build_pdf(report_df, kpis: dict, start_date, end_date, downtime_df=None) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=18 * mm, bottomMargin=16 * mm, leftMargin=16 * mm, rightMargin=16 * mm,
        title="ProdView - Relatorio de Producao",
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=BLUE, fontSize=20, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=TEXT, fontSize=13, spaceBefore=14, spaceAfter=6)
    sub = ParagraphStyle("sub", parent=styles["Normal"], textColor=MUTED, fontSize=10)
    small = ParagraphStyle("small", parent=styles["Normal"], textColor=MUTED, fontSize=8, alignment=TA_RIGHT)

    story = []
    story.append(Paragraph("ENDTECH · ProdView", h1))
    story.append(Paragraph("Relatório de Produção — Nacional Gás", sub))
    story.append(Paragraph(
        f"Período: {start_date.strftime('%d/%m/%Y')} a {end_date.strftime('%d/%m/%Y')} · "
        f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        sub,
    ))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", color=BLUE, thickness=1.4))
    story.append(Spacer(1, 10))

    # --- KPIs -----------------------------------------------------------
    total_fmt = f"{int(kpis.get('total', 0)):,}".replace(",", ".")
    kpi_data = [
        ["Total de botijões", "OEE médio", "Minutos parados"],
        [total_fmt, f"{kpis.get('oee', 0):.1f}%", f"{kpis.get('downtime', 0):.0f} min"],
    ]
    t = Table(kpi_data, colWidths=[57 * mm] * 3)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, 1), 16),
        ("TEXTCOLOR", (0, 1), (-1, 1), BLUE),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 12),
        ("TOPPADDING", (0, 1), (-1, 1), 4),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#E3E7EF")),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#E3E7EF")),
    ]))
    story.append(t)

    # --- Produção por linha ----------------------------------------------
    story.append(Paragraph("Produção por linha", h2))
    if report_df is not None and not report_df.empty:
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
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E3E7EF")),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(tt)
    else:
        story.append(Paragraph("Sem dados para o período selecionado.", sub))

    # --- Detalhe diário (limitado) ---------------------------------------
    story.append(Paragraph("Detalhe diário (máx. 40 registros)", h2))
    if report_df is not None and not report_df.empty:
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
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1C2430")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E3E7EF")),
            ("ALIGN", (2, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(tt)

    # --- Paradas -----------------------------------------------------------
    if downtime_df is not None and not downtime_df.empty:
        story.append(Paragraph("Principais causas de parada no período", h2))
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
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E3E7EF")),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(tt)

    story.append(Spacer(1, 16))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#E3E7EF"), thickness=0.8))
    story.append(Spacer(1, 4))
    story.append(Paragraph("ENDTECH · Soluções em Engenharia — Sistema ProdView (dados de demonstração)", small))

    doc.build(story)
    return buf.getvalue()


def pd_fmt_date(v) -> str:
    try:
        return v.strftime("%d/%m/%Y")
    except Exception:
        return str(v)
