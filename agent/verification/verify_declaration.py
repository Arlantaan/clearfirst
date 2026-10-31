"""The declaration rules for the SAD declaration. Plain code, no model call.

Called when the agent calls submit_declaration with VERIFICATION=on, and by
./helper verify RUN --declaration.

    run_verification(ctx, declaration) -> {"passed": bool, "feedback": [problem, ...]}

declaration = {"header": {values, "citations": {field path: [citation]}},
"items": [{line values, "citations": [citation]}], "discrepancies": [{field,
documents, detail}], "open_questions": [str]}. Each problem is one short sentence
naming the field; passed = no problems.

Rules:
1. Every checklist item is proven or escalated; no evidence request is still open.
2. Every citation matches a recorded fact (same document, page, and quote).
3. Every cited field's citation comes from a checklist item about that field
   (keywords in the item's question); broker-declared fields take no citation.
4. gross_kg, net_kg, packages, hs_code, importer.name and exporter.name are quoted
   in recorded facts from at least two documents, unless named in
   discrepancies/open_questions. For multi-item declarations, per-line
   gross_kg, net_kg and packages quoted on one document are accepted when the
   field total is quoted on a different document.
5. Nothing excluded is cited; a proven signature item has a consistent signature
   check on a document backing one of its recorded facts.
6. Header values are sane (positive totals, HS shape, 2-letter codes, net <= gross,
   item values sum to the invoice total within 0.5%).
"""

from __future__ import annotations

import re

from agent_kit import document_text

HEADER_KEYWORDS = {
    "importer": {"importer", "tin"},
    "exporter": {"exporter", "origin"},
    "transport": {"transport", "vessel", "container", "port", "lading"},
    "valuation": {"valuation", "value", "invoice", "currency", "incoterm"},
}
ITEM_KEYWORDS = {
    "goods",
    "hs",
    "description",
    "classification",
    "origin",
    "package",
    "weight",
    "quantity",
    "supplementary",
    "valuation",
    "value",
    "invoice",
}
HS_CODE = re.compile(r"^\d{4}\.\d{2}(\.\d{2})?$")
COUNTRY = re.compile(r"^[A-Za-z]{2}$")
_NUMBER = re.compile(r"\d[\d,]*\.?\d*")


def run_verification(ctx, declaration: dict) -> dict:
    case = ctx.case
    declaration = declaration if isinstance(declaration, dict) else {}
    header = declaration.get("header")
    header = header if isinstance(header, dict) else {}
    items = declaration.get("items")
    items = items if isinstance(items, list) else []
    discrepancies = declaration.get("discrepancies")
    discrepancies = discrepancies if isinstance(discrepancies, list) else []
    open_questions = declaration.get("open_questions")
    open_questions = open_questions if isinstance(open_questions, list) else []
    facts = case.data["facts"]
    problems = []

    named_fields = {
        str(d.get("field", "")).strip()
        for d in discrepancies
        if isinstance(d, dict) and str(d.get("field", "")).strip()
    }
    questions = [str(q) for q in open_questions]

    def named(path: str) -> bool:
        return path in named_fields or any(path in q for q in questions)

    # Rule 1: every item settled, no open request.
    for item_id, entry in case.data["checklist"].items():
        if entry.get("status") not in ("proven", "escalated"):
            problems.append(f"checklist item {item_id} is neither proven nor escalated.")
    for request in case.open_requests():
        problems.append(
            f"evidence request {request['id']} for {request['item']} is still open."
        )

    # The declaration's citations: (label, keywords or None, citation).
    cites = []
    header_cites = header.get("citations") or {}
    if not isinstance(header_cites, dict):
        problems.append("header citations must be an object keyed by field path.")
        header_cites = {}
    for path, entries in header_cites.items():
        for cite in entries or []:
            cites.append(
                (
                    f"header {path}",
                    HEADER_KEYWORDS.get(str(path).split(".")[0]),
                    cite,
                )
            )
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"items[{index}] must be an object.")
            continue
        item_cites = item.get("citations") or []
        if not isinstance(item_cites, list):
            problems.append(f"items[{index}] citations must be a list.")
            continue
        for cite in item_cites:
            cites.append((f"items[{index}]", ITEM_KEYWORDS, cite))

    # Rules 2, 3, 5 (excluded): each citation matches a fact from a related item.
    for label, keywords, cite in cites:
        document_id = str(cite.get("document_id", "")) if isinstance(cite, dict) else ""
        if document_id and case.flagged(document_id):
            problems.append(f"{label} cites excluded document {document_id}.")
            continue
        matches = _matching_facts(facts, cite)
        if not matches:
            problems.append(f"{label} cites a quote with no matching recorded fact.")
            continue
        if keywords:
            for fact in matches:
                entry = case.data["checklist"].get(fact["item"], {})
                text = f"{fact['item']} {entry.get('question', '')}"
                if any(_mentions(text, word) for word in keywords):
                    break
            else:
                problems.append(
                    f"{label} cites a fact from unrelated item {matches[0]['item']}."
                )

    # Rule 5 (signatures): a proven signature item has a consistent check on a
    # document backing one of its recorded facts.
    for item_id, entry in case.data["checklist"].items():
        if not entry.get("needs_signature_check") or entry.get("status") != "proven":
            continue
        docs = {f["document_id"] for f in facts if f["item"] == item_id}
        checks = [
            c for c in case.data["signature_checks"] if c.get("document_id") in docs
        ]
        if not checks:
            problems.append(
                f"{item_id} is proven but no document backing its facts was checked."
            )
        for check in checks:
            if check.get("verdict") == "inconsistent":
                problems.append(
                    f"{check.get('document_id')} p{check.get('page')} signature is "
                    f"inconsistent, so {item_id} is not proven."
                )

    # Rule 4: key values quoted in facts from at least two documents.
    dict_items = [item for item in items if isinstance(item, dict)]
    multi = len(dict_items) > 1
    line_fields = ("hs_code",) if multi else ("gross_kg", "net_kg", "packages", "hs_code")
    targets = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        for field in line_fields:
            targets.append((f"items[{index}].{field}", item.get(field), True))
    targets.append(("importer.name", _at(header, "importer.name"), False))
    targets.append(("exporter.name", _at(header, "exporter.name"), False))
    for label, value, numeric in targets:
        if named(label):
            continue
        if numeric:
            number = _as_number(value)
            if number is None:
                continue  # rule 6 flags it
            docs = {
                f["document_id"]
                for f in facts
                if _quote_has_number(f.get("quote", ""), number)
            }
        else:
            name = document_text.normalize(str(value or ""))
            if not name:
                continue
            docs = {
                f["document_id"]
                for f in facts
                if name in document_text.normalize(f.get("quote", ""))
            }
        if len(docs) < 2:
            problems.append(f"{label} is supported by only one document.")

    # Rule 4, multi-item weights/packages: per-line values quoted on one
    # document are accepted when the field total is quoted on another.
    if multi:
        lined = [(i, item) for i, item in enumerate(items) if isinstance(item, dict)]
        for field in ("gross_kg", "net_kg", "packages"):
            unnamed = [
                (i, item)
                for i, item in lined
                if not named(f"items[{i}].{field}")
            ]
            if not unnamed:
                continue
            numbers = [_as_number(item.get(field)) for _, item in lined]
            if any(n is None for n in numbers):
                # Rule 6 flags the bad values; rule 4 keeps the per-line shape.
                for i, item in unnamed:
                    number = _as_number(item.get(field))
                    if number is None:
                        continue
                    docs = {
                        f["document_id"]
                        for f in facts
                        if _quote_has_number(f.get("quote", ""), number)
                    }
                    if len(docs) < 2:
                        problems.append(
                            f"items[{i}].{field} is supported by only one document."
                        )
                continue
            docs_of = {
                i: {
                    f["document_id"]
                    for f in facts
                    if _quote_has_number(f.get("quote", ""), number)
                }
                for (i, _), number in zip(lined, numbers)
            }
            failing = [i for i, _ in unnamed if len(docs_of[i]) < 2]
            if not failing:
                continue
            total = sum(numbers)
            failing_docs = set().union(*(docs_of[i] for i in failing))
            corroborated = all(docs_of[i] for i in failing) and any(
                f.get("document_id") not in failing_docs
                and _quote_has_total(f.get("quote", ""), total)
                for f in facts
            )
            if not corroborated:
                problems.append(
                    f"items[].{field}: per-line values from one document and no "
                    f"second document quotes the total {_format_total(total)}"
                )

    # Rule 6: header value sanity.
    raw_total = _at(header, "valuation.invoice_total")
    total = _as_number(raw_total)
    if _is_blank(raw_total):
        problems.append("valuation.invoice_total is missing.")
    elif total is None or total <= 0:
        problems.append("valuation.invoice_total must be a positive number.")
    country = _at(header, "exporter.country")
    if _is_blank(country):
        problems.append("exporter.country is missing.")
    elif not isinstance(country, str) or not COUNTRY.match(country.strip()):
        problems.append("exporter.country must be a 2-letter code.")
    values = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        code = item.get("hs_code")
        if _is_blank(code):
            problems.append(f"items[{index}].hs_code is missing.")
        elif not isinstance(code, str) or not HS_CODE.match(code.strip()):
            problems.append(f"items[{index}].hs_code '{code}' is not a valid HS code.")
        origin = item.get("origin")
        if _is_blank(origin):
            problems.append(f"items[{index}].origin is missing.")
        elif not isinstance(origin, str) or not COUNTRY.match(origin.strip()):
            problems.append(f"items[{index}].origin must be a 2-letter code.")
        weighed = {}
        for field in ("packages", "gross_kg", "net_kg"):
            raw = item.get(field)
            number = _as_number(raw)
            if _is_blank(raw):
                problems.append(f"items[{index}].{field} is missing.")
            elif number is None or number <= 0:
                problems.append(f"items[{index}].{field} must be a positive number.")
            else:
                weighed[field] = number
        if (
            "gross_kg" in weighed
            and "net_kg" in weighed
            and weighed["net_kg"] > weighed["gross_kg"]
        ):
            problems.append(f"items[{index}].net_kg exceeds gross_kg.")
        raw_value = item.get("item_value")
        value = _as_number(raw_value)
        if _is_blank(raw_value):
            problems.append(f"items[{index}].item_value is missing.")
        elif value is None:
            problems.append(f"items[{index}].item_value must be a number.")
        else:
            values.append(value)
    if total and total > 0 and len(values) == len(dict_items) and dict_items:
        if abs(sum(values) - total) > abs(total) * 0.005:
            problems.append(
                f"item values sum to {sum(values):g} but valuation.invoice_total "
                f"is {total:g}."
            )

    return {"passed": not problems, "feedback": problems}


def _matching_facts(facts: list, cite) -> list:
    """Every recorded fact with the same document, page, and quote."""
    if not isinstance(cite, dict):
        return []
    try:
        page = int(cite.get("page"))
    except (TypeError, ValueError):
        return []
    document_id, quote = str(cite.get("document_id", "")), str(cite.get("quote", ""))
    return [
        fact
        for fact in facts
        if fact["document_id"] == document_id
        and fact["page"] == page
        and document_text.normalize(fact["quote"]) == document_text.normalize(quote)
    ]


def _mentions(text: str, keyword: str) -> bool:
    """The keyword starts a word in the text (so "port" skips "importer")."""
    return re.search(r"\b" + re.escape(keyword), (text or "").lower()) is not None


def _at(mapping: dict, path: str):
    """mapping["importer"]["tin"] for path "importer.tin"; None when absent."""
    value = mapping
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _is_blank(value) -> bool:
    """Missing, or a string with nothing in it. Numbers (even 0) count as present."""
    return value is None or (isinstance(value, str) and not value.strip())


def _as_number(value):
    """A value as a float, tolerating thousands separators; None when not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", "").replace(" ", ""))
        except ValueError:
            return None
    return None


def _quote_has_number(quote: str, number: float) -> bool:
    """A numeric token in the quote equals the value (commas ignored)."""
    for token in _NUMBER.findall(str(quote or "")):
        try:
            if float(token.replace(",", "")) == number:
                return True
        except ValueError:
            continue
    return False


def _quote_has_total(quote: str, total: float) -> bool:
    """A numeric token in the quote equals the total within 0.5%."""
    for token in _NUMBER.findall(str(quote or "")):
        try:
            if abs(float(token.replace(",", "")) - total) <= abs(total) * 0.005:
                return True
        except ValueError:
            continue
    return False


def _format_total(total: float) -> str:
    """4,700 — thousands separators, decimals only when needed."""
    return f"{int(total):,}" if float(total).is_integer() else f"{total:,}"
