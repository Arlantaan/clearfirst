"""Pre-built: is each cited value supported by the quotes cited for it?

Called by the submit_declaration tool after verify_declaration passes, and by ./helper verify RUN --declaration.

    run_verification(ctx, declaration) -> {"passed": bool, "feedback": [problem, ...]}

One Muse Spark call judges every cited field in the declaration against its quotes
(hs_justification excluded: agent reasoning, not a document fact).
"""

from __future__ import annotations

import json
from typing import cast

from agent_kit.case_record import ITEM_FIELDS
from agent_kit.settings import model
from openai.types.responses import Response

PROMPT = """CLAIMS TO CHECK. Each entry below states a declaration field, its filed value, and the exact quotes cited for it.
For each entry, decide whether the quotes support the value as written. A value that goes
beyond what its quotes say is unsupported; a quote that merely comes from the same document
but says nothing about the field does not support it. A quote supports a value when it is
the same thing in another form: a country name supports its ISO 2-letter code (TURKIYE
supports TR, CHINA supports CN); numbers match ignoring thousands separators, decimals
and units; a short package or unit word matches its longer form on the document.

{fields}

Answer only with JSON: {{"unsupported": [{{"field": "<field>", "reason": "one sentence"}}]}}
(an empty list when every value is supported)."""


def run_verification(ctx, declaration: dict) -> dict:
    declaration = declaration if isinstance(declaration, dict) else {}
    header = declaration.get("header")
    header = header if isinstance(header, dict) else {}
    claims = []
    citations = header.get("citations") or {}
    if isinstance(citations, dict):
        for path, entries in citations.items():
            quotes = [
                c.get("quote", "")
                for c in (entries or [])
                if isinstance(c, dict)
            ]
            if quotes:
                claims.append(
                    {
                        "field": str(path),
                        "value": _at(header, str(path)),
                        "quotes": quotes,
                    }
                )
    items = declaration.get("items")
    if isinstance(items, list):
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            quotes = [
                c.get("quote", "")
                for c in (item.get("citations") or [])
                if isinstance(c, dict)
            ]
            if not quotes:
                continue
            for field in ITEM_FIELDS:
                if field == "hs_justification":
                    continue  # agent reasoning, not a document fact
                claims.append(
                    {
                        "field": f"items[{index}].{field}",
                        "value": item.get(field),
                        "quotes": quotes,
                    }
                )
    if not claims:
        return {"passed": True, "feedback": []}
    response = cast(
        Response,
        ctx.client.responses.create(
            model=model(),
            input=PROMPT.format(fields=json.dumps(claims, indent=1)),
            text={"format": {"type": "json_object"}},
        ),
    )
    try:
        unsupported = json.loads(response.output_text).get("unsupported") or []
    except (ValueError, AttributeError):
        return {
            "passed": True,
            "feedback": [],
        }  # an unreadable judgement never blocks the declaration
    values = {claim["field"]: claim["value"] for claim in claims}
    problems = [
        f"{u.get('field')}: {values.get(u.get('field'), '')} — quotes do not support it"
        for u in unsupported
        if isinstance(u, dict)
    ]
    return {"passed": not problems, "feedback": problems}


def _at(mapping: dict, path: str):
    """mapping["importer"]["tin"] for path "importer.tin"; None when absent."""
    value = mapping
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value
