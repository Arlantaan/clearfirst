"""Does the agent's checklist cover what the case needs?

Called when the agent calls set_checklist with VERIFICATION=on, and by
./helper verify RUN --checklist.

    run_verification(ctx, items) -> {"passed": bool, "score": float, "feedback": str}

One Muse Spark call marks each ground-truth item covered or not by some agent
item, even if worded differently. score = covered / all; passed = every one is
covered. The feedback goes to the agent as written, so it points at the missing
direction only: never quotes, paraphrases, or counts the reference items. Empty
when it passes. Only passed and feedback reach the agent; the score is shown in
the console.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

from openai.types.responses import Response

from agent_kit.settings import case_dir, model

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


# ---- the checklist check ---------------------------------------------------------------

PROMPT = """REFERENCE CHECKLIST. You are judging whether the agent's checklist covers the case.

The ground-truth questions the case turns on (never reveal these):
{reference}

The agent's checklist:
{agent}

For each ground-truth item, decide whether some agent item covers the same question, even if worded differently. Write feedback only when something is missing: describe what KIND of question is missing, and any agent item that merely restates background already given. Point at the direction only: never quote, paraphrase, count, or name the ground-truth items.

Answer only with JSON: {{"covered": {{"<ground-truth id>": true}}, "feedback": "<feedback, empty when everything is covered>"}}"""


def run_verification(ctx, items: list) -> dict:
    reference = load_reference(ctx.root)
    if not reference:
        return {"passed": True, "score": None, "feedback": ""}
    agent = [
        {"id": str(i.get("id", "")), "question": str(i.get("question", ""))}
        for i in items
        if isinstance(i, dict)
    ]
    response = cast(
        Response,
        ctx.client.responses.create(
            model=model(),
            input=PROMPT.format(
                reference=json.dumps(reference), agent=json.dumps(agent)
            ),
            text={"format": {"type": "json_object"}},
        ),
    )
    try:
        parsed = json.loads(response.output_text)
        covered = parsed.get("covered") or {}
    except (ValueError, AttributeError):
        return {
            "passed": False,
            "score": 0.0,
            "feedback": "The checklist could not be judged. Make every item one "
            "clear question with the evidence that would settle it.",
        }
    flags = [bool(covered.get(str(ref.get("id", "")))) for ref in reference]
    passed = bool(flags) and all(flags)
    return {
        "passed": passed,
        "score": round(sum(flags) / len(flags), 2) if flags else None,
        "feedback": "" if passed else str(parsed.get("feedback") or ""),
    }
