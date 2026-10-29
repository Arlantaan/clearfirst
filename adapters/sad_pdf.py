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


def _pct(value) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) else text(value)


def _duty_rows(declaration: dict) -> list:
    """Boxes 46/47 from the compute_duty result filed with the declaration."""
    estimate = declaration.get("duty_estimate")
    levies = estimate.get("levies") if isinstance(estimate, dict) else None
    if not levies:
        return [("46", "Customs value", "Not computed"), ("47", "Taxes", "Not computed")]
    lines = [
        f"{text(l.get('code'))} {_pct(l.get('rate_pct'))}%: GMD {money(l.get('amount'))}"
        for l in levies
        if isinstance(l, dict)
    ]
    lines.append(f"Total payable: GMD {money(estimate.get('total_payable_gmd'))}")
    return [
        ("46", "Customs value", f"GMD {money(estimate.get('customs_value_gmd'))}"),
        ("47", "Taxes", "; ".join(lines)),
    ]


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
    rows.append(("Duty estimate", "", ""))
    rows.extend(_duty_rows(declaration))
    return rows


def render(declaration: dict, objective_text: str = "") -> bytes:
    """The declaration as PDF bytes (two pages)."""
    fictional = "fictional" in text(objective_text).lower()
    styles = getSampleStyleSheet()
    body = styles["Normal"]
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10)

    def cell(value, style=body):
        return Paragraph(escape(text(value)) or "—", style)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm
    )
    story: list = [
        Paragraph("Single Administrative Document — IM4", styles["Title"]),
        Spacer(1, 4 * mm),
        Table(
            [[cell(box), cell(label), cell(value)] for box, label, value in _boxes(declaration)],
            colWidths=[14 * mm, 38 * mm, 130 * mm],
            style=GRID,
        ),
        PageBreak(),
        Paragraph("Evidence, discrepancies and sign-off", styles["Heading2"]),
        Spacer(1, 3 * mm),
        Paragraph("Citations", styles["Heading3"]),
        Table(
            [[cell("Box", small), cell("Document", small), cell("Page", small), cell("Quote", small)]]
            + [
                [cell(box or field, small), cell(doc_id, small), cell(page, small), cell(quote, small)]
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
            canvas.setFillColor(colors.Color(0.7, 0, 0.7, 0.7))
            canvas.setFont("Helvetica-Bold", 64)
            canvas.rotate(45)
            canvas.drawCentredString(300, 100, "FICTIONAL DEMO")
        canvas.setFillColor(colors.black)
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(A4[0] - 14 * mm, 12 * mm, f"Page {_doc.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=frame, onLaterPages=frame)
    return buf.getvalue()
