"""ASYCUDA World mapping (stub): SAD box number -> ASYCUDA data element name.

The element names are drafts from the SAD layout; confirm them against the
DTI message specification before use. build_asycuda_payload raises until
DTI access lands, so the door stays visible.
"""

FIELD_MAP = {
    "1": "Declaration.Type",
    "2": "Trader.Exporter",
    "8": "Trader.Consignee",
    "14": "Trader.Declarant",
    "18": "Transport.Vessel",
    "19": "Transport.Container",
    "20": "Valuation.Incoterm",
    "22": "Valuation.CurrencyAndTotal",
    "25": "Transport.ModeAtBorder",
    "29": "Declaration.OfficeOfEntry",
    "31": "Item.PackagesAndDescription",
    "33": "Item.HSCode",
    "34": "Item.Origin",
    "35": "Item.GrossMass",
    "38": "Item.NetMass",
    "41": "Item.SupplementaryUnits",
    "42": "Item.Price",
    "46": "Declaration.StatisticalValue",
    "47": "Declaration.Taxes",
}


def build_asycuda_payload(declaration: dict) -> dict:
    """Map the declaration to an ASYCUDA World SAD payload (not yet available)."""
    raise NotImplementedError("pending ASYCUDA DTI access")
