"""Page images: 100 dpi PNG renders of shipment documents.

One <ID>-p<n>.png per page, next to the documents in a pages/ folder.
check_signatures sends these to SAM; the console shows them and uses render()
for newly uploaded shipments. Requires pdftoppm and pdfinfo for PDFs.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

DPI = 100


def pages_of(pdf: Path) -> int:
    info = subprocess.run(
        ["pdfinfo", str(pdf)], capture_output=True, text=True, check=True
    ).stdout
    match = re.search(r"Pages:\s+(\d+)", info)
    if match is None:
        raise RuntimeError(f"pdfinfo reported no page count for {pdf}")
    return int(match.group(1))


def render(doc: Path, out_dir: Path) -> int:
    """Render doc into out_dir as <stem>-p<n>.png. Returns the page count."""
    out_dir.mkdir(exist_ok=True)
    stem = doc.stem
    for old in out_dir.glob(f"{stem}-*.png"):
        old.unlink()
    if doc.suffix.lower() == ".pdf":
        subprocess.run(
            [
                "pdftoppm",
                "-r",
                str(DPI),
                "-gray",
                "-png",
                str(doc),
                str(out_dir / f"{stem}-render"),
            ],
            check=True,
        )
        # pdftoppm writes <prefix>-1.png or <prefix>-01.png; normalise to <ID>-p1.png.
        for png in out_dir.glob(f"{stem}-render-*.png"):
            n = int(png.stem.rsplit("-", 1)[1])
            png.rename(out_dir / f"{stem}-p{n}.png")
        return pages_of(doc)
    (out_dir / f"{stem}-p1.png").write_bytes(
        subprocess.run(
            [
                "python3",
                "-c",
                "import sys;from PIL import Image;im=Image.open(sys.argv[1]).convert('L');im.thumbnail((1100,1100));im.save(sys.stdout.buffer,'PNG')",
                str(doc),
            ],
            capture_output=True,
            check=True,
        ).stdout
    )
    return 1
