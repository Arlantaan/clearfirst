"""The exporters: the signed-off run in the workspace renders as PDF and XML."""

import json
import re
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
WORKSPACE = ROOT / "agent" / "workspace"

from adapters import asycuda_stub, sad_pdf, sad_xml  # noqa: E402


def signed_off() -> tuple:
    """The latest signed-off (run_id, declaration) in the workspace, if any."""
    found = []
    for path in sorted((WORKSPACE / "case_records").glob("run-*.json")):
        declaration = json.loads(path.read_text()).get("declaration") or {}
        if declaration.get("status") == "approved":
            found.append((path.stem, declaration))
    return found[-1] if found else (None, None)


RUN_ID, DECLARATION = signed_off()


def objective_text() -> str:
    """The run's case objective (drives the FICTIONAL DEMO watermark)."""
    try:
        mapping = json.loads((WORKSPACE / "console_runs.json").read_text())
        objective = ROOT / "cases" / mapping[RUN_ID] / "objective.md"
        return objective.read_text(errors="replace")
    except (OSError, ValueError, KeyError):
        return ""


@unittest.skipUnless(RUN_ID, "no signed-off run in the workspace")
class ExportTest(unittest.TestCase):
    def test_pdf_has_two_pages(self) -> None:
        pdf = sad_pdf.render(DECLARATION, objective_text())
        self.assertTrue(pdf.startswith(b"%PDF"))
        pages = len(re.findall(rb"/Type\s*/Page(?!s)", pdf))
        self.assertEqual(2, pages)

    def test_xml_parses_with_the_declaration_items(self) -> None:
        root = ElementTree.fromstring(sad_xml.render(DECLARATION))
        self.assertEqual(len(DECLARATION["items"]), len(root.findall("./items/item")))
        self.assertTrue(all(box.get("number") for box in root.findall(".//box")))

    def test_asycuda_stub_shows_the_door(self) -> None:
        self.assertIn("33", asycuda_stub.FIELD_MAP)
        with self.assertRaisesRegex(NotImplementedError, "pending ASYCUDA DTI access"):
            asycuda_stub.build_asycuda_payload(DECLARATION)


if __name__ == "__main__":
    unittest.main()
