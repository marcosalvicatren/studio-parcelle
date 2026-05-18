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

from database import Client, FeeReport, FeeReportLine, get_all_settings
from utils import fmt_currency


# ---------------------------------------------------------------------------
# Palette colori
# ---------------------------------------------------------------------------

COLOR_PRIMARY   = colors.HexColor("#1a3a5c")   # blu scuro
COLOR_SECONDARY = colors.HexColor("#2e6da4")   # blu medio
COLOR_ACCENT    = colors.HexColor("#e8f0f7")   # azzurro chiaro (sfondo header tabella)
COLOR_LIGHT     = colors.HexColor("#f5f7fa")   # grigio chiarissimo (righe alternate)
COLOR_BORDER    = colors.HexColor("#c5d3e0")   # bordo tabella
COLOR_TEXT      = colors.HexColor("#1a1a2e")   # testo principale
COLOR_MUTED     = colors.HexColor("#6b7a8d")   # testo secondario


# ---------------------------------------------------------------------------
# Stili tipografici
# ---------------------------------------------------------------------------

def _build_styles():
    base = getSampleStyleSheet()
    styles = {}

    styles["studio_name"] = ParagraphStyle(
        "studio_name",
        fontName="Helvetica-Bold",
        fontSize=15,
        textColor=COLOR_PRIMARY,
        spaceAfter=2,
    )
    styles["studio_info"] = ParagraphStyle(
        "studio_info",
        fontName="Helvetica",
        fontSize=8,
        textColor=COLOR_MUTED,
        spaceAfter=1,
        leading=11,
    )
    styles["doc_title"] = ParagraphStyle(
        "doc_title",
        fontName="Helvetica-Bold",
        fontSize=13,
        textColor=COLOR_PRIMARY,
        alignment=TA_RIGHT,
        spaceAfter=2,
    )
    styles["doc_subtitle"] = ParagraphStyle(
        "doc_subtitle",
        fontName="Helvetica",
        fontSize=9,
        textColor=COLOR_MUTED,
        alignment=TA_RIGHT,
    )
    styles["section_label"] = ParagraphStyle(
        "section_label",
        fontName="Helvetica-Bold",
        fontSize=8,
        textColor=COLOR_MUTED,
        spaceAfter=1,
    )
    styles["client_name"] = ParagraphStyle(
        "client_name",
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=COLOR_TEXT,
        spaceAfter=2,
    )
    styles["client_detail"] = ParagraphStyle(
        "client_detail",
        fontName="Helvetica",
        fontSize=8.5,
        textColor=COLOR_TEXT,
        leading=13,
    )
    styles["footer"] = ParagraphStyle(
        "footer",
        fontName="Helvetica",
        fontSize=7,
        textColor=COLOR_MUTED,
        alignment=TA_CENTER,
    )
    styles["total_label"] = ParagraphStyle(
        "total_label",
        fontName="Helvetica-Bold",
        fontSize=9,
        textColor=COLOR_PRIMARY,
        alignment=TA_RIGHT,
    )
    styles["notes_text"] = ParagraphStyle(
        "notes_text",
        fontName="Helvetica-Oblique",
        fontSize=8,
        textColor=COLOR_MUTED,
        spaceAfter=4,
    )
    return styles


# ---------------------------------------------------------------------------
# Builder principale
# ---------------------------------------------------------------------------

def generate_fee_report_pdf(
    report: FeeReport,
    client: Client,
    quarter: Optional[int] = None,   # None = annuale, 1-4 = trimestrale
) -> bytes:
    """
    Genera il PDF rendiconto.
    quarter=None → documento annuale con colonne T1/T2/T3/T4/Totale
    quarter=1..4  → documento singolo trimestre
    """
    settings = get_all_settings()
    styles = _build_styles()
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2*cm,
        rightMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2.5*cm,
        title=f"Rendiconto {report.year} - {client.name}",
        author=settings.get("studio_name", ""),
    )

    story = []

    # ------------------------------------------------------------------
    # INTESTAZIONE
    # ------------------------------------------------------------------
    story.extend(_build_header(settings, report, client, quarter, styles))

    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=COLOR_SECONDARY))
    story.append(Spacer(1, 0.4*cm))

    # ------------------------------------------------------------------
    # DATI CLIENTE
    # ------------------------------------------------------------------
    story.extend(_build_client_section(client, styles))
    story.append(Spacer(1, 0.5*cm))

    # ------------------------------------------------------------------
    # TABELLA PRESTAZIONI
    # ------------------------------------------------------------------
    story.extend(_build_services_table(report, quarter, styles))
    story.append(Spacer(1, 0.6*cm))

    # ------------------------------------------------------------------
    # NOTE
    # ------------------------------------------------------------------
    if report.notes:
        story.append(Paragraph("Note:", styles["section_label"]))
        story.append(Paragraph(report.notes, styles["notes_text"]))
        story.append(Spacer(1, 0.3*cm))

    # ------------------------------------------------------------------
    # FOOTER
    # ------------------------------------------------------------------
    story.extend(_build_footer(settings, styles))

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Sezioni
# ---------------------------------------------------------------------------

def _build_header(settings, report, client, quarter, styles) -> list:
    """Intestazione a due colonne: studio a sinistra, titolo doc a destra."""
    studio_name = settings.get("studio_name", "Studio")
    studio_info_lines = []
    for key in ("studio_address", "studio_city", "studio_phone", "studio_email"):
        val = settings.get(key, "")
        if val:
            studio_info_lines.append(val)
    if settings.get("studio_piva"):
        studio_info_lines.append(f"P.IVA: {settings['studio_piva']}")

    left_content = [
        Paragraph(studio_name, styles["studio_name"]),
        *[Paragraph(line, styles["studio_info"]) for line in studio_info_lines],
    ]

    if quarter:
        doc_title = f"RENDICONTO {_quarter_label(quarter)} {report.year}"
        doc_sub = f"Periodo: {_quarter_period(quarter, report.year)}"
    else:
        doc_title = f"RENDICONTO ANNUALE {report.year}"
        doc_sub = f"Anno {report.year}"

    right_content = [
        Paragraph(doc_title, styles["doc_title"]),
        Paragraph(doc_sub, styles["doc_subtitle"]),
    ]

    header_data = [[left_content, right_content]]
    header_table = Table(header_data, colWidths=["60%", "40%"])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return [header_table]


def _build_client_section(client: Client, styles) -> list:
    label_style = styles["section_label"]
    val_style = styles["client_detail"]

    rows = [
        [Paragraph("CLIENTE", label_style),
         Paragraph("CODICE", label_style),
         Paragraph("TIPOLOGIA", label_style)],
        [Paragraph(client.name, val_style),
         Paragraph(client.client_code, val_style),
         Paragraph(client.client_type.title(), val_style)],
    ]

    extra_rows = []
    if client.vat_number:
        extra_rows.append(("P.IVA", client.vat_number))
    if client.tax_code:
        extra_rows.append(("Cod. Fiscale", client.tax_code))

    if extra_rows:
        rows.append([Paragraph(k, label_style) for k, _ in extra_rows]
                    + [Paragraph("", label_style)] * (3 - len(extra_rows)))
        rows.append([Paragraph(v, val_style) for _, v in extra_rows]
                    + [Paragraph("", val_style)] * (3 - len(extra_rows)))

    t = Table(rows, colWidths=["45%", "20%", "35%"])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_ACCENT),
        ("ROWBACKGROUND", (0, 2), (-1, 2), COLOR_ACCENT) if len(rows) > 2 else ("", (0,0),(0,0),""),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, COLOR_BORDER),
    ]))
    return [t]


def _build_services_table(report: FeeReport, quarter: Optional[int], styles) -> list:
    """Tabella principale prestazioni."""
    lines = [l for l in report.lines if l.total > 0 or any([
        l.driver_q1, l.driver_q2, l.driver_q3, l.driver_q4
    ])]

    # Header colonne
    if quarter:
        q_label = _quarter_label(quarter)
        headers = ["Cod.", "Prestazione", "Categoria", q_label, "Importo"]
        col_widths = [1.5*cm, 7.5*cm, 3*cm, 2.5*cm, 2.5*cm]
    else:
        headers = ["Cod.", "Prestazione", "T1", "T2", "T3", "T4", "Totale"]
        col_widths = [1.5*cm, 6.5*cm, 2*cm, 2*cm, 2*cm, 2*cm, 2.5*cm]

    header_style = ParagraphStyle("th", fontName="Helvetica-Bold",
                                  fontSize=8, textColor=colors.white, alignment=TA_CENTER)
    desc_style = ParagraphStyle("td_desc", fontName="Helvetica", fontSize=8.5,
                                textColor=COLOR_TEXT)
    code_style = ParagraphStyle("td_code", fontName="Helvetica", fontSize=7.5,
                                textColor=COLOR_MUTED, alignment=TA_CENTER)
    cat_style  = ParagraphStyle("td_cat", fontName="Helvetica", fontSize=7.5,
                                textColor=COLOR_MUTED)
    num_style  = ParagraphStyle("td_num", fontName="Helvetica", fontSize=8.5,
                                textColor=COLOR_TEXT, alignment=TA_RIGHT)
    zero_style = ParagraphStyle("td_zero", fontName="Helvetica", fontSize=8.5,
                                textColor=COLOR_MUTED, alignment=TA_RIGHT)

    def money(val):
        if val is None or val == 0:
            return Paragraph("—", zero_style)
        return Paragraph(fmt_currency(val).replace("€ ", ""), num_style)

    data = [[Paragraph(h, header_style) for h in headers]]

    for i, line in enumerate(lines):
        if quarter == 1:
            fee = line.effective_q1
        elif quarter == 2:
            fee = line.effective_q2
        elif quarter == 3:
            fee = line.effective_q3
        elif quarter == 4:
            fee = line.effective_q4
        else:
            fee = None

        if quarter:
            row = [
                Paragraph(line.service_code_snap, code_style),
                Paragraph(line.description_snap, desc_style),
                Paragraph(line.category_snap or "", cat_style),
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
    total_style = ParagraphStyle("total", fontName="Helvetica-Bold", fontSize=9,
                                 textColor=COLOR_PRIMARY, alignment=TA_RIGHT)
    if quarter:
        q_total = sum(
            getattr(l, f"effective_q{quarter}") for l in lines
        )
        total_row = [
            Paragraph("", total_style),
            Paragraph("TOTALE", total_style),
            Paragraph("", total_style),
            Paragraph("", total_style),
            Paragraph(fmt_currency(q_total).replace("€ ", ""), total_style),
        ]
    else:
        annual_total = sum(l.total for l in lines)
        total_row = [
            Paragraph("", total_style),
            Paragraph("TOTALE", total_style),
            Paragraph(fmt_currency(sum(l.effective_q1 for l in lines)).replace("€ ", ""), total_style),
            Paragraph(fmt_currency(sum(l.effective_q2 for l in lines)).replace("€ ", ""), total_style),
            Paragraph(fmt_currency(sum(l.effective_q3 for l in lines)).replace("€ ", ""), total_style),
            Paragraph(fmt_currency(sum(l.effective_q4 for l in lines)).replace("€ ", ""), total_style),
            Paragraph(fmt_currency(annual_total).replace("€ ", ""), total_style),
        ]
    data.append(total_row)

    t = Table(data, colWidths=col_widths, repeatRows=1)

    n_rows = len(data)
    style_cmds = [
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), COLOR_PRIMARY),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        # Righe dati
        ("FONTSIZE", (0, 1), (-1, -2), 8.5),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        # Righe alternate
        *[("BACKGROUND", (0, i), (-1, i), COLOR_LIGHT)
          for i in range(2, n_rows - 1, 2)],
        # Riga totale
        ("BACKGROUND", (0, -1), (-1, -1), COLOR_ACCENT),
        ("TOPPADDING", (0, -1), (-1, -1), 7),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 7),
        ("LINEABOVE", (0, -1), (-1, -1), 1, COLOR_SECONDARY),
        # Bordi
        ("BOX", (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ("INNERGRID", (0, 1), (-1, -1), 0.3, COLOR_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    t.setStyle(TableStyle(style_cmds))

    return [t]


def _build_footer(settings, styles) -> list:
    footer_text = settings.get("pdf_footer", "")
    if not footer_text:
        footer_text = (
            f"{settings.get('studio_name', '')} — "
            f"Documento generato il {date.today().strftime('%d/%m/%Y')}"
        )
    return [
        Spacer(1, 0.3*cm),
        HRFlowable(width="100%", thickness=0.5, color=COLOR_BORDER),
        Spacer(1, 0.2*cm),
        Paragraph(footer_text, styles["footer"]),
    ]


# ---------------------------------------------------------------------------
# Utility date
# ---------------------------------------------------------------------------

def _quarter_label(q: int) -> str:
    return {1: "1° Trimestre", 2: "2° Trimestre",
            3: "3° Trimestre", 4: "4° Trimestre"}.get(q, f"T{q}")


def _quarter_period(q: int, year: int) -> str:
    periods = {
        1: f"gennaio – marzo {year}",
        2: f"aprile – giugno {year}",
        3: f"luglio – settembre {year}",
        4: f"ottobre – dicembre {year}",
    }
    return periods.get(q, "")
