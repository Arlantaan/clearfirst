"""Does the agent's checklist cover what the case needs?

Called when the agent calls set_checklist with VERIFICATION=on, and by
./helper verify RUN --checklist.

    run_verification(ctx, items) -> {"passed": bool, "score": float, "feedback": str}

Muse Spark marks each reference item covered or not and writes feedback that points to
what is missing without stating it; code turns the marks into the score.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

from agent_kit.settings import case_dir, model
from openai.types.responses import Response

# ---- pre-built: the ground truth (don't change) ----------------------------------------
# It lives outside this folder (GROUND_TRUTH_DIR, default ../ground_truth), one
# <case folder name>.json per case. Read it only through load_reference.


def reference_path(root: Path) -> Path:
    folder = Path(os.environ.get("GROUND_TRUTH_DIR") or "../ground_truth").expanduser()
    if not folder.is_absolute():
        folder = (Path(root) / folder).resolve()
    return folder / f"{case_dir(root).name}.json"


def load_reference(root: Path) -> list | None:
    """The case's ground-truth items, or None if the case has none."""
    path = reference_path(root)
    return json.loads(path.read_text())["items"] if path.is_file() else None


# ---- yours ---------------------------------------------------------------------------

PROMPT = """You review an investigation checklist against a REFERENCE CHECKLIST that the agent must not see.

REFERENCE CHECKLIST (what the investigation must cover):
{reference}

AGENT CHECKLIST (what the agent plans to prove):
{agent}

1. For each reference item, decide whether some agent item asks the same thing, even if worded differently.
2. Write feedback for the agent: what kind of question its checklist is missing, and any item that only
   restates background instead of something to prove. Point to the direction only. Do not quote,
   paraphrase, or count the reference items. Empty when every reference item is covered.

Answer only with JSON: {{"covered": {{"<reference id>": true or false}}, "feedback": "..."}}"""


def run_verification(ctx, items: list) -> dict:
    reference = load_reference(ctx.root)
    if reference is None:
        return {"passed": True, "score": None, "feedback": ""}
    prompt = PROMPT.format(
        reference=json.dumps(
            [{"id": r["id"], "question": r["question"]} for r in reference], indent=1
        ),
        agent=json.dumps(
            [{"id": i.get("id"), "question": i.get("question")} for i in items],
            indent=1,
        ),
    )
    response = cast(
        Response,
        ctx.client.responses.create(
            model=model(), input=prompt, text={"format": {"type": "json_object"}}
        ),
    )
    try:
        answer = json.loads(response.output_text)
        marks, feedback = answer.get("covered") or {}, str(answer.get("feedback") or "")
    except (ValueError, AttributeError):
        marks, feedback = {}, ""
    covered = sum(1 for r in reference if marks.get(r["id"]) is True)
    score = covered / len(reference) if reference else 1.0
    passed = score >= 1.0
    if not passed and not feedback:
        feedback = "The checklist does not yet cover everything the question turns on."
    return {
        "passed": passed,
        "score": round(score, 2),
        "feedback": "" if passed else feedback,
    }
