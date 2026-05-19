"""
pdf_generator.py — Generazione PDF rendiconto con ReportLab.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from database import Client, FeeReport, get_all_settings
from utils import fmt_currency

COLOR_PRIMARY   = colors.HexColor("#1a3a5c")
COLOR_SECONDARY = colors.HexColor("#2e6da4")
COLOR_ACCENT    = colors.HexColor("#e8f0f7")
COLOR_LIGHT     = colors.HexColor("#f5f7fa")
COLOR_BORDER    = colors.HexColor("#c5d3e0")
COLOR_TEXT      = colors.HexColor("#1a1a2e")
COLOR_MUTED     = colors.HexColor("#6b7a8d")


def _build_styles():
    styles = {}
    styles["studio_name"] = ParagraphStyle(
        "studio_name", fontName="Helvetica-Bold", fontSize=15,
        textColor=COLOR_PRIMARY, spaceAfter=2)
    styles["studio_info"] = ParagraphStyle(
        "studio_info", fontName="Helvetica", fontSize=8,
        textColor=COLOR_MUTED, spaceAfter=1, leading=11)
    styles["doc_title"] = ParagraphStyle(
        "doc_title", fontName="Helvetica-Bold", fontSize=13,
        textColor=COLOR_PRIMARY, alignment=TA_RIGHT, spaceAfter=2)
    styles["doc_subtitle"] = ParagraphStyle(
        "doc_subtitle", fontName="Helvetica", fontSize=9,
        textColor=COLOR_MUTED, alignment=TA_RIGHT)
    styles["section_label"] = ParagraphStyle(
        "section_label", fontName="Helvetica-Bold", fontSize=8,
        textColor=COLOR_MUTED, spaceAfter=1)
    styles["client_name"] = ParagraphStyle(
        "client_name", fontName="Helvetica-Bold", fontSize=11,
        textColor=COLOR_TEXT, spaceAfter=2)
    styles["client_detail"] = ParagraphStyle(
        "client_detail", fontName="Helvetica", fontSize=8.5,
        textColor=COLOR_TEXT, leading=13)
    styles["footer"] = ParagraphStyle(
        "footer", fontName="Helvetica", fontSize=7,
        textColor=COLOR_MUTED, alignment=TA_CENTER)
    styles["notes_text"] = ParagraphStyle(
        "notes_text", fontName="Helvetica-Oblique", fontSize=8,
        textColor=COLOR_MUTED, spaceAfter=4)
    return styles


def generate_fee_report_pdf(report: FeeReport, client: Client,
                             quarter: Optional[int] = None) -> bytes:
    settings = get_all_settings()
    styles = _build_styles()
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2.5*cm,
        title=f"Rendiconto {report.year} - {client.name}",
        author=settings.get("studio_name", ""),
    )

    story = []
    story.extend(_build_header(settings, report, client, quarter, styles))
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=COLOR_SECONDARY))
    story.append(Spacer(1, 0.4*cm))
    story.extend(_build_client_section(client, styles))
    story.append(Spacer(1, 0.5*cm))
    story.extend(_build_services_table(report, quarter, styles))
    story.append(Spacer(1, 0.6*cm))

    if report.notes:
        story.append(Paragraph("Note:", styles["section_label"]))
        story.append(Paragraph(report.notes, styles["notes_text"]))
        story.append(Spacer(1, 0.3*cm))

    story.extend(_build_footer(settings, styles))
    doc.build(story)
    return buf.getvalue()


def _build_header(settings, report, client, quarter, styles) -> list:
    studio_name = settings.get("studio_name", "Studio")
    info_lines = []
    for key in ("studio_address", "studio_city", "studio_phone", "studio_email"):
        val = settings.get(key, "")
        if val:
            info_lines.append(val)
    if settings.get("studio_piva"):
        info_lines.append(f"P.IVA: {settings['studio_piva']}")

    left = [Paragraph(studio_name, styles["studio_name"]),
            *[Paragraph(l, styles["studio_info"]) for l in info_lines]]

    if quarter:
        title = f"RENDICONTO {_quarter_label(quarter)} {report.year}"
        sub   = f"Periodo: {_quarter_period(quarter, report.year)}"
    else:
        title = f"RENDICONTO ANNUALE {report.year}"
        sub   = f"Anno {report.year}"

    right = [Paragraph(title, styles["doc_title"]),
             Paragraph(sub, styles["doc_subtitle"])]

    t = Table([[left, right]], colWidths=["60%", "40%"])
    t.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
    ]))
    return [t]


def _build_client_section(client: Client, styles) -> list:
    label = styles["section_label"]
    val   = styles["client_detail"]
    rows = [
        [Paragraph("CLIENTE", label), Paragraph("CODICE", label), Paragraph("TIPOLOGIA", label)],
        [Paragraph(client.name, val), Paragraph(client.client_code, val),
         Paragraph(client.client_type.title(), val)],
    ]
    if client.vat_number or client.tax_code:
        rows.append([
            Paragraph("P.IVA", label) if client.vat_number else Paragraph("", label),
            Paragraph("COD. FISCALE", label) if client.tax_code else Paragraph("", label),
            Paragraph("", label),
        ])
        rows.append([
            Paragraph(client.vat_number or "", val),
            Paragraph(client.tax_code or "", val),
            Paragraph("", val),
        ])

    t = Table(rows, colWidths=["45%", "20%", "35%"])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), COLOR_ACCENT),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
        ("BOX", (0,0), (-1,-1), 0.5, COLOR_BORDER),
        ("INNERGRID", (0,0), (-1,-1), 0.3, COLOR_BORDER),
    ]))
    return [t]


def _build_services_table(report, quarter, styles) -> list:
    lines = [l for l in report.lines if l.total > 0]

    num_style  = ParagraphStyle("num", fontName="Helvetica", fontSize=8.5,
                                textColor=COLOR_TEXT, alignment=TA_RIGHT)
    zero_style = ParagraphStyle("zero", fontName="Helvetica", fontSize=8.5,
                                textColor=COLOR_MUTED, alignment=TA_RIGHT)
    desc_style = ParagraphStyle("desc", fontName="Helvetica", fontSize=8.5,
                                textColor=COLOR_TEXT)
    code_style = ParagraphStyle("code", fontName="Helvetica", fontSize=7.5,
                                textColor=COLOR_MUTED, alignment=TA_CENTER)
    hdr_style  = ParagraphStyle("hdr", fontName="Helvetica-Bold", fontSize=8,
                                textColor=colors.white, alignment=TA_CENTER)
    tot_style  = ParagraphStyle("tot", fontName="Helvetica-Bold", fontSize=9,
                                textColor=COLOR_PRIMARY, alignment=TA_RIGHT)

    def money(val):
        if not val or val == 0:
            return Paragraph("—", zero_style)
        return Paragraph(fmt_currency(val).replace("€ ", ""), num_style)

    if quarter:
        headers    = ["Cod.", "Prestazione", "Categoria", _quarter_label(quarter), "Importo"]
        col_widths = [1.5*cm, 7.5*cm, 3*cm, 2.5*cm, 2.5*cm]
    else:
        headers    = ["Cod.", "Prestazione", "T1", "T2", "T3", "T4", "Totale"]
        col_widths = [1.5*cm, 6.5*cm, 2*cm, 2*cm, 2*cm, 2*cm, 2.5*cm]

    data = [[Paragraph(h, hdr_style) for h in headers]]

    for line in lines:
        if quarter:
            fee = getattr(line, f"effective_q{quarter}")
            row = [
                Paragraph(line.service_code_snap, code_style),
                Paragraph(line.description_snap, desc_style),
                Paragraph(line.category_snap or "", desc_style),
                Paragraph("", zero_style),
                money(fee),
            ]
        else:
            row = [
                Paragraph(line.service_code_snap, code_style),
                Paragraph(line.description_snap, desc_style),
                money(line.effective_q1),
                money(line.effective_q2),
                money(line.effective_q3),
                money(line.effective_q4),
                money(line.total),
            ]
        data.append(row)

    # Riga totale
    if quarter:
        q_total = sum(getattr(l, f"effective_q{quarter}") for l in lines)
        total_row = [
            Paragraph("", tot_style), Paragraph("TOTALE", tot_style),
            Paragraph("", tot_style), Paragraph("", tot_style),
            Paragraph(fmt_currency(q_total).replace("€ ", ""), tot_style),
        ]
    else:
        annual = sum(l.total for l in lines)
        total_row = [
            Paragraph("", tot_style),
            Paragraph("TOTALE", tot_style),
            Paragraph(fmt_currency(sum(l.effective_q1 for l in lines)).replace("€ ", ""), tot_style),
            Paragraph(fmt_currency(sum(l.effective_q2 for l in lines)).replace("€ ", ""), tot_style),
            Paragraph(fmt_currency(sum(l.effective_q3 for l in lines)).replace("€ ", ""), tot_style),
            Paragraph(fmt_currency(sum(l.effective_q4 for l in lines)).replace("€ ", ""), tot_style),
            Paragraph(fmt_currency(annual).replace("€ ", ""), tot_style),
        ]
    data.append(total_row)

    n = len(data)
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), COLOR_PRIMARY),
        ("TOPPADDING", (0,0), (-1,0), 7),
        ("BOTTOMPADDING", (0,0), (-1,0), 7),
        ("TOPPADDING", (0,1), (-1,-1), 5),
        ("BOTTOMPADDING", (0,1), (-1,-1), 5),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        *[("BACKGROUND", (0,i), (-1,i), COLOR_LIGHT) for i in range(2, n-1, 2)],
        ("BACKGROUND", (0,-1), (-1,-1), COLOR_ACCENT),
        ("TOPPADDING", (0,-1), (-1,-1), 7),
        ("BOTTOMPADDING", (0,-1), (-1,-1), 7),
        ("LINEABOVE", (0,-1), (-1,-1), 1, COLOR_SECONDARY),
        ("BOX", (0,0), (-1,-1), 0.5, COLOR_BORDER),
        ("INNERGRID", (0,1), (-1,-1), 0.3, COLOR_BORDER),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    return [t]


def _build_footer(settings, styles) -> list:
    footer_text = settings.get("pdf_footer", "")
    if not footer_text:
        footer_text = (f"{settings.get('studio_name', '')} — "
                       f"Documento generato il {date.today().strftime('%d/%m/%Y')}")
    return [
        Spacer(1, 0.3*cm),
        HRFlowable(width="100%", thickness=0.5, color=COLOR_BORDER),
        Spacer(1, 0.2*cm),
        Paragraph(footer_text, styles["footer"]),
    ]


def _quarter_label(q: int) -> str:
    return {1: "1° Trimestre", 2: "2° Trimestre",
            3: "3° Trimestre", 4: "4° Trimestre"}.get(q, f"T{q}")


def _quarter_period(q: int, year: int) -> str:
    return {1: f"gennaio – marzo {year}", 2: f"aprile – giugno {year}",
            3: f"luglio – settembre {year}", 4: f"ottobre – dicembre {year}"}.get(q, "")
