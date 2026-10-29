"""flag_excluded (verification on): flag a confidential lawyer-client document.

It is excluded: its facts are withdrawn, it cannot be read again or cited, and the
broker reviews the flags at declaration sign-off.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import Context

DEFINITION = {
    "type": "function",
    "name": "flag_excluded",
    "description": "Flag a confidential lawyer-client document (Confidential Doc/Info). It is excluded and can "
    "never be cited. The broker reviews flags at declaration sign-off.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"document_id": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["document_id", "reason"],
    },
}


def run(ctx: Context, args: dict) -> dict:
    flag = ctx.case.flag_excluded(
        str(args.get("document_id", "")), str(args.get("reason", ""))
    )
    return {"flagged": flag}
