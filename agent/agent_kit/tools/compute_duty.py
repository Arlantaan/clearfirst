"""compute_duty: the duty estimate for a shipment from the tariff pack (pure code).

customs_value_gmd is invoice_total x the pack's exchange rate. Each levy in the
pack applies in order on its basis (customs_value, or customs_value_plus_duty
for VAT); the total is the rounded lines added up. File the result with the
declaration as duty_estimate.

With items [{hs_code, value}], import duty and VAT are computed per line from
each line's tariff rate while the fixed levies apply on the total customs
value; the result carries per-line rows plus the totals.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ..tariff import heading, load_pack, nearest_lines, schedule_line

if TYPE_CHECKING:
    from . import Context

BASES = ("customs_value", "customs_value_plus_duty")
QUOTED_NUMBER = re.compile(r"\d[\d,]*\.?\d*")

DEFINITION = {
    "type": "function",
    "name": "compute_duty",
    "description": "Compute the duty estimate from the country tariff pack: "
    "customs value in GMD (invoice total x exchange rate), each levy in order "
    "with its amount, VAT on customs value plus import duty, and the total "
    "payable. The invoice total must be quoted in a recorded fact. Pass items "
    "[{hs_code, value}] (one per declaration line) for multi-line declarations "
    "instead of a single hs_code; the values must sum to the invoice total. "
    "Call it before filing and attach the result as duty_estimate.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "currency": {"type": "string"},
            "invoice_total": {"type": "number"},
            "hs_code": {"type": "string"},
            "items": {
                "type": "array",
                "description": "one {hs_code, value} per declaration line",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "hs_code": {"type": "string"},
                        "value": {"type": "number"},
                    },
                    "required": ["hs_code", "value"],
                },
            },
        },
        "required": ["currency", "invoice_total"],
    },
}


def run(ctx: Context, args: dict) -> dict:
    pack = load_pack(ctx.root)
    currency = str(args.get("currency") or "").upper()
    rates = {
        code: rate
        for code, rate in (pack.get("exchange_rates") or {}).items()
        if isinstance(rate, (int, float))
    }
    if currency not in rates:
        raise ValueError(
            f"no {currency or 'currency'} rate in the pack "
            f"(have: {', '.join(sorted(rates))})"
        )
    try:
        total = float(args.get("invoice_total"))
    except (TypeError, ValueError):
        raise ValueError("invoice_total must be a number") from None
    if total <= 0:
        raise ValueError("invoice_total must be positive")
    quoted = []
    for fact in ctx.case.data["facts"]:
        for match in QUOTED_NUMBER.finditer(fact.get("quote", "")):
            try:
                quoted.append(float(match.group(0).replace(",", "")))
            except ValueError:
                continue
    if not any(abs(number - total) <= total * 0.005 for number in quoted):
        raise ValueError(
            f"invoice total {args.get('invoice_total')} is not quoted in any recorded fact"
        )
    if args.get("items") is not None:
        return _run_multi(pack, rates, currency, total, args.get("items"))
    hs_code = str(args.get("hs_code", ""))
    line = schedule_line(pack, heading(hs_code))
    if line is None:
        nearby = ", ".join(l.get("hs", "") for l in nearest_lines(pack, hs_code))
        raise ValueError(f"{hs_code} is not in pack (nearest: {nearby})")
    customs_value = round(total * rates[currency], 2)
    levies, duty = [], 0.0
    for levy in pack.get("levies") or []:
        basis = levy.get("basis")
        if basis not in BASES:
            raise ValueError(f"unknown levy basis in the pack: {basis!r}")
        pct = levy.get("rate_pct")
        if pct is None:
            pct = (
                line["vat_pct"]
                if basis == "customs_value_plus_duty"
                else line["duty_pct"]
            )
        base = customs_value + duty if basis == "customs_value_plus_duty" else customs_value
        amount = round(base * pct / 100, 2)
        levies.append(
            {
                "code": levy.get("code"),
                "name": levy.get("name"),
                "basis": basis,
                "rate_pct": pct,
                "amount": amount,
            }
        )
        if levy.get("rate_source") == "hs_schedule" and basis == "customs_value":
            duty = amount
    vat = next(
        l["amount"] for l in levies if l["basis"] == "customs_value_plus_duty"
    )
    return {
        "currency": currency,
        "invoice_total": total,
        "hs_code": hs_code,
        "hs": line.get("hs"),
        "customs_value_gmd": customs_value,
        "levies": levies,
        "vat_gmd": vat,
        "total_payable_gmd": round(sum(l["amount"] for l in levies), 2),
        "rates_used": {
            "exchange_rate": rates[currency],
            "duty_pct": line["duty_pct"],
            "vat_pct": line["vat_pct"],
        },
    }


def _run_multi(pack: dict, rates: dict, currency: str, total: float, items) -> dict:
    """Duty with per-line import duty and VAT; fixed levies on the total."""
    if not isinstance(items, list) or not items:
        raise ValueError("items must be a non-empty list of {hs_code, value}")
    specs = []
    for index, entry in enumerate(items):
        if not isinstance(entry, dict):
            raise ValueError(f"items[{index}] must be an object with hs_code and value")
        try:
            value = float(entry.get("value"))
        except (TypeError, ValueError):
            raise ValueError(f"items[{index}].value must be a number") from None
        if value <= 0:
            raise ValueError(f"items[{index}].value must be a positive number")
        hs = str(entry.get("hs_code", ""))
        sline = schedule_line(pack, heading(hs))
        if sline is None:
            nearby = ", ".join(l.get("hs", "") for l in nearest_lines(pack, hs))
            raise ValueError(f"{hs} is not in pack (nearest: {nearby})")
        specs.append((hs, sline, value))
    items_sum = sum(value for _, _, value in specs)
    if abs(items_sum - total) > abs(total) * 0.005:
        raise ValueError(f"item values sum to {items_sum:g} but invoice_total is {total:g}")
    rate = rates[currency]
    customs_total = round(total * rate, 2)
    levies = pack.get("levies") or []
    for levy in levies:
        if levy.get("basis") not in BASES:
            raise ValueError(f"unknown levy basis in the pack: {levy.get('basis')!r}")
    per_line = []
    for hs, sline, value in specs:
        line_customs = round(value * rate, 2)
        duty = 0.0
        for levy in levies:
            if levy.get("rate_pct") is None and levy.get("basis") == "customs_value":
                duty = round(line_customs * sline["duty_pct"] / 100, 2)
        per_line.append(
            {
                "hs": hs,
                "schedule": sline,
                "value": value,
                "customs": line_customs,
                "duty": duty,
            }
        )
    total_duty = sum(info["duty"] for info in per_line)
    rows, line_vats = [], {}
    for levy in levies:
        basis, pct = levy.get("basis"), levy.get("rate_pct")
        if pct is None:
            for number, info in enumerate(per_line, 1):
                line_pct = (
                    info["schedule"]["vat_pct"]
                    if basis == "customs_value_plus_duty"
                    else info["schedule"]["duty_pct"]
                )
                base = (
                    info["customs"] + info["duty"]
                    if basis == "customs_value_plus_duty"
                    else info["customs"]
                )
                amount = round(base * line_pct / 100, 2)
                rows.append(
                    {
                        "code": levy.get("code"),
                        "name": levy.get("name"),
                        "basis": basis,
                        "rate_pct": line_pct,
                        "amount": amount,
                        "line": number,
                        "hs": info["schedule"].get("hs"),
                    }
                )
                if basis == "customs_value_plus_duty":
                    line_vats[number] = line_vats.get(number, 0.0) + amount
        else:
            base = (
                customs_total + total_duty
                if basis == "customs_value_plus_duty"
                else customs_total
            )
            rows.append(
                {
                    "code": levy.get("code"),
                    "name": levy.get("name"),
                    "basis": basis,
                    "rate_pct": pct,
                    "amount": round(base * pct / 100, 2),
                }
            )
    return {
        "currency": currency,
        "invoice_total": total,
        "customs_value_gmd": customs_total,
        "levies": rows,
        "lines": [
            {
                "line": number,
                "hs_code": info["hs"],
                "hs": info["schedule"].get("hs"),
                "value": info["value"],
                "customs_value_gmd": info["customs"],
                "duty_gmd": info["duty"],
                "vat_gmd": line_vats.get(number, 0.0),
            }
            for number, info in enumerate(per_line, 1)
        ],
        "vat_gmd": round(sum(line_vats.values()), 2),
        "total_payable_gmd": round(sum(row["amount"] for row in rows), 2),
        "rates_used": {"exchange_rate": rate},
    }
