"""The filed SAD declaration as XML: one element per box, plus items, evidence and duty."""

import xml.etree.ElementTree as ET

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


def _box(parent, num: str, name: str, value: str) -> None:
    el = ET.SubElement(parent, "box", number=num, name=name)
    el.text = value


def render(declaration: dict) -> bytes:
    """The declaration as UTF-8 XML bytes."""
    header = declaration.get("header") or {}
    imp, exp = header.get("importer") or {}, header.get("exporter") or {}
    tr, val = header.get("transport") or {}, header.get("valuation") or {}
    currency = text(val.get("currency"))
    review = declaration.get("review") or {}

    sad = ET.Element("sad", procedure=text(header.get("procedure_code")))
    head = ET.SubElement(sad, "header")
    _box(head, "1", "Declaration type", text(header.get("declaration_type")))
    _box(head, "2", "Exporter", f"{text(exp.get('name'))}, {text(exp.get('country'))}")
    _box(head, "8", "Importer", f"{text(imp.get('name'))} — TIN {text(imp.get('tin'))}")
    _box(head, "14", "Declarant", f"{DECLARANT['name']} ({DECLARANT['code']})")
    _box(head, "18", "Vessel", f"{text(tr.get('vessel'))} — B/L {text(tr.get('bl_number'))}")
    _box(head, "19", "Container", text(tr.get("container")))
    _box(head, "20", "Incoterm", text(val.get("incoterm")))
    _box(
        head,
        "22",
        "Currency and total",
        f"{currency} {money(val.get('invoice_total'))}",
    )
    _box(head, "25", "Mode of transport", TRANSPORT_MODE)
    _box(head, "29", "Office of entry", OFFICE)

    items = ET.SubElement(sad, "items")
    for item in declaration.get("items") or []:
        el = ET.SubElement(items, "item", line=text(item.get("line")))
        _box(
            el,
            "31",
            "Packages and description",
            f"{number(item.get('packages'))} {text(item.get('package_kind'))} — "
            f"{text(item.get('description'))}",
        )
        _box(el, "33", "HS code", text(item.get("hs_code")))
        _box(el, "34", "Origin", text(item.get("origin")))
        _box(el, "35", "Gross kg", number(item.get("gross_kg")))
        _box(el, "38", "Net kg", number(item.get("net_kg")))
        _box(
            el,
            "41",
            "Supplementary units",
            f"{number(item.get('supplementary_qty'))} "
            f"{text(item.get('supplementary_unit'))}",
        )
        _box(el, "42", "Item price", f"{currency} {money(item.get('item_value'))}")

    estimate = declaration.get("duty_estimate")
    if isinstance(estimate, dict) and estimate.get("levies"):
        ET.SubElement(sad, "customsValue", currency="GMD").text = money(
            estimate.get("customs_value_gmd")
        )
        tax_el = ET.SubElement(sad, "tax", currency="GMD")
        for levy in estimate["levies"]:
            if not isinstance(levy, dict):
                continue
            attrs = {
                "code": text(levy.get("code")),
                "name": text(levy.get("name")),
                "rate": text(levy.get("rate_pct")),
            }
            if levy.get("line") is not None:
                attrs["item_line"] = str(levy.get("line"))
            if levy.get("hs"):
                attrs["hs"] = text(levy.get("hs"))
            ET.SubElement(tax_el, "line", **attrs).text = money(levy.get("amount"))
        ET.SubElement(tax_el, "total").text = money(estimate.get("total_payable_gmd"))

    discs = ET.SubElement(sad, "discrepancies")
    for entry in declaration.get("discrepancies") or []:
        if not isinstance(entry, dict):
            continue
        el = ET.SubElement(
            discs,
            "discrepancy",
            field=text(entry.get("field")),
            documents=", ".join(text(d) for d in entry.get("documents") or []),
        )
        el.text = text(entry.get("detail"))

    questions = ET.SubElement(sad, "openQuestions")
    for question in declaration.get("open_questions") or []:
        ET.SubElement(questions, "question").text = text(question)

    cites = ET.SubElement(sad, "citations")
    for field, box, doc_id, page, quote in header_citations(declaration):
        el = ET.SubElement(
            cites, "citation", field=field, box=box, document=doc_id, page=page
        )
        el.text = quote
    for line, doc_id, page, quote in item_citations(declaration):
        el = ET.SubElement(
            cites,
            "citation",
            field=f"items[{line}]",
            box=f"31–42 (item {line})",
            document=doc_id,
            page=page,
        )
        el.text = quote

    ET.SubElement(
        sad,
        "signOff",
        broker=f"{DECLARANT['name']} ({DECLARANT['code']})",
        decision=text(review.get("decision")),
        notes=text(review.get("notes")),
        at=text(review.get("at")),
    )

    ET.indent(sad)
    return ET.tostring(sad, encoding="utf-8", xml_declaration=True)
