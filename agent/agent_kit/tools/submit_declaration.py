"""submit_declaration: file the case declaration.

Verification off: the declaration is filed unverified and the run ends (answered).
Verification on: the declaration rules (verification/verify_declaration.py) run first, then the claims
check (verification/verify_claims.py). A declaration that fails is refused with the problems; after
MAX_REFUSALS refused declarations the run escalates to a person. A declaration that passes both waits
for broker sign-off (awaiting_signoff).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .request_evidence import escalate

if TYPE_CHECKING:
    from . import Context

MAX_REFUSALS = 3

ITEM = {
    "type": "string",
    "description": "id of an item in your checklist (set_checklist)",
}
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
FINDING = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "item": ITEM,
        "status": {"type": "string", "enum": ["proven", "not_proven", "escalated"]},
        "summary": {"type": "string"},
        "citations": {"type": "array", "items": CITATION, "maxItems": 3},
    },
    "required": ["item", "status", "summary", "citations"],
}

DEFINITION = {
    "type": "function",
    "name": "submit_declaration",
    "description": "File the case declaration: the answer to the question in 2-3 sentences, one finding per checklist item "
    "in one sentence citing its 1-3 strongest recorded facts, and the remaining gaps as a short list.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "conclusion": {"type": "string"},
            "findings": {"type": "array", "items": FINDING},
            "gaps": {"type": "string"},
        },
        "required": ["conclusion", "findings", "gaps"],
    },
}


def run(ctx: Context, args: dict) -> dict:
    declaration = {
        "conclusion": str(args.get("conclusion", "")),
        "findings": args.get("findings") or [],
        "gaps": str(args.get("gaps", "")),
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
