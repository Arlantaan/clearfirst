"""Pre-built kit: document text, the case record, progress, and the tools. These pass from
the start and must keep passing."""

from __future__ import annotations

import json
import os
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from agent_kit import case_record, document_text, tools
from agent_kit.case_record import CaseError, CaseRecord
from agent_kit.progress import load_progress, new_run, resume, save_progress
from agent_kit.tools import check_signatures
from agent_kit.tools.analyze_document import analyze
from tests import support
from tests.fake_model import Refused


def call(name: str, args: dict | None = None, call_id: str = "c1") -> dict:
    return {
        "type": "function_call",
        "name": name,
        "arguments": json.dumps(args or {}),
        "call_id": call_id,
    }


class KitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root, tmp = support.make_root()
        self.addCleanup(tmp.cleanup)
        self.fake = support.scripted(self.root, [])
        self.client = self.fake.client
        self.run_id = new_run(
            self.root, instructions="i", objective="o", verification=False
        )

    def read(self, ids: list, request: str = "status") -> dict:
        return analyze(self.client, self.root, ids, request)

    def case(self) -> CaseRecord:
        case = CaseRecord(self.root, self.run_id)
        case.set_checklist(support.CHECKLIST_ITEMS)
        return case

    def tool(self, name: str, args: dict | None = None, run_id: str = "") -> dict:
        return tools.run(
            self.client, self.root, run_id or self.run_id, call(name, args)
        )

    # ---- document text and reading --------------------------------------------------
    def test_inbox_lists_only_released_documents(self) -> None:
        ids = [d["id"] for d in document_text.list_documents(self.root)]
        self.assertEqual(sorted(support.INITIAL), sorted(ids))
        with self.assertRaises(document_text.DocumentError):
            document_text.get_document(self.root, "DOC-DRAFT")

    def test_text_is_extracted_once_and_reused(self) -> None:
        self.read(["DOC-REPORT"])
        self.read(["DOC-REPORT"], "a different request")
        extractions = [
            c
            for c in self.fake.calls
            if c[0] == "respond" and "Transcribe document" in json.dumps(c[1])
        ]
        self.assertEqual(1, len(extractions))
        self.assertEqual(1, len([c for c in self.fake.calls if c[0] == "upload"]))

    def test_reading_marks_quotes_verified_against_saved_text(self) -> None:
        record = self.read(["DOC-MINUTES"], "who said it was ready")["documents"][0][
            "evidence"
        ][0]
        self.assertTrue(record["verified"])

    def test_documents_are_read_in_parallel_in_order(self) -> None:
        state, lock, original = (
            {"now": 0, "max": 0},
            threading.Lock(),
            self.fake.responder,
        )

        def slow(kind, payload):
            with lock:
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
            time.sleep(0.1)
            try:
                return original(kind, payload)
            finally:
                with lock:
                    state["now"] -= 1

        self.fake.responder = slow
        ids = ["DOC-REPORT", "DOC-MINUTES", "DOC-DECLARATION", "DOC-REF"]
        self.assertEqual(ids, [d["document_id"] for d in self.read(ids)["documents"]])
        self.assertEqual(4, state["max"])

    def test_one_failing_document_does_not_sink_the_others(self) -> None:
        original = self.fake.responder

        def broken(kind, payload):
            if kind == "respond" and "DOC-DECLARATION" in json.dumps(payload):
                raise Refused("simulated outage")
            return original(kind, payload)

        self.fake.responder = broken
        by_id = {
            d["document_id"]: d
            for d in self.read(["DOC-REPORT", "DOC-DECLARATION"])["documents"]
        }
        self.assertTrue(by_id["DOC-REPORT"]["evidence"])
        self.assertIn("simulated outage", by_id["DOC-DECLARATION"]["note"])
        with self.assertRaises(document_text.DocumentError):
            self.read(["DOC-REPORT", "DOC-NOPE"])

    # ---- the case record -------------------------------------------------------------
    def test_record_fact_refuses_an_invented_quote_and_reports_progress(self) -> None:
        self.read(["DOC-REPORT"])
        case = self.case()
        with self.assertRaisesRegex(CaseError, "quote not found"):
            case.record_fact(
                "not_ready", "DOC-REPORT", 1, "The system was fully ready.", "claim"
            )
        fact = case.record_fact(
            "not_ready", "DOC-REPORT", 1, "Open Severity 1 defects: 21", "21 Sev-1 open"
        )
        self.assertEqual("proven", case.data["checklist"]["not_ready"]["status"])
        self.assertIn("timing", fact["progress"]["summary"])

    def test_limits_six_facts_per_item_and_three_citations(self) -> None:
        self.read(["DOC-REPORT", "DOC-MINUTES"])
        case = self.case()
        for _ in range(case_record.MAX_FACTS_PER_ITEM):
            case.record_fact(
                "not_ready", "DOC-REPORT", 1, "Overall status is green", "x"
            )
        with self.assertRaisesRegex(case_record.FactLimitError, "already has 6 facts"):
            case.record_fact(
                "not_ready", "DOC-REPORT", 1, "Overall status is green", "x"
            )
        args = support.cited_declaration()
        args["items"][0]["citations"] = [dict(support.CITE)] * 4
        with self.assertRaisesRegex(CaseError, "cites 4 quotes"):
            case.file_declaration(args, "unverified")

    def test_flagged_document_withdraws_and_blocks_facts(self) -> None:
        self.read(["DOC-DECLARATION"])
        case = self.case()
        case.record_fact(
            "counterevidence",
            "DOC-DECLARATION",
            1,
            "Broker work product for the review team",
            "c",
        )
        case.flag_excluded("DOC-DECLARATION", "broker work product")
        self.assertEqual([], case.data["facts"])
        with self.assertRaisesRegex(CaseError, "confidential"):
            case.record_fact(
                "counterevidence",
                "DOC-DECLARATION",
                1,
                "Broker work product for the review team",
                "c",
            )

    def test_set_checklist_validates_and_keeps_items_with_facts(self) -> None:
        case = CaseRecord(self.root, self.run_id)
        with self.assertRaisesRegex(CaseError, "snake_case"):
            case.set_checklist([support.checklist_item("Has Spaces")])
        self.read(["DOC-REPORT"])
        case.set_checklist([support.checklist_item("not_ready")])
        case.record_fact(
            "not_ready", "DOC-REPORT", 1, "Open Severity 1 defects: 21", "c"
        )
        with self.assertRaisesRegex(CaseError, "keep the items"):
            case.set_checklist([support.checklist_item("timing")])

    def test_sam_boxes_parse(self) -> None:
        boxes = check_signatures.parse_boxes(
            "<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=20|><|mask;x=0;y=0;data=2,2,~ab|>,1<|box;x1=5;y1=6;x2=7;y2=8;w=10;h=20|><|mask;x=0;y=0;data=2,2,!c|>"
        )
        self.assertEqual([0, 1], [b["ordinal"] for b in boxes])
        self.assertEqual([], check_signatures.parse_boxes(""))

    # ---- progress and resume ---------------------------------------------------------
    def test_progress_saves_status_and_notes(self) -> None:
        save_progress(
            self.root,
            self.run_id,
            [{"role": "user", "content": "o"}],
            status="paused",
            note="x",
        )
        progress = load_progress(self.root, self.run_id)
        self.assertEqual(
            ("paused", 0, "x"),
            (progress["status"], progress["turn"], progress["notes"]["note"]),
        )

    def test_resume_after_the_turn_limit_and_nothing_to_resume(self) -> None:
        save_progress(self.root, self.run_id, [], status="paused")
        self.assertIn("more turns", resume(self.root, self.run_id)["message"])
        save_progress(self.root, self.run_id, [], status="answered")
        step = resume(self.root, self.run_id)
        self.assertEqual((None, "answered"), (step["message"], step["status"]))

    # ---- the tools ------------------------------------------------------------------
    def test_tools_run_and_errors_come_back_to_the_model(self) -> None:
        self.assertEqual({"plan": ["a"]}, self.tool("update_plan", {"plan": ["a"]}))
        self.assertIn("DOC-REPORT", str(self.tool("list_documents")))
        self.assertIn(
            "set_checklist first", self.tool("record_fact", support.FACT[1])["error"]
        )
        self.assertIn("unknown tool", self.tool("request_evidence")["error"])
        bad = dict(call("update_plan"), arguments="{not json")
        self.assertIn(
            "not valid JSON",
            tools.run(self.client, self.root, self.run_id, bad)["error"],
        )

    def test_base_tools_without_verification_and_three_more_with_it(self) -> None:
        names = [t["name"] for t in tools.definitions(self.root, self.run_id)]
        self.assertEqual(tools.BASE_TOOLS, names)
        verified = new_run(
            self.root, instructions="i", objective="o", verification=True
        )
        names = [t["name"] for t in tools.definitions(self.root, verified)]
        self.assertEqual(
            ["flag_excluded", "request_evidence", "check_signatures"],
            names[len(tools.BASE_TOOLS) :],
        )

    def test_a_filed_declaration_ends_the_run_without_verification(self) -> None:
        result = self.tool("submit_declaration", support.DECLARATION[1])
        self.assertEqual(("answered", "unverified"), (result["status"], result["declaration"]))
        self.assertEqual(
            "unverified", CaseRecord(self.root, self.run_id).data["declaration"]["status"]
        )

    def test_cited_declaration_files_when_every_field_is_covered(self) -> None:
        self.read(["DOC-MINUTES"])
        case = self.case()
        record = case.file_declaration(support.cited_declaration(), "unverified")
        self.assertEqual("unverified", record["status"])
        args = support.cited_declaration()
        del args["header"]["citations"]["transport.bl_number"]
        args["discrepancies"] = [
            {
                "field": "transport.bl_number",
                "documents": ["DOC-REPORT", "DOC-MINUTES"],
                "detail": "B/L numbers differ.",
            }
        ]
        record = case.file_declaration(args, "unverified")
        self.assertEqual("unverified", record["status"])

    def test_filed_declaration_round_trips_header_values(self) -> None:
        self.read(["DOC-MINUTES"])
        case = self.case()
        record = case.file_declaration(support.cited_declaration(), "unverified")
        header = record["header"]
        self.assertEqual("SAD", header["declaration_type"])
        self.assertEqual("SE5566778899", header["importer"]["tin"])
        self.assertEqual("BL123456", header["transport"]["bl_number"])
        self.assertEqual(10000, header["valuation"]["invoice_total"])
        self.assertIn("importer.tin", header["citations"])

    def test_filed_declaration_stores_the_duty_estimate(self) -> None:
        self.read(["DOC-MINUTES"])
        case = self.case()
        args = support.cited_declaration()
        args["duty_estimate"] = {
            "customs_value_gmd": 100.0,
            "total_payable_gmd": 10.0,
        }
        record = case.file_declaration(args, "unverified")
        self.assertEqual(100.0, record["duty_estimate"]["customs_value_gmd"])

    def test_filed_declaration_refuses_a_non_object_duty_estimate(self) -> None:
        self.read(["DOC-MINUTES"])
        case = self.case()
        args = support.cited_declaration()
        args["duty_estimate"] = "GMD 10"
        with self.assertRaisesRegex(CaseError, "duty_estimate must be"):
            case.file_declaration(args, "unverified")

    def test_broker_declared_fields_take_no_citation(self) -> None:
        self.read(["DOC-MINUTES"])
        case = self.case()
        for field in ("procedure_code", "declaration_type"):
            args = support.cited_declaration()
            args["header"]["citations"][field] = [dict(support.CITE)]
            with self.assertRaisesRegex(
                CaseError, f"{field} is declared by the broker"
            ):
                case.file_declaration(args, "unverified")

    def test_declaration_tool_schema_is_strict_and_shows_where_values_go(self) -> None:
        from agent_kit.tools import submit_declaration

        header = submit_declaration.DEFINITION["parameters"]["properties"]["header"]
        self.assertFalse(header["additionalProperties"])
        for key in ("importer", "exporter", "transport", "valuation"):
            self.assertFalse(header["properties"][key]["additionalProperties"])
        self.assertIn("citations", header["properties"])
        self.assertIn("nested objects", header["description"])
        self.assertIn("importer.tin", submit_declaration.DEFINITION["description"])

    def test_flat_header_is_refused_naming_values_and_where_they_go(self) -> None:
        case = self.case()
        args = {
            "header": {
                "importer.name": [dict(support.CITE)],
                "exporter.country": [dict(support.CITE)],
            },
            "items": [],
            "discrepancies": [],
            "open_questions": [],
        }
        with self.assertRaisesRegex(
            CaseError, "missing header values for: .*exporter\\.country"
        ):
            case.file_declaration(args, "unverified")
        with self.assertRaisesRegex(CaseError, "citations under header\\.citations"):
            case.file_declaration(args, "unverified")

    def test_declaration_refuses_missing_fields_bad_quotes_and_excluded_docs(
        self,
    ) -> None:
        self.read(["DOC-MINUTES"])
        case = self.case()
        with self.assertRaisesRegex(CaseError, "importer\\.tin"):
            case.file_declaration(
                {
                    "header": support.header_values(),
                    "items": [],
                    "discrepancies": [],
                    "open_questions": [],
                },
                "unverified",
            )
        with self.assertRaisesRegex(CaseError, r"items\[0\]\.gross_kg"):
            case.file_declaration(
                {
                    "header": support.header_values(),
                    "items": [{}],
                    "discrepancies": [],
                    "open_questions": list(case_record.HEADER_FIELDS),
                },
                "unverified",
            )
        args = support.cited_declaration()
        del args["header"]["importer"]["tin"]
        with self.assertRaisesRegex(CaseError, "missing header values for.*importer\\.tin"):
            case.file_declaration(args, "unverified")
        args = support.cited_declaration()
        args["header"]["citations"]["importer.tin"][0]["quote"] = (
            "The vendor admitted it was broken"
        )
        with self.assertRaisesRegex(CaseError, "quote not found"):
            case.file_declaration(args, "unverified")
        args = support.cited_declaration()
        args["items"][0]["citations"] = [
            {
                "document_id": "DOC-DECLARATION",
                "page": 1,
                "quote": "Broker work product for the review team",
            }
        ]
        case.flag_excluded("DOC-DECLARATION", "broker work product")
        with self.assertRaisesRegex(CaseError, "confidential"):
            case.file_declaration(args, "unverified")

    def test_documents_read_are_remembered(self) -> None:
        self.tool("analyze_document", {"document_ids": ["DOC-REPORT"], "request": "x"})
        self.assertEqual(
            ["DOC-REPORT"], CaseRecord(self.root, self.run_id).data["read_ids"]
        )

    def test_a_check_that_is_not_built_yet_pauses_the_run(self) -> None:
        run_id = new_run(self.root, instructions="i", objective="o", verification=True)
        with mock.patch(
            "agent_kit.tools.set_checklist.importlib.import_module",
            side_effect=NotImplementedError("not implemented yet"),
        ):
            result = self.tool(
                "set_checklist", {"items": support.CHECKLIST_ITEMS}, run_id
            )
        self.assertEqual(
            ("not implemented yet", "paused"), (result["error"], result["status"])
        )

    def test_check_signatures_segments_crops_and_records_the_verdict(self) -> None:
        run_id = new_run(self.root, instructions="i", objective="o", verification=True)
        args = {"document_id": "DOC-REF", "page": 1, "signer": "Dana Okafor"}
        same = dict(args, reference_document_id="DOC-REF", reference_page=1)
        self.assertIn(
            "different page", self.tool("check_signatures", same, run_id)["error"]
        )
        support.release(self.root)
        pages = self.root / "workspace/inbox/pages"
        for doc_id in ("DOC-REF", "DOC-CERT"):
            Image.new("RGB", (200, 120), "white").save(pages / f"{doc_id}-p1.png")
        seen = {}

        def verdict(text: str) -> dict:
            seen["text"] = text
            return {"consistent": True, "confidence": 0.8, "reason": "same slant"}

        self.fake = support.scripted(self.root, [], verdict=verdict)
        self.client = self.fake.client
        other = dict(args, reference_document_id="DOC-CERT", reference_page=1)
        result = self.tool("check_signatures", other, run_id)
        self.assertEqual("consistent", result["verdict"])
        self.assertEqual(0.8, result["confidence"])
        self.assertIn("Dana Okafor", seen["text"])
        self.assertIn("DOC-REF", seen["text"])
        self.assertIn("DOC-CERT", seen["text"])
        self.assertEqual(
            ["segment", "segment", "respond"], [kind for kind, _ in self.fake.calls]
        )
        record = CaseRecord(self.root, run_id)
        check = record.data["signature_checks"][0]
        self.assertEqual(0.8, check["confidence"])
        self.assertTrue(check["boxes"])
        self.assertTrue(check["reference"]["boxes"])
        self.assertEqual([], record.data["flags"])
        self.fake = support.scripted(
            self.root,
            [],
            verdict=lambda text: {
                "consistent": True,
                "confidence": 0.2,
                "reason": "blurry",
            },
        )
        self.client = self.fake.client
        result = self.tool("check_signatures", other, run_id)
        self.assertEqual("inconsistent", result["verdict"])
        flags = CaseRecord(self.root, run_id).data["flags"]
        self.assertEqual(1, len(flags))
        self.assertEqual("signature", flags[0]["kind"])
        self.assertTrue(flags[0]["reason"].startswith("inconsistent"))
        result = self.tool(
            "check_signatures",
            dict(args, reference_document_id="DOC-DECLARATION", reference_page=1),
            run_id,
        )
        self.assertEqual("no_signature_found", result["verdict"])
        flags = CaseRecord(self.root, run_id).data["flags"]
        self.assertEqual(2, len(flags))
        self.assertTrue(flags[1]["reason"].startswith("no_signature_found"))

    # ---- pre-built checks ------------------------------------------------------------
    def ctx(self) -> tools.Context:
        return tools.Context(
            self.client,
            self.root,
            self.run_id,
            CaseRecord(self.root, self.run_id),
            True,
        )

    def test_verify_claims_reports_unsupported_fields(self) -> None:
        from verification import verify_claims

        declaration = support.cited_declaration()
        self.assertEqual(
            {"passed": True, "feedback": [], "unsupported": []},
            verify_claims.run_verification(self.ctx(), declaration),
        )
        fake = support.scripted(
            self.root,
            [],
            unsupported=lambda text: [
                {"field": "importer.name", "reason": "off topic"}
            ],
        )
        ctx = tools.Context(
            fake.client,
            self.root,
            self.run_id,
            CaseRecord(self.root, self.run_id),
            True,
        )
        result = verify_claims.run_verification(ctx, declaration)
        self.assertFalse(result["passed"])
        self.assertIn("importer.name", result["feedback"][0])
        self.assertIn("quotes do not support it", result["feedback"][0])

    def test_claims_check_states_equivalences_and_skips_hs_justification(self) -> None:
        from verification import verify_claims

        declaration = support.cited_declaration()
        seen = {}

        def capture(text):
            seen["text"] = text
            return []

        fake = support.scripted(self.root, [], unsupported=capture)
        ctx = tools.Context(
            fake.client,
            self.root,
            self.run_id,
            CaseRecord(self.root, self.run_id),
            True,
        )
        result = verify_claims.run_verification(ctx, declaration)
        self.assertTrue(result["passed"])
        self.assertIn("TURKIYE", seen["text"])
        self.assertIn("importer.name", seen["text"])
        self.assertNotIn("hs_code", seen["text"])
        self.assertNotIn("importer.tin", seen["text"])
        self.assertNotIn("hs_justification", seen["text"])

    def test_declaration_refusals_reset_when_a_request_is_answered(self) -> None:
        case = self.case()
        case.set_checklist(support.CHECKLIST_ITEMS)
        case.record_declaration_check("declaration", ["bad"])
        case.record_declaration_check("declaration", ["bad"])
        self.assertEqual(2, case.declaration_refusals())
        case.open_request("timing", "the draft assessment", "missing_evidence", ["DOC-REPORT"])
        case.answer_request("R1", "here it is")
        self.assertEqual(0, case.declaration_refusals())
        case.record_declaration_check("declaration", ["bad"])
        self.assertEqual(1, case.declaration_refusals())
        case.record_declaration_check("claims", ["bad"])
        self.assertEqual(1, case.declaration_refusals())

    def test_verify_evidence_request(self) -> None:
        from verification import verify_evidence_request

        self.read(["DOC-REPORT"])
        case = self.case()
        case.mark_read(["DOC-REPORT"])
        result = verify_evidence_request.run_verification(
            self.ctx(), {"item": "timing", "need": "x"}
        )
        self.assertFalse(result["passed"])
        self.assertIn("DOC-MINUTES", result["feedback"])
        case.mark_read(list(support.INITIAL))
        self.assertTrue(
            verify_evidence_request.run_verification(
                self.ctx(), {"item": "timing", "need": "x"}
            )["passed"]
        )
        case.record_fact(
            "not_ready", "DOC-REPORT", 1, "Open Severity 1 defects: 21", "c"
        )
        result = verify_evidence_request.run_verification(
            self.ctx(), {"item": "not_ready", "need": "x"}
        )
        self.assertIn("already proven", result["feedback"])


class TariffToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root, tmp = support.make_root()
        self.addCleanup(tmp.cleanup)
        self.fake = support.scripted(self.root, [])
        self.client = self.fake.client
        self.run_id = new_run(
            self.root, instructions="i", objective="o", verification=False
        )
        self._tariff_dir = os.environ.get("TARIFF_DIR")
        os.environ["TARIFF_DIR"] = str(
            Path(support.__file__).resolve().parents[2] / "tariff"
        )

    def tearDown(self) -> None:
        if self._tariff_dir is None:
            os.environ.pop("TARIFF_DIR", None)
        else:
            os.environ["TARIFF_DIR"] = self._tariff_dir

    def test_lookup_tariff_finds_the_schedule_line(self) -> None:
        result = tools.run(
            self.client,
            self.root,
            self.run_id,
            call("lookup_tariff", {"hs_code": "6907.21.00"}),
        )
        self.assertEqual(
            ("6907.21", 20.0, 15.0),
            (result["hs"], result["duty_pct"], result["vat_pct"]),
        )
        self.assertIn("porcelain", result["description"])

    def test_lookup_tariff_offers_nearest_headings_when_missing(self) -> None:
        result = tools.run(
            self.client,
            self.root,
            self.run_id,
            call("lookup_tariff", {"hs_code": "9999.99"}),
        )
        self.assertEqual("not in pack", result["message"])
        self.assertEqual(3, len(result["nearest"]))
        self.assertEqual("9403.60", result["nearest"][0]["hs"])

    def test_compute_duty_matches_the_worked_example(self) -> None:
        result = tools.run(
            self.client,
            self.root,
            self.run_id,
            call(
                "compute_duty",
                {
                    "currency": "USD",
                    "invoice_total": 21000,
                    "hs_code": "6809.19.00",
                },
            ),
        )
        self.assertEqual(1508430.00, result["customs_value_gmd"])
        self.assertAlmostEqual(48269.76, result["total_payable_gmd"], delta=1)
        self.assertEqual(
            ["IDF", "PRF", "AUL", "ECL", "GNSW", "VAT"],
            [levy["code"] for levy in result["levies"]],
        )
        self.assertEqual(71.83, result["rates_used"]["exchange_rate"])

    def test_compute_duty_refuses_an_unknown_currency(self) -> None:
        result = tools.run(
            self.client,
            self.root,
            self.run_id,
            call(
                "compute_duty",
                {"currency": "XXX", "invoice_total": 100, "hs_code": "6809.19.00"},
            ),
        )
        self.assertIn("no XXX rate", result["error"])


if __name__ == "__main__":
    unittest.main()
