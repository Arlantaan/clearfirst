"""Does the agent's checklist cover what the case needs? run_verification is not implemented yet.

Called when the agent calls set_checklist with VERIFICATION=on, and by
./helper verify RUN --checklist.

    run_verification(ctx, items) -> {"passed": bool, "score": float, "feedback": str}

- items: the agent's checklist items: [{"id", "question", "evidence_needed", ...}, ...]
- load_reference(ctx.root) (pre-built, below) returns the case's ground truth,
  [{"id": "...", "question": "..."}, ...], or None when the case has none (then the
  checklist passes).

1. Ask Muse Spark (ctx.client.responses.create, JSON output) to mark each reference item
   covered or not by some agent item, even if worded differently, and to write feedback.
2. score = covered reference items / all reference items; passed = every one is covered.
3. feedback: what kind of question the checklist is missing, and any item that only
   restates background. It goes to the agent, so it must point to the direction only:
   never quote, paraphrase, or count the reference items. Empty when it passes.

Only passed and feedback reach the agent; the score is shown in the console.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from agent_kit.settings import case_dir

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


def run_verification(ctx, items: list) -> dict:
    raise NotImplementedError("verification/verify_checklist.py is not implemented yet")
