"""The filed SAD declaration as a two-page PDF.

Page 1 is the numbered SAD boxes; page 2 lists every citation, the
discrepancies and open questions, and the sign-off. Watermarked FICTIONAL
DEMO when the case objective says the documents are fictional.
"""

from html import escape
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from adapters.common import (
    DECLARANT,
    OFFICE,
    TRANSPORT_MODE,
    header_citations,
    item_citations,
    money,
    number,
    text,
)

GRID = TableStyle(
    [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
)


OLD_LEVY_CODES = ("IDF", "PRF", "AUL", "ECL", "GNSW", "VAT")


def _pct(value) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) else text(value)


def _duty_rows(declaration: dict) -> list:
    """Boxes 46/47 from the compute_duty result filed with the declaration."""
    estimate = declaration.get("duty_estimate")
    if not isinstance(estimate, dict):
        estimate = {}
    customs = estimate.get("customs_value_gmd", estimate.get("basis"))
    levies = estimate.get("levies")
    if levies is None:
        # Older compute_duty shape: per-levy amounts as top-level keys.
        levies = [
            {"code": code, "rate_pct": None, "amount": estimate[code]}
            for code in OLD_LEVY_CODES
            if isinstance(estimate.get(code), (int, float))
        ]
    else:
        levies = [l for l in levies if isinstance(l, dict)]
    total = estimate.get("total_payable_gmd")
    if customs is None and not levies and total is None:
        return [("46", "Customs value", "Not computed"), ("47", "Taxes", "Not computed")]
    lines = []
    for levy in levies:
        rate = levy.get("rate_pct")
        tag = ""
        if levy.get("line") is not None:
            tag = f" line {levy.get('line')}"
            if levy.get("hs"):
                tag += f" (HS {text(levy.get('hs'))})"
        prefix = (
            f"{text(levy.get('code'))} {_pct(rate)}%{tag}: "
            if isinstance(rate, (int, float))
            else f"{text(levy.get('code'))}{tag}: "
        )
        lines.append(f"{prefix}GMD {money(levy.get('amount'))}")
    if total is not None:
        lines.append(f"Total payable: GMD {money(total)}")
    return [
        (
            "46",
            "Customs value",
            f"GMD {money(customs)}" if customs is not None else "\u2014",
        ),
        ("47", "Taxes", "; ".join(lines) if lines else "\u2014"),
    ]


def _field_label(field: str) -> str:
    """Short label for a cited field with no SAD box (never the raw path)."""
    if field in ("transport.port_of_loading", "transport.port_of_discharge"):
        return "Ports"
    return text(field).split(".")[-1].replace("_", " ").capitalize() or "\u2014"


def _boxes(declaration: dict) -> list:
    """Page 1 as [(box, label, value)]: header boxes, one block per item, duty."""
    header = declaration.get("header") or {}
    imp, exp = header.get("importer") or {}, header.get("exporter") or {}
    tr, val = header.get("transport") or {}, header.get("valuation") or {}
    currency = text(val.get("currency"))
    rows = [
        (
            "1",
            "Declaration type",
            f"{text(header.get('declaration_type'))} ({text(header.get('procedure_code'))})",
        ),
        ("2", "Exporter", f"{text(exp.get('name'))}, {text(exp.get('country'))}"),
        (
            "8",
            "Importer",
            f"{text(imp.get('name'))} — TIN {text(imp.get('tin'))}",
        ),
        (
            "14",
            "Declarant",
            f"{DECLARANT['name']} ({DECLARANT['code']})",
        ),
        (
            "18",
            "Vessel",
            f"{text(tr.get('vessel'))} — B/L {text(tr.get('bl_number'))}",
        ),
        ("19", "Container", text(tr.get("container"))),
        ("20", "Incoterm", text(val.get("incoterm"))),
        (
            "22",
            "Currency / Total",
            f"{currency} {money(val.get('invoice_total'))}",
        ),
        ("25", "Mode of transport", TRANSPORT_MODE),
        ("29", "Office of entry", OFFICE),
    ]
    for item in declaration.get("items") or []:
        rows.append((f"Item {text(item.get('line'))}", "", ""))
        rows.extend(
            [
                (
                    "31",
                    "Packages / Description",
                    f"{number(item.get('packages'))} {text(item.get('package_kind'))} — "
                    f"{text(item.get('description'))}",
                ),
                ("33", "HS code", text(item.get("hs_code"))),
                ("34", "Origin", text(item.get("origin"))),
                ("35", "Gross (kg)", number(item.get("gross_kg"))),
                ("38", "Net (kg)", number(item.get("net_kg"))),
                (
                    "41",
                    "Supplementary units",
                    f"{number(item.get('supplementary_qty'))} "
                    f"{text(item.get('supplementary_unit'))}",
                ),
                (
                    "42",
                    "Item price",
                    f"{currency} {money(item.get('item_value'))}",
                ),
            ]
        )
    rows.append(("Duty", "", ""))
    rows.extend(_duty_rows(declaration))
    return rows


def render(
    declaration: dict, objective_text: str = "", shipment: str = "", exported: str = ""
) -> bytes:
    """The declaration as PDF bytes (two pages)."""
    from datetime import date

    fictional = "fictional" in text(objective_text).lower()
    header = declaration.get("header") or {}
    bl_number = text((header.get("transport") or {}).get("bl_number"))
    subtitle = " \u00b7 ".join(
        part
        for part in [
            f"Shipment: {shipment}" if shipment else "",
            f"B/L: {bl_number}" if bl_number else "",
            f"Exported: {exported or date.today().isoformat()}",
        ]
        if part
    )
    styles = getSampleStyleSheet()
    body = styles["Normal"]
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10)

    def cell(value, style=body):
        return Paragraph(escape(text(value)) or "—", style)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm
    )
    sub = ParagraphStyle("sub", parent=body, alignment=1, textColor=colors.grey)
    story: list = [
        Paragraph("Single Administrative Document — IM4", styles["Title"]),
        Paragraph(escape(subtitle), sub),
        Spacer(1, 4 * mm),
        Table(
            [[cell(box), cell(label), cell(value)] for box, label, value in _boxes(declaration)],
            colWidths=[20 * mm, 38 * mm, 124 * mm],
            style=GRID,
        ),
        PageBreak(),
        Paragraph("Evidence, discrepancies and sign-off", styles["Heading2"]),
        Spacer(1, 3 * mm),
        Paragraph("Citations", styles["Heading3"]),
        Table(
            [[cell("Box", small), cell("Document", small), cell("Page", small), cell("Quote", small)]]
            + [
                [cell(box or _field_label(field), small), cell(doc_id, small), cell(page, small), cell(quote, small)]
                for field, box, doc_id, page, quote in header_citations(declaration)
            ]
            + [
                [
                    cell(f"31–42 (item {line})", small),
                    cell(doc_id, small),
                    cell(page, small),
                    cell(quote, small),
                ]
                for line, doc_id, page, quote in item_citations(declaration)
            ],
            colWidths=[24 * mm, 38 * mm, 12 * mm, 108 * mm],
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ]
            ),
        ),
    ]
    discs = [
        Paragraph(
            escape(
                f"{text(d.get('field'))} "
                f"[{', '.join(text(x) for x in d.get('documents') or [])}]: "
                f"{text(d.get('detail'))}"
            ),
            small,
        )
        for d in declaration.get("discrepancies") or []
        if isinstance(d, dict)
    ] or [Paragraph("None", small)]
    questions = [
        Paragraph(escape(text(q)), small)
        for q in declaration.get("open_questions") or []
    ] or [Paragraph("None", small)]
    story += [
        Spacer(1, 4 * mm),
        Paragraph("Discrepancies", styles["Heading3"]),
        *discs,
        Spacer(1, 4 * mm),
        Paragraph("Open questions", styles["Heading3"]),
        *questions,
    ]
    review = declaration.get("review") or {}
    story += [
        Spacer(1, 4 * mm),
        Paragraph("Sign-off", styles["Heading3"]),
        Paragraph(
            escape(
                f"Broker: {DECLARANT['name']} ({DECLARANT['code']}) — "
                f"{text(review.get('decision'))} at {text(review.get('at'))}"
            ),
            small,
        ),
        Paragraph(escape(f"Notes: {text(review.get('notes')) or '—'}"), small),
    ]

    def frame(canvas, _doc) -> None:
        canvas.saveState()
        if fictional:
            canvas.setFillColor(colors.grey)
            canvas.setFillAlpha(0.3)
            canvas.setFont("Helvetica-Bold", 48)
            canvas.translate(A4[0] / 2, A4[1] / 2)
            canvas.rotate(45)
            canvas.drawCentredString(0, 0, "FICTIONAL DEMO")
            canvas.setFillAlpha(1)
        canvas.setFillColor(colors.black)
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(A4[0] - 14 * mm, 12 * mm, f"Page {_doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    return buf.getvalue()
