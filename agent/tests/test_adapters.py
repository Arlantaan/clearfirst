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


class MultiLineDutyTest(unittest.TestCase):
    """Per-line duty rows in the PDF and XML for a multi-line estimate."""

    def estimate(self) -> dict:
        from types import SimpleNamespace

        from agent_kit.tools import compute_duty

        ctx = SimpleNamespace(
            root=ROOT / "agent",
            case=SimpleNamespace(data={"facts": [{"quote": "total USD 21,000"}]}),
        )
        return compute_duty.run(
            ctx,
            {
                "currency": "USD",
                "invoice_total": 21000,
                "items": [
                    {"hs_code": "6809.19.00", "value": 10000},
                    {"hs_code": "1006.30", "value": 11000},
                ],
            },
        )

    def test_pdf_duty_box_names_each_line(self) -> None:
        declaration = {
            "header": {},
            "items": [],
            "discrepancies": [],
            "open_questions": [],
            "duty_estimate": self.estimate(),
        }
        taxes = dict(
            (box, value) for box, _, value in sad_pdf._duty_rows(declaration)
        )["47"]
        self.assertIn("IDF 20% line 1 (HS 6809.19)", taxes)
        self.assertIn("VAT 0% line 2 (HS 1006.30)", taxes)
        self.assertIn("PRF 1.5%:", taxes)
        pdf = sad_pdf.render(declaration, "")
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_xml_tax_lines_carry_item_lines(self) -> None:
        declaration = {
            "header": {},
            "items": [],
            "discrepancies": [],
            "open_questions": [],
            "duty_estimate": self.estimate(),
        }
        root = ElementTree.fromstring(sad_xml.render(declaration))
        lines = root.findall("./tax/line")
        first = [line for line in lines if line.get("code") == "IDF"][0]
        self.assertEqual(
            ("1", "6809.19"), (first.get("item_line"), first.get("hs"))
        )
        fixed = [line for line in lines if line.get("code") == "PRF"][0]
        self.assertIsNone(fixed.get("item_line"))


if __name__ == "__main__":
    unittest.main()
