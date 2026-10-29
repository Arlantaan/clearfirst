"""compute_duty: the duty estimate for a shipment from the tariff pack (pure code).

customs_value_gmd is invoice_total x the pack's exchange rate. Each levy in the
pack applies in order on its basis (customs_value, or customs_value_plus_duty
for VAT); the total is the rounded lines added up. File the result with the
declaration as duty_estimate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..tariff import heading, load_pack, nearest_lines, schedule_line

if TYPE_CHECKING:
    from . import Context

BASES = ("customs_value", "customs_value_plus_duty")

DEFINITION = {
    "type": "function",
    "name": "compute_duty",
    "description": "Compute the duty estimate from the country tariff pack: "
    "customs value in GMD (invoice total x exchange rate), each levy in order "
    "with its amount, VAT on customs value plus import duty, and the total "
    "payable. Call it before filing and attach the result as duty_estimate.",
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "currency": {"type": "string"},
            "invoice_total": {"type": "number"},
            "hs_code": {"type": "string"},
        },
        "required": ["currency", "invoice_total", "hs_code"],
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
