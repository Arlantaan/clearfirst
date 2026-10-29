"""What the SAD adapters share: broker identity, demo rates, the box map."""

# The broker signing the declaration (box 14). Broker identity, not shipment data.
DECLARANT = {"name": "Banjul Clearing & Forwarding Services", "code": "DEC-0417"}
# Customs office of entry (box 29).
OFFICE = "GMBJL — Banjul Port"
# Mode of transport at the border (box 25): 1 = sea.
TRANSPORT_MODE = "1 (Sea)"

# Box 46/47 hold no rates of their own: the agent computes the duty with the
# compute_duty tool against the country tariff pack and files the result with
# the declaration as duty_estimate; the adapters render that stored result.

# Cited header field path -> SAD box for the evidence page ("" when the path
# has no box on page 1; the field path itself is still shown).
FIELD_BOXES = {
    "declaration_type": "1",
    "procedure_code": "1",
    "exporter.name": "2",
    "exporter.country": "2",
    "importer.name": "8",
    "importer.tin": "8",
    "transport.vessel": "18",
    "transport.bl_number": "18",
    "transport.container": "19",
    "valuation.incoterm": "20",
    "valuation.currency": "22",
    "valuation.invoice_total": "22",
}


def text(value) -> str:
    return "" if value is None else str(value)


def number(value) -> str:
    """1,245 — counts and weights without trailing decimals."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return text(value)
    return f"{int(result):,}" if result.is_integer() else f"{result:,}"


def money(value) -> str:
    """21,000.00 — money with two decimals."""
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return text(value)


def header_citations(declaration: dict) -> list:
    """[(field, box, document_id, page, quote)] for every header citation."""
    header = declaration.get("header") or {}
    out = []
    for field, cites in (header.get("citations") or {}).items():
        cites = cites if isinstance(cites, list) else []
        for cite in cites:
            if not isinstance(cite, dict):
                continue
            out.append(
                (
                    text(field),
                    FIELD_BOXES.get(text(field), ""),
                    text(cite.get("document_id")),
                    text(cite.get("page")),
                    text(cite.get("quote")),
                )
            )
    return out


def item_citations(declaration: dict) -> list:
    """[(line, document_id, page, quote)] for every item citation."""
    out = []
    for item in declaration.get("items") or []:
        if not isinstance(item, dict):
            continue
        for cite in item.get("citations") or []:
            if not isinstance(cite, dict):
                continue
            out.append(
                (
                    text(item.get("line")),
                    text(cite.get("document_id")),
                    text(cite.get("page")),
                    text(cite.get("quote")),
                )
            )
    return out
