"""
pdf_generator.py — PDF rendiconto con ReportLab.
Supporta: T1, T1+T2, T1+T2+T3, annuale.
"""
from __future__ import annotations
import io
from datetime import date
from typing import Optional
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from database import Client, FeeReport, get_all_settings
from utils import fmt_currency

C_PRIMARY = colors.HexColor("#1976d2")
C_LIGHT   = colors.HexColor("#f5f7fa")
C_ACCENT  = colors.HexColor("#e3f0fd")
C_BORDER  = colors.HexColor("#c5d3e0")
C_MUTED   = colors.HexColor("#6b7a8d")
C_TEXT    = colors.HexColor("#212121")


def _s(name, **kw):
    return ParagraphStyle(name, **kw)

def generate_fee_report_pdf(report: FeeReport, client: Client,
                             quarters: list[int] = None) -> bytes:
    """
    quarters: lista di trimestri da includere, es. [1] o [1,2] o [1,2,3,4]
    None o [1,2,3,4] = annuale completo
    """
    if quarters is None:
        quarters = [1, 2, 3, 4]

    settings = get_all_settings()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2.5*cm)

    hdr  = _s("h",  fontName="Helvetica-Bold", fontSize=14, textColor=C_PRIMARY)
    info = _s("i",  fontName="Helvetica", fontSize=8, textColor=C_MUTED, leading=11)
    rt   = _s("rt", fontName="Helvetica-Bold", fontSize=12, textColor=C_PRIMARY,
               alignment=TA_RIGHT)
    rs   = _s("rs", fontName="Helvetica", fontSize=8, textColor=C_MUTED, alignment=TA_RIGHT)
    sl   = _s("sl", fontName="Helvetica-Bold", fontSize=7.5, textColor=C_MUTED)
    cv   = _s("cv", fontName="Helvetica", fontSize=8.5, textColor=C_TEXT)
    th   = _s("th", fontName="Helvetica-Bold", fontSize=8, textColor=colors.white,
               alignment=TA_CENTER)
    td   = _s("td", fontName="Helvetica", fontSize=8.5, textColor=C_TEXT)
    tc   = _s("tc", fontName="Helvetica", fontSize=7.5, textColor=C_MUTED, alignment=TA_CENTER)
    tn   = _s("tn", fontName="Helvetica", fontSize=8.5, textColor=C_TEXT, alignment=TA_RIGHT)
    tz   = _s("tz", fontName="Helvetica", fontSize=8.5, textColor=C_MUTED, alignment=TA_RIGHT)
    tot  = _s("to", fontName="Helvetica-Bold", fontSize=9, textColor=C_PRIMARY, alignment=TA_RIGHT)
    ft   = _s("ft", fontName="Helvetica", fontSize=7, textColor=C_MUTED, alignment=TA_CENTER)
    nt   = _s("nt", fontName="Helvetica-Oblique", fontSize=8, textColor=C_MUTED)

    # Titolo documento
    q_labels = {1:"1° Trimestre", 2:"2° Trimestre", 3:"3° Trimestre", 4:"4° Trimestre"}
    if len(quarters) == 4:
        title = f"RENDICONTO ANNUALE {report.year}"
        subtitle = f"Anno {report.year}"
    elif len(quarters) == 1:
        title = f"RENDICONTO {q_labels[quarters[0]]} {report.year}"
        subtitle = _quarter_period(quarters[0], report.year)
    else:
        last_q = max(quarters)
        title = f"RENDICONTO CUMULATIVO {report.year}"
        subtitle = f"Periodo: {_quarter_period(1, report.year).split('–')[0].strip()} – {_quarter_period(last_q, report.year).split('–')[1].strip()}"

    studio = settings.get("studio_name","Studio")
    info_lines = [v for k in ("studio_address","studio_city","studio_phone","studio_email")
                  if (v := settings.get(k,""))]
    if settings.get("studio_piva"): info_lines.append(f"P.IVA: {settings['studio_piva']}")

    left  = [Paragraph(studio, hdr)] + [Paragraph(l, info) for l in info_lines]
    right = [Paragraph(title, rt), Paragraph(subtitle, rs)]
    header_t = Table([[left, right]], colWidths=["60%","40%"])
    header_t.setStyle(TableStyle([
        ("VALIGN",(0,0),(-1,-1),"TOP"),
        ("LEFTPADDING",(0,0),(-1,-1),0),
        ("RIGHTPADDING",(0,0),(-1,-1),0),
    ]))

    # Sezione cliente
    cl_rows = [
        [Paragraph("CLIENTE",sl), Paragraph("CODICE",sl), Paragraph("TIPOLOGIA",sl)],
        [Paragraph(client.name,cv), Paragraph(client.client_code,cv),
         Paragraph(client.client_type.title(),cv)],
    ]
    if client.vat_number or client.tax_code:
        labels = []
        vals   = []
        if client.vat_number: labels.append(Paragraph("P.IVA",sl)); vals.append(Paragraph(client.vat_number,cv))
        if client.tax_code:   labels.append(Paragraph("C.F.",sl));  vals.append(Paragraph(client.tax_code,cv))
        while len(labels) < 3: labels.append(Paragraph("",sl)); vals.append(Paragraph("",cv))
        cl_rows += [labels[:3], vals[:3]]
    cl_t = Table(cl_rows, colWidths=["45%","20%","35%"])
    cl_t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),C_ACCENT),
        ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
        ("TOPPADDING",(0,0),(-1,-1),4),  ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("BOX",(0,0),(-1,-1),0.5,C_BORDER), ("INNERGRID",(0,0),(-1,-1),0.3,C_BORDER),
    ]))

    # Tabella prestazioni
    def money(v):
        if not v: return Paragraph("—", tz)
        return Paragraph(fmt_currency(v).replace("€ ",""), tn)

    q_cols = [f"T{q}" for q in quarters]
    headers = ["Cod.", "Prestazione"] + q_cols + ["Totale periodo"]
    n_q = len(quarters)
    col_w = [1.5*cm, 16.5*cm / (n_q + 2)] * 0  # ricalcolo sotto
    total_w = 17*cm
    desc_w  = 7*cm
    code_w  = 1.5*cm
    num_w   = (total_w - desc_w - code_w) / (n_q + 1)
    col_widths = [code_w, desc_w] + [num_w] * n_q + [num_w]

    data = [[Paragraph(h, th) for h in headers]]

    lines = [l for l in report.lines if any(
        getattr(l, f"effective_q{q}") > 0 for q in quarters
    )]

    for i, line in enumerate(lines):
        q_vals = [getattr(line, f"effective_q{q}") for q in quarters]
        period_total = sum(q_vals)
        row = [Paragraph(line.service_code_snap, tc),
               Paragraph(line.description_snap, td)]
        row += [money(v) for v in q_vals]
        row += [money(period_total)]
        data.append(row)

    # Riga totale
    q_totals = [sum(getattr(l, f"effective_q{q}") for l in lines) for q in quarters]
    grand_total = sum(q_totals)
    total_row = [Paragraph("",tot), Paragraph("TOTALE",tot)]
    total_row += [Paragraph(fmt_currency(v).replace("€ ",""), tot) for v in q_totals]
    total_row += [Paragraph(fmt_currency(grand_total).replace("€ ",""), tot)]
    data.append(total_row)

    n = len(data)
    svc_t = Table(data, colWidths=col_widths, repeatRows=1)
    svc_t.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),C_PRIMARY),
        ("TOPPADDING",(0,0),(-1,0),7), ("BOTTOMPADDING",(0,0),(-1,0),7),
        ("TOPPADDING",(0,1),(-1,-1),5), ("BOTTOMPADDING",(0,1),(-1,-1),5),
        ("LEFTPADDING",(0,0),(-1,-1),5), ("RIGHTPADDING",(0,0),(-1,-1),5),
        *[("BACKGROUND",(0,i),(-1,i),C_LIGHT) for i in range(2,n-1,2)],
        ("BACKGROUND",(0,-1),(-1,-1),C_ACCENT),
        ("LINEABOVE",(0,-1),(-1,-1),1,C_PRIMARY),
        ("BOX",(0,0),(-1,-1),0.5,C_BORDER),
        ("INNERGRID",(0,1),(-1,-1),0.3,C_BORDER),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),
    ]))

    footer_text = settings.get("pdf_footer","") or \
        f"{studio} — Documento generato il {date.today().strftime('%d/%m/%Y')}"

    story = [
        header_t,
        Spacer(1, 0.5*cm),
        HRFlowable(width="100%", thickness=1, color=C_PRIMARY),
        Spacer(1, 0.4*cm),
        cl_t,
        Spacer(1, 0.5*cm),
        svc_t,
        Spacer(1, 0.5*cm),
    ]
    if report.notes:
        story += [Paragraph("Note:", _s("nl",fontName="Helvetica-Bold",fontSize=8,textColor=C_MUTED)),
                  Paragraph(report.notes, nt), Spacer(1,0.3*cm)]
    story += [
        HRFlowable(width="100%", thickness=0.5, color=C_BORDER),
        Spacer(1, 0.2*cm),
        Paragraph(footer_text, ft),
    ]
    doc.build(story)
    return buf.getvalue()


def _quarter_period(q, year):
    return {1: f"gennaio – marzo {year}", 2: f"aprile – giugno {year}",
            3: f"luglio – settembre {year}", 4: f"ottobre – dicembre {year}"}.get(q,"")
