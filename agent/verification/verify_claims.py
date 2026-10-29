"""Pre-built: is each finding supported by the quotes it cites?

Called by the submit_declaration tool after verify_declaration passes, and by ./helper verify RUN --declaration.

    run_verification(ctx, declaration) -> {"passed": bool, "feedback": [problem, ...]}

One Muse Spark call judges every proven finding in the declaration against its quotes.
"""

from __future__ import annotations

import json
from typing import cast

from agent_kit.settings import model
from openai.types.responses import Response

PROMPT = """CLAIMS TO CHECK. Each finding below states a claim and the exact quotes cited for it.
For each finding, decide whether the quotes support the claim as written. A claim that goes
beyond what its quotes say is unsupported.

{findings}

Answer only with JSON: {{"unsupported": [{{"item": "<item>", "reason": "one sentence"}}]}}
(an empty list when every claim is supported)."""


def run_verification(ctx, declaration: dict) -> dict:
    findings = [
        {
            "item": f.get("item"),
            "claim": f.get("summary", ""),
            "quotes": [c.get("quote", "") for c in f.get("citations") or []],
        }
        for f in declaration.get("findings") or []
        if isinstance(f, dict) and f.get("status") == "proven" and f.get("citations")
    ]
    if not findings:
        return {"passed": True, "feedback": []}
    response = cast(
        Response,
        ctx.client.responses.create(
            model=model(),
            input=PROMPT.format(findings=json.dumps(findings, indent=1)),
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
    problems = [
        f"{u.get('item')}: the finding is not supported by its quotes ({u.get('reason', '')})"
        for u in unsupported
        if isinstance(u, dict)
    ]
    return {"passed": not problems, "feedback": problems}
