"""lookup_tariff: the tariff schedule line for an HS code (duty, VAT, CET band).

Looks up the code's 6-digit prefix in the country tariff pack. When the prefix
is not in the pack, the result says "not in pack" and offers the three nearest
headings so the agent can reconsider its classification.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..tariff import heading, load_pack, nearest_lines, schedule_line

if TYPE_CHECKING:
    from . import Context

DEFINITION = {
    "type": "function",
    "name": "lookup_tariff",
    "description": "Look up an HS code in the country tariff pack: the schedule "
    "line for its 6-digit prefix (description, duty_pct, vat_pct, cet_band), or "
    '"not in pack" with the three nearest headings. Call it after settling an '
    "HS code to confirm the code exists and get its rates.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"hs_code": {"type": "string"}},
        "required": ["hs_code"],
    },
}


def _line(line: dict) -> dict:
    return {
        "hs": line.get("hs"),
        "description": line.get("description"),
        "duty_pct": line.get("duty_pct"),
        "vat_pct": line.get("vat_pct"),
        "cet_band": line.get("cet_band"),
    }


def run(ctx: Context, args: dict) -> dict:
    pack = load_pack(ctx.root)
    hs_code = str(args.get("hs_code", ""))
    line = schedule_line(pack, heading(hs_code))
    if line is not None:
        return {"hs_code": hs_code, **_line(line)}
    return {
        "hs_code": hs_code,
        "message": "not in pack",
        "nearest": [_line(line) for line in nearest_lines(pack, hs_code)],
    }
