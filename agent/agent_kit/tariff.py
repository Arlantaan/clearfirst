"""Country tariff packs: exchange rates, levies, and the HS schedule.

One JSON file per country in the tariff folder (TARIFF_DIR, default ../tariff
next to the agent folder), named <pack>.json. The pack is chosen by
COUNTRY_PACK (settings.country_pack, default gm).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .settings import country_pack


def tariff_dir(root: Path) -> Path:
    folder = Path(os.environ.get("TARIFF_DIR") or "../tariff").expanduser()
    if not folder.is_absolute():
        folder = (Path(root) / folder).resolve()
    return folder


def load_pack(root: Path, pack: str | None = None) -> dict:
    """The country's tariff pack (exchange_rates, levies, hs_schedule)."""
    name = pack or country_pack()
    path = tariff_dir(root) / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"tariff pack not found: {path}")
    return json.loads(path.read_text())


def heading(hs_code: str) -> str:
    """The 6-digit heading: 6809.19.00 -> 680919."""
    digits = "".join(c for c in str(hs_code or "") if c.isdigit())
    if len(digits) < 6:
        raise ValueError(f"{hs_code!r} is not an HS code (need at least 6 digits)")
    return digits[:6]


def schedule_line(pack: dict, hs_code: str) -> dict | None:
    """The hs_schedule entry for the code's 6-digit prefix, if the pack has it."""
    want = heading(hs_code)
    return next(
        (
            line
            for line in pack.get("hs_schedule") or []
            if heading(line.get("hs")) == want
        ),
        None,
    )


def nearest_lines(pack: dict, hs_code: str, count: int = 3) -> list:
    """The closest schedule lines by heading number, for codes missing from the pack."""
    want = int(heading(hs_code))
    lines = [line for line in pack.get("hs_schedule") or [] if line.get("hs")]
    lines.sort(key=lambda line: abs(int(heading(line["hs"])) - want))
    return lines[:count]
