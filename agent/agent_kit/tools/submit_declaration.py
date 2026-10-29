"""submit_declaration: file the SAD declaration (IM4).

The declaration is header, items, discrepancies, open_questions. Every header
field and every item field must be cited (1-3 exact quotes each) or named in
discrepancies/open_questions, or the filing is refused naming the missing fields.

Verification off: the declaration is filed unverified and the run ends (answered).
Verification on: the declaration rules (verification/verify_declaration.py) run first,
then the claims check (verification/verify_claims.py). A declaration that fails is
refused with the problems; after MAX_REFUSALS refused declarations the run escalates
to a person. A declaration that passes both waits for broker sign-off (awaiting_signoff).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .request_evidence import escalate

if TYPE_CHECKING:
    from . import Context

MAX_REFUSALS = 3

CITATION = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "document_id": {"type": "string"},
        "page": {"type": "integer"},
        "quote": {"type": "string"},
    },
    "required": ["document_id", "page", "quote"],
}
CITATION_LIST = {
    "type": "array",
    "items": CITATION,
    "minItems": 1,
    "maxItems": 3,
}
HEADER = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "declaration_type": {"type": "string"},
        "procedure_code": {"type": "string"},
        "importer": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"name": {"type": "string"}, "tin": {"type": "string"}},
            "required": ["name", "tin"],
        },
        "exporter": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string"},
                "country": {"type": "string"},
            },
            "required": ["name", "country"],
        },
        "transport": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "vessel": {"type": "string"},
                "bl_number": {"type": "string"},
                "container": {"type": "string"},
                "port_of_loading": {"type": "string"},
                "port_of_discharge": {"type": "string"},
            },
            "required": [
                "vessel",
                "bl_number",
                "container",
                "port_of_loading",
                "port_of_discharge",
            ],
        },
        "valuation": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "incoterm": {"type": "string"},
                "currency": {"type": "string"},
                "invoice_total": {"type": "number"},
            },
            "required": ["incoterm", "currency", "invoice_total"],
        },
        "citations": {
            "type": "object",
            "description": "1-3 citations per header field path "
            "(declaration_type, importer.name, importer.tin, transport.bl_number, ...). "
            "A field with no citations must be named in discrepancies or open_questions.",
            "additionalProperties": CITATION_LIST,
        },
    },
    "required": [
        "declaration_type",
        "procedure_code",
        "importer",
        "exporter",
        "transport",
        "valuation",
    ],
}
LINE_ITEM = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "line": {"type": "integer"},
        "description": {"type": "string"},
        "hs_code": {"type": "string"},
        "hs_justification": {"type": "string"},
        "origin": {"type": "string"},
        "packages": {"type": "integer"},
        "package_kind": {"type": "string"},
        "gross_kg": {"type": "number"},
        "net_kg": {"type": "number"},
        "supplementary_qty": {"type": "number"},
        "supplementary_unit": {"type": "string"},
        "item_value": {"type": "number"},
        "citations": CITATION_LIST,
    },
    "required": [
        "line",
        "description",
        "hs_code",
        "hs_justification",
        "origin",
        "packages",
        "package_kind",
        "gross_kg",
        "net_kg",
        "supplementary_qty",
        "supplementary_unit",
        "item_value",
    ],
}
DISCREPANCY = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "field": {
            "type": "string",
            "description": "field path, e.g. transport.bl_number or items[0].gross_kg",
        },
        "documents": {"type": "array", "items": {"type": "string"}},
        "detail": {"type": "string"},
    },
    "required": ["field", "documents", "detail"],
}

DEFINITION = {
    "type": "function",
    "name": "submit_declaration",
    "description": "File the SAD declaration: header boxes with per-field citations, goods items with "
    "HS codes and citations, discrepancies where documents disagree, and open questions. Every header "
    "and item field must be cited (1-3 quotes) or named in discrepancies/open_questions.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "header": HEADER,
            "items": {"type": "array", "items": LINE_ITEM},
            "discrepancies": {"type": "array", "items": DISCREPANCY},
            "open_questions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["header", "items", "discrepancies", "open_questions"],
    },
}


def run(ctx: Context, args: dict) -> dict:
    declaration = {
        "header": args.get("header") or {},
        "items": args.get("items") or [],
        "discrepancies": args.get("discrepancies") or [],
        "open_questions": args.get("open_questions") or [],
    }
    if not ctx.verification:
        ctx.case.file_declaration(declaration, "unverified")
        return {"filed": True, "declaration": "unverified", "status": "answered"}
    from verification import verify_claims

    verify_declaration = importlib.import_module(
        "verification.verify_declaration"
    )  # yours, built in Session 2
    check, result = "declaration", verify_declaration.run_verification(ctx, declaration)
    if result.get("passed"):
        ctx.case.record_declaration_check("declaration", [])
        check, result = "claims", verify_claims.run_verification(ctx, declaration)
    problems = (
        []
        if result.get("passed")
        else [str(p) for p in result.get("feedback") or ["refused"]]
    )
    ctx.case.record_declaration_check(check, problems)
    if problems:
        if ctx.case.declaration_refusals() >= MAX_REFUSALS:
            checklist = ctx.case.data["checklist"]
            item = next(
                (k for k, v in checklist.items() if v["status"] == "open"),
                next(iter(checklist), ""),
            )
            need = (
                f"The declaration was refused {ctx.case.declaration_refusals()} times. Last problems: "
                + "; ".join(problems)
            )
            return escalate(ctx, item, need, "declaration_refused")
        return {"error": "declaration refused", "check": check, "problems": problems}
    ctx.case.file_declaration(declaration, "awaiting_signoff")
    return {"filed": True, "declaration": "awaiting_signoff", "status": "awaiting_signoff"}
