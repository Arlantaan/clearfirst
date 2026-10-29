"""The verification layer (VERIFICATION=on): the checks you build in agent/verification/
(verify_checklist.py, verify_declaration.py), and the tools running them inside a real run of the agent loop,
with escalation, resume, broker sign-off, ./helper verify, and continuing from a checklist."""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from agent_kit import tools
from agent_kit.case_record import CaseRecord
from agent_kit.progress import branch, new_run
from agent_kit.settings import verification_enabled
from scripts import verify
from tests import support


ALL_INITIAL = list(support.INITIAL)
READ_ALL = (
    "analyze_document",
    {"document_ids": ALL_INITIAL, "request": "invoice, packing, transport and signatures"},
)
FLAG = (
    "flag_excluded",
    {"document_id": "DOC-DECLARATION", "reason": "broker work product"},
)
FACTS = [
    (
        "record_fact",
        {
            "item": "importer",
            "document_id": "DOC-MINUTES",
            "page": 1,
            "quote": "Mr. Lindgren confirmed the system is ready for go-live",
            "claim": "importer confirmed",
        },
    ),
    (
        "record_fact",
        {
            "item": "exporter_origin",
            "document_id": "DOC-MINUTES",
            "page": 1,
            "quote": "Erik Lindgren, Engagement Partner",
            "claim": "exporter named",
        },
    ),
    (
        "record_fact",
        {
            "item": "goods",
            "document_id": "DOC-REPORT",
            "page": 1,
            "quote": "Weekly status report",
            "claim": "goods described",
        },
    ),
    (
        "record_fact",
        {
            "item": "valuation",
            "document_id": "DOC-REPORT",
            "page": 1,
            "quote": "Overall status is green",
            "claim": "value stated",
        },
    ),
]
ASK = (
    "request_evidence",
    {
        "item": "transport",
        "need": "Vessel, B/L number, container and port details for the shipment.",
    },
)
AFTER_RELEASE = [
    (
        "analyze_document",
        {
            "document_ids": ["DOC-DRAFT", "DOC-CERT"],
            "request": "arrival documents and who signed",
        },
    ),
    (
        "record_fact",
        {
            "item": "transport",
            "document_id": "DOC-CERT",
            "page": 1,
            "quote": "UAT Phase 2 exit certification",
            "claim": "transport certified",
        },
    ),
    (
        "check_signatures",
        {
            "document_id": "DOC-CERT",
            "page": 1,
            "signer": "Dana Okafor",
            "reference_document_id": "DOC-REF",
            "reference_page": 1,
        },
    ),
    (
        "record_fact",
        {
            "item": "signatures",
            "document_id": "DOC-CERT",
            "page": 1,
            "quote": "I certify that all exit criteria have been satisfied",
            "claim": "cert presented as signed by Okafor",
        },
    ),
]


SAD_QUESTIONS = [
    ("importer", "Who is the importer and what is their TIN?", False),
    (
        "exporter_origin",
        "Who is the exporter and what is the country of origin?",
        False,
    ),
    (
        "goods",
        "What are the goods, their HS code, packages, weights and quantity?",
        False,
    ),
    (
        "valuation",
        "What is the invoice total, currency, incoterm and customs value?",
        False,
    ),
    (
        "transport",
        "What vessel, B/L number, container and ports move the shipment?",
        False,
    ),
    ("signatures", "Is the certificate signed by the named person?", True),
]


def _sad_items(without=()):
    return [
        {
            "id": item_id,
            "question": question,
            "evidence_needed": f"A document showing {item_id}",
            "needs_signature_check": signature,
        }
        for item_id, question, signature in SAD_QUESTIONS
        if item_id not in without
    ]


SAD_CHECKLIST = ("set_checklist", {"items": _sad_items()})
SAD_PARTIAL = ("set_checklist", {"items": _sad_items(without=("signatures",))})

# Stand-in for the unbuilt checklist judge (verification/verify_checklist.py):
# run tests patch the check with these so the declaration flow can be tested.
CHECKLIST_PASS = {"passed": True, "score": 1.0, "feedback": ""}
CHECKLIST_FAIL = {
    "passed": False,
    "score": 0.83,
    "feedback": "The checklist leaves out the transport leg: name the vessel, "
    "documents and ports that would settle it.",
}


def _cite(document_id, quote):
    return {"document_id": document_id, "page": 1, "quote": quote}


def _good_declaration_args():
    header = support.header_values()
    importer = _cite("DOC-MINUTES", "Mr. Lindgren confirmed the system is ready for go-live")
    exporter = _cite("DOC-MINUTES", "Erik Lindgren, Engagement Partner")
    transport = _cite("DOC-CERT", "UAT Phase 2 exit certification")
    valuation = _cite("DOC-REPORT", "Overall status is green")
    header["citations"] = {
        "importer.name": [importer],
        "importer.tin": [importer],
        "exporter.name": [exporter],
        "exporter.country": [exporter],
        "transport.vessel": [transport],
        "transport.bl_number": [transport],
        "transport.container": [transport],
        "transport.port_of_loading": [transport],
        "transport.port_of_discharge": [transport],
        "valuation.incoterm": [valuation],
        "valuation.currency": [valuation],
        "valuation.invoice_total": [valuation],
    }
    item = support.cited_declaration()["items"][0]
    item["citations"] = [_cite("DOC-REPORT", "Weekly status report")]
    return {
        "header": header,
        "items": [item],
        "discrepancies": [],
        "open_questions": [
            "importer.name",
            "valuation.invoice_total",
            "items[0].gross_kg",
            "items[0].net_kg",
            "items[0].packages",
            "items[0].hs_code",
        ],
    }


GOOD_DECLARATION = ("submit_declaration", _good_declaration_args())
EARLY_DECLARATION = support.DECLARATION


SKIP = unittest.skipUnless(
    verification_enabled(),
    "verification layer tests (VERIFICATION=on, or ./helper test --verification)",
)
GROUND_TRUTH_TEXT = [g["question"] for g in support.GROUND_TRUTH]


def context(root, client, run_id: str = "") -> tools.Context:
    run_id = run_id or new_run(root, instructions="i", objective="o")
    return tools.Context(client, root, run_id, CaseRecord(root, run_id), True)


@SKIP
class ChecklistCheckTest(unittest.TestCase):
    """verification/verify_checklist.py: the agent's checklist against the ground truth."""

    def setUp(self) -> None:
        from verification import verify_checklist

        self.verify = verify_checklist.run_verification
        self.root, tmp = support.make_root()
        self.addCleanup(tmp.cleanup)
        self.fake = support.scripted(self.root, [])
        self.ctx = context(self.root, self.fake.client)

    def test_a_complete_checklist_passes(self) -> None:
        result = self.verify(self.ctx, support.CHECKLIST_ITEMS)
        self.assertEqual(
            (True, 1.0, ""), (result["passed"], result["score"], result["feedback"])
        )

    def test_a_partial_checklist_fails_with_a_score_and_feedback(self) -> None:
        result = self.verify(self.ctx, support.PARTIAL_CHECKLIST[1]["items"])
        self.assertFalse(result["passed"])
        self.assertAlmostEqual(5 / 6, result["score"], places=2)
        self.assertTrue(result["feedback"])

    def test_the_judge_sees_the_ground_truth_but_the_feedback_does_not_repeat_it(
        self,
    ) -> None:
        result = self.verify(self.ctx, support.PARTIAL_CHECKLIST[1]["items"])
        judge = [c[1] for c in self.fake.calls if c[0] == "respond"][-1]
        self.assertIn(GROUND_TRUTH_TEXT[3], json.dumps(judge))
        self.assertFalse(
            [q for q in GROUND_TRUTH_TEXT if q.lower() in result["feedback"].lower()]
        )
        self.assertNotIn("seniority", result["feedback"])

    def test_no_ground_truth_passes(self) -> None:
        (self.root / "ground_truth/case.json").unlink()
        result = self.verify(self.ctx, support.PARTIAL_CHECKLIST[1]["items"])
        self.assertEqual((True, None), (result["passed"], result["score"]))


@SKIP
class DeclarationRulesTest(unittest.TestCase):
    """verification/verify_declaration.py: the declaration rules."""

    OKA_REF = "signed by Dana Okafor"  # DOC-REF p1
    OKA_CERT = "D. Okafor"  # DOC-CERT p1
    PARTNER = "Erik Lindgren, Engagement Partner"  # DOC-MINUTES p1
    READY = "Mr. Lindgren confirmed the system is ready for go-live"  # DOC-MINUTES p1
    PHASE2 = "UAT Phase 2 exit certification"  # DOC-CERT p1
    CERTIFY = "I certify that all exit criteria have been satisfied"  # DOC-CERT p1
    GREEN = "Overall status is green"  # DOC-REPORT p1
    DEFECTS = "Open Severity 1 defects: 21"  # DOC-REPORT p1
    WEEKLY = "Weekly status report"  # DOC-REPORT p1
    DATED = "dated December 19"  # DOC-DRAFT p1
    NOGO = "Recommendation: NO-GO"  # DOC-DRAFT p1
    WORK = "Broker work product for the review team"  # DOC-DECLARATION p1

    def setUp(self) -> None:
        from verification import verify_declaration

        self.root, tmp = support.make_root()
        self.addCleanup(tmp.cleanup)
        self.fake = support.scripted(self.root, [])
        self.ctx = context(self.root, self.fake.client)
        self.case = self.ctx.case
        self.case.set_checklist(
            [
                self.checklist_item(
                    "importer", "Who is the importer and what is their TIN?"
                ),
                self.checklist_item(
                    "exporter_origin",
                    "Who is the exporter and what is the country of origin?",
                ),
                self.checklist_item(
                    "goods_hs",
                    "What are the goods and what is their HS classification?",
                ),
                self.checklist_item(
                    "packages_weights",
                    "How many packages of what kind, and what are the gross "
                    "and net weights?",
                ),
                self.checklist_item(
                    "quantity", "What is the supplementary quantity and unit?"
                ),
                self.checklist_item(
                    "valuation",
                    "What is the invoice total, currency, incoterm and customs value?",
                ),
                self.checklist_item(
                    "transport",
                    "What are the transport details: vessel, B/L number, "
                    "container and ports?",
                ),
                self.checklist_item(
                    "consistency",
                    "Do weights, package counts, references and parties agree "
                    "across documents?",
                ),
                self.checklist_item(
                    "signatures",
                    "Is the certificate signed by the named person?",
                    signature=True,
                ),
            ]
        )
        self.verify = verify_declaration.run_verification

    @staticmethod
    def checklist_item(item_id, question, signature=False):
        return {
            "id": item_id,
            "question": question,
            "evidence_needed": f"A document showing {item_id}",
            "needs_signature_check": signature,
        }

    @staticmethod
    def citation(document_id, quote):
        return {"document_id": document_id, "page": 1, "quote": quote}

    def fact(self, item, document_id, quote):
        return self.case.record_fact(item, document_id, 1, quote, "c")

    def bare(self):
        """Minimal valid-shape declaration; rule-4 header targets named."""
        return {
            "header": support.header_values(),
            "items": [],
            "discrepancies": [],
            "open_questions": ["valuation.invoice_total", "importer.name"],
        }

    def problems(self, declaration: dict) -> list:
        result = self.verify(self.ctx, declaration)
        self.assertEqual(not result["feedback"], result["passed"])
        return result["feedback"]

    def read(self, ids: list) -> None:
        from agent_kit.tools.analyze_document import analyze

        analyze(self.fake.client, self.root, ids, "x")

    def test_open_items_and_open_requests_are_problems(self) -> None:
        self.case.open_request(
            "importer", "the commercial invoice", "missing_evidence", ALL_INITIAL
        )
        found = self.problems(self.bare())
        self.assertTrue(
            any("valuation is neither proven nor escalated" in p for p in found)
        )
        self.assertTrue(
            any("evidence request R1 for importer is still open" in p for p in found)
        )

    def test_unmatched_citations_are_problems(self) -> None:
        declaration = self.bare()
        declaration["header"]["citations"] = {
            "importer.tin": [self.citation("DOC-MINUTES", self.READY)]
        }
        found = self.problems(declaration)
        self.assertIn(
            "header importer.tin cites a quote with no matching recorded fact.", found
        )

    def test_citations_from_unrelated_items_are_problems(self) -> None:
        self.read(["DOC-MINUTES"])
        self.fact("consistency", "DOC-MINUTES", self.READY)
        declaration = self.bare()
        declaration["header"]["citations"] = {
            "importer.tin": [self.citation("DOC-MINUTES", self.READY)]
        }
        found = self.problems(declaration)
        self.assertIn(
            "header importer.tin cites a fact from unrelated item consistency.", found
        )

    def test_single_source_values_are_problems_unless_named(self) -> None:
        self.read(["DOC-REPORT"])
        self.fact("packages_weights", "DOC-REPORT", self.DEFECTS)
        item = support.cited_declaration()["items"][0]
        item["gross_kg"] = 21
        item["net_kg"] = 20
        item["citations"] = [self.citation("DOC-REPORT", self.DEFECTS)]
        named = [
            "valuation.invoice_total",
            "importer.name",
            "items[0].net_kg",
            "items[0].packages",
            "items[0].hs_code",
        ]
        declaration = {
            "header": support.header_values(),
            "items": [item],
            "discrepancies": [],
            "open_questions": list(named),
        }
        self.assertIn(
            "items[0].gross_kg is supported by only one document.",
            self.problems(declaration),
        )
        declaration["open_questions"].append("items[0].gross_kg")
        self.assertNotIn(
            "items[0].gross_kg is supported by only one document.",
            self.problems(declaration),
        )

    def signature_declaration(self) -> dict:
        support.release(self.root)
        self.read(["DOC-CERT"])
        self.fact("transport", "DOC-CERT", self.PHASE2)
        self.fact("signatures", "DOC-CERT", self.CERTIFY)
        declaration = self.bare()
        declaration["header"]["citations"] = {
            "transport.vessel": [self.citation("DOC-CERT", self.PHASE2)]
        }
        return declaration

    def test_signature_items_need_a_check_on_a_cited_document(self) -> None:
        declaration = self.signature_declaration()
        self.assertIn(
            "signatures is proven but no cited document was checked.",
            self.problems(declaration),
        )
        self.case.add_signature_check(
            {
                "document_id": "DOC-REF",
                "page": 1,
                "signer": "Dana Okafor",
                "verdict": "consistent",
            }
        )
        self.assertIn(
            "signatures is proven but no cited document was checked.",
            self.problems(declaration),
        )
        self.case.add_signature_check(
            {
                "document_id": "DOC-CERT",
                "page": 1,
                "signer": "Dana Okafor",
                "verdict": "consistent",
            }
        )
        found = self.problems(declaration)
        self.assertFalse(
            [p for p in found if "was checked" in p or "is not proven" in p]
        )

    def test_a_proven_item_cannot_rest_on_an_inconsistent_signature(self) -> None:
        declaration = self.signature_declaration()
        self.case.add_signature_check(
            {
                "document_id": "DOC-CERT",
                "page": 1,
                "signer": "Dana Okafor",
                "verdict": "inconsistent",
                "reason": "different hand",
            }
        )
        found = self.problems(declaration)
        self.assertIn(
            "DOC-CERT p1 signature is inconsistent, so signatures is not proven.",
            found,
        )
        self.assertEqual("signature", self.case.data["flags"][0]["kind"])

    def test_excluded_documents_are_never_cited(self) -> None:
        self.read(["DOC-DECLARATION"])
        self.fact("importer", "DOC-DECLARATION", self.WORK)
        self.case.flag_excluded("DOC-DECLARATION", "work product")
        declaration = self.bare()
        declaration["header"]["citations"] = {
            "importer.name": [self.citation("DOC-DECLARATION", self.WORK)]
        }
        found = self.problems(declaration)
        self.assertIn(
            "header importer.name cites excluded document DOC-DECLARATION.", found
        )

    def test_header_sanity_flags_bad_values(self) -> None:
        header = support.header_values()
        header["valuation"]["invoice_total"] = 9000
        header["exporter"]["country"] = "DEU"
        item = support.cited_declaration()["items"][0]
        item["hs_code"] = "12"
        item["origin"] = "DEU"
        item["net_kg"] = 300
        item["citations"] = []
        declaration = {
            "header": header,
            "items": [item],
            "discrepancies": [],
            "open_questions": [
                "valuation.invoice_total",
                "importer.name",
                "items[0].gross_kg",
                "items[0].net_kg",
                "items[0].packages",
                "items[0].hs_code",
            ],
        }
        found = self.problems(declaration)
        self.assertIn("exporter.country must be a 2-letter code.", found)
        self.assertIn("items[0].hs_code '12' is not a valid HS code.", found)
        self.assertIn("items[0].origin must be a 2-letter code.", found)
        self.assertIn("items[0].net_kg exceeds gross_kg.", found)
        self.assertTrue(any("item values sum to" in p for p in found))
        header["valuation"]["invoice_total"] = -5
        found = self.problems(declaration)
        self.assertIn("valuation.invoice_total must be a positive number.", found)

    def test_blank_values_are_missing_and_strings_are_normalised(self) -> None:
        header = support.header_values()
        header["valuation"]["invoice_total"] = "21,000"
        header["exporter"]["country"] = "tr"
        item = support.cited_declaration()["items"][0]
        item["item_value"] = 21000
        item["citations"] = []
        named = [
            "valuation.invoice_total",
            "importer.name",
            "items[0].gross_kg",
            "items[0].net_kg",
            "items[0].packages",
            "items[0].hs_code",
        ]
        declaration = {
            "header": header,
            "items": [item],
            "discrepancies": [],
            "open_questions": list(named),
        }
        found = self.problems(declaration)
        self.assertFalse(
            [p for p in found if "invoice_total" in p or "exporter.country" in p]
        )
        header["valuation"]["invoice_total"] = ""
        header["exporter"]["country"] = ""
        item["hs_code"] = ""
        found = self.problems(declaration)
        self.assertIn("valuation.invoice_total is missing.", found)
        self.assertIn("exporter.country is missing.", found)
        self.assertIn("items[0].hs_code is missing.", found)

    def test_a_good_declaration_has_no_problems(self) -> None:
        self.read(ALL_INITIAL)
        support.release(self.root)
        self.read(["DOC-DRAFT", "DOC-CERT"])
        self.fact("importer", "DOC-REF", self.OKA_REF)
        self.fact("importer", "DOC-CERT", self.OKA_CERT)
        self.fact("exporter_origin", "DOC-MINUTES", self.PARTNER)
        self.fact("goods_hs", "DOC-REPORT", self.WEEKLY)
        self.fact("packages_weights", "DOC-REPORT", self.DEFECTS)
        self.fact("quantity", "DOC-DRAFT", self.DATED)
        self.fact("valuation", "DOC-REPORT", self.GREEN)
        self.fact("transport", "DOC-CERT", self.PHASE2)
        self.fact("consistency", "DOC-DRAFT", self.NOGO)
        self.fact("signatures", "DOC-CERT", self.CERTIFY)
        self.case.add_signature_check(
            {
                "document_id": "DOC-CERT",
                "page": 1,
                "signer": "Dana Okafor",
                "verdict": "consistent",
            }
        )
        header = support.header_values()
        header["importer"]["name"] = "Okafor"
        green = self.citation("DOC-REPORT", self.GREEN)
        phase2 = self.citation("DOC-CERT", self.PHASE2)
        partner = self.citation("DOC-MINUTES", self.PARTNER)
        header["citations"] = {
            "importer.name": [
                self.citation("DOC-REF", self.OKA_REF),
                self.citation("DOC-CERT", self.OKA_CERT),
            ],
            "importer.tin": [self.citation("DOC-REF", self.OKA_REF)],
            "exporter.name": [partner],
            "exporter.country": [partner],
            "transport.vessel": [phase2],
            "transport.bl_number": [phase2],
            "transport.container": [phase2],
            "transport.port_of_loading": [phase2],
            "transport.port_of_discharge": [phase2],
            "valuation.incoterm": [green],
            "valuation.currency": [green],
            "valuation.invoice_total": [green],
        }
        item = support.cited_declaration()["items"][0]
        item["citations"] = [self.citation("DOC-REPORT", self.WEEKLY)]
        declaration = {
            "header": header,
            "items": [item],
            "discrepancies": [],
            "open_questions": [
                "valuation.invoice_total",
                "items[0].gross_kg",
                "items[0].net_kg",
                "items[0].packages",
                "items[0].hs_code",
            ],
        }
        self.assertEqual([], self.problems(declaration))


@SKIP
class VerifiedRunTest(unittest.TestCase):
    """The tools running the checks inside a real run of the agent loop."""

    def setUp(self) -> None:
        from customs_agent.loop import resume_run, run_agent

        self.run_agent, self.resume_run = run_agent, resume_run
        self.root, tmp = support.make_root()
        self.addCleanup(tmp.cleanup)

    def initial(self) -> list:
        return [SAD_CHECKLIST, READ_ALL, FLAG, *FACTS, EARLY_DECLARATION, ASK]

    def passing_checklist(self):
        """Patch the unbuilt checklist judge to pass (declaration flow tests)."""
        return mock.patch(
            "verification.verify_checklist.run_verification",
            return_value=dict(CHECKLIST_PASS),
        )

    def tool_results(self, run_id: str, name: str) -> list:
        return [
            out for n, _args, out in support.tool_calls(self.root, run_id) if n == name
        ]

    def test_verification_tools_are_offered(self) -> None:
        fake = support.scripted(self.root, [SAD_CHECKLIST])
        self.run_agent(root=self.root, client=fake.client, turns=1)
        offered = {t["name"] for t in support.first_agent_request(fake)["tools"]}
        self.assertTrue(
            {"flag_excluded", "request_evidence", "check_signatures"} <= offered
        )

    def test_an_incomplete_checklist_gets_feedback_not_the_ground_truth(self) -> None:
        fake = support.scripted(self.root, [SAD_PARTIAL, SAD_CHECKLIST, READ_ALL])
        with mock.patch(
            "verification.verify_checklist.run_verification",
            side_effect=[dict(CHECKLIST_FAIL), dict(CHECKLIST_PASS)],
        ):
            result = self.run_agent(root=self.root, client=fake.client, turns=3)
        refused = self.tool_results(result["run_id"], "set_checklist")[0]
        self.assertEqual({"error", "feedback"}, set(refused))
        sent = json.dumps(support.agent_requests(fake))
        self.assertIn(CHECKLIST_FAIL["feedback"], sent)
        self.assertNotIn("score", sent)
        case = support.case(self.root, result["run_id"])
        self.assertEqual([False, True], [c["passed"] for c in case["checklist_checks"]])
        self.assertAlmostEqual(0.83, case["checklist_checks"][0]["score"], places=2)
        self.assertTrue(case["checklist"]["signatures"]["added_after_check"])

    def test_the_checklist_is_accepted_after_three_refusals(self) -> None:
        fake = support.scripted(self.root, [SAD_PARTIAL, SAD_PARTIAL, SAD_PARTIAL, READ_ALL])
        with mock.patch(
            "verification.verify_checklist.run_verification",
            return_value=dict(CHECKLIST_FAIL, score=0.5),
        ):
            result = self.run_agent(root=self.root, client=fake.client, turns=4)
        case = support.case(self.root, result["run_id"])
        self.assertEqual(5, len(case["checklist"]))
        last = case["checklist_checks"][-1]
        self.assertEqual(
            (False, True, 3), (last["passed"], last["accepted"], last["attempt"])
        )

    def test_early_declaration_is_refused_and_missing_evidence_escalates(self) -> None:
        fake = support.scripted(self.root, self.initial())
        with self.passing_checklist():
            result = self.run_agent(root=self.root, client=fake.client, turns=20)
        self.assertEqual("needs_input", result["status"])
        refused = self.tool_results(result["run_id"], "submit_declaration")[0]
        self.assertEqual("declaration", refused["check"])
        case = support.case(self.root, result["run_id"])
        self.assertEqual(
            ("transport", "missing_evidence"),
            (case["requests"][0]["item"], case["requests"][0]["rule"]),
        )
        self.assertIsNone(case["declaration"])

    def test_escalating_before_reading_everything_is_refused(self) -> None:
        fake = support.scripted(self.root, [SAD_CHECKLIST, ASK])
        with self.passing_checklist():
            result = self.run_agent(root=self.root, client=fake.client, turns=2)
        self.assertIn(
            "read every visible document",
            self.tool_results(result["run_id"], "request_evidence")[0]["error"],
        )

    def test_resume_without_new_evidence_makes_no_model_call(self) -> None:
        fake = support.scripted(self.root, self.initial())
        with self.passing_checklist():
            result = self.run_agent(root=self.root, client=fake.client, turns=20)
        before = len(fake.calls)
        resumed = self.resume_run(
            root=self.root, run_id=result["run_id"], client=fake.client, turns=5
        )
        self.assertEqual("needs_input", resumed["status"])
        self.assertIn("nothing new", resumed["note"])
        self.assertEqual(before, len(fake.calls))

    def test_release_resume_verified_declaration_then_signoff(self) -> None:
        fake = support.scripted(self.root, self.initial() + AFTER_RELEASE + [GOOD_DECLARATION])
        with self.passing_checklist():
            result = self.run_agent(root=self.root, client=fake.client, turns=20)
            support.release(self.root)
            resumed = self.resume_run(
                root=self.root, run_id=result["run_id"], client=fake.client, turns=10
            )
        self.assertEqual(
            (result["run_id"], "awaiting_signoff"),
            (resumed["run_id"], resumed["status"]),
        )
        first_after = support.agent_requests(fake)[len(self.initial())]
        self.assertIn(
            "Released documents: DOC-CERT, DOC-DRAFT", json.dumps(first_after["input"])
        )
        case = CaseRecord(self.root, result["run_id"])
        self.assertEqual("awaiting_signoff", case.data["declaration"]["status"])
        self.assertEqual(
            ["declaration", "declaration", "claims"], [c["check"] for c in case.data["declaration_checks"]]
        )
        self.assertEqual("consistent", case.data["signature_checks"][0]["verdict"])
        case.review_declaration(True, "approved")
        done = self.resume_run(
            root=self.root, run_id=result["run_id"], client=fake.client, turns=5
        )
        self.assertEqual("done", done["status"])
        self.assertEqual(
            "done", support.progress(self.root, result["run_id"])["status"]
        )

    def test_a_rejected_declaration_goes_back_to_the_agent(self) -> None:
        fake = support.scripted(
            self.root, self.initial() + AFTER_RELEASE + [GOOD_DECLARATION, GOOD_DECLARATION]
        )
        with self.passing_checklist():
            result = self.run_agent(root=self.root, client=fake.client, turns=20)
            support.release(self.root)
            self.resume_run(
                root=self.root, run_id=result["run_id"], client=fake.client, turns=10
            )
        CaseRecord(self.root, result["run_id"]).review_declaration(
            False, "Explain the valuation evidence more fully."
        )
        with self.passing_checklist():
            again = self.resume_run(
                root=self.root, run_id=result["run_id"], client=fake.client, turns=5
            )
        self.assertEqual("awaiting_signoff", again["status"])
        self.assertIn("rejected", str(support.agent_requests(fake)[-1]["input"]))

    def test_unsupported_claims_refuse_the_declaration(self) -> None:
        fake = support.scripted(
            self.root,
            self.initial() + AFTER_RELEASE + [GOOD_DECLARATION],
            unsupported=lambda text: [
                {"field": "transport.vessel", "reason": "the quote gives no vessel"}
            ],
        )
        with self.passing_checklist():
            result = self.run_agent(root=self.root, client=fake.client, turns=20)
            support.release(self.root)
            resumed = self.resume_run(
                root=self.root, run_id=result["run_id"], client=fake.client, turns=10
            )
        refused = self.tool_results(result["run_id"], "submit_declaration")[-1]
        self.assertEqual("claims", refused["check"])
        self.assertNotEqual("awaiting_signoff", resumed["status"])

    def test_three_refused_declarations_escalate_to_a_person(self) -> None:
        fake = support.scripted(
            self.root, [SAD_CHECKLIST, READ_ALL, EARLY_DECLARATION, EARLY_DECLARATION, EARLY_DECLARATION]
        )
        with self.passing_checklist():
            result = self.run_agent(root=self.root, client=fake.client, turns=10)
        self.assertEqual(("needs_input", 5), (result["status"], result["turn"]))
        self.assertEqual(
            "declaration_refused",
            support.case(self.root, result["run_id"])["requests"][0]["rule"],
        )

    def test_a_flagged_document_cannot_be_read_again(self) -> None:
        reread = ("analyze_document", {"document_ids": ["DOC-DECLARATION"], "request": "x"})
        fake = support.scripted(self.root, [SAD_CHECKLIST, READ_ALL, FLAG, reread])
        with self.passing_checklist():
            result = self.run_agent(root=self.root, client=fake.client, turns=4)
        self.assertIn(
            "confidential",
            self.tool_results(result["run_id"], "analyze_document")[-1]["error"],
        )


@SKIP
class ContinueFromSessionOneTest(unittest.TestCase):
    """./helper verify on a finished Session 1 run, then ./helper branch from its checklist."""

    def setUp(self) -> None:
        from customs_agent.loop import resume_run, run_agent

        self.run_agent, self.resume_run = run_agent, resume_run
        self.root, tmp = support.make_root()
        self.addCleanup(tmp.cleanup)

    def test_verify_finds_the_declaration_and_checklist_problems(self) -> None:
        run_id = self._session_one()
        fake = support.scripted(self.root, [])
        declaration = verify.verify_declaration(verify.context(fake.client, self.root, run_id))
        self.assertFalse(declaration["passed"])
        self.assertTrue(
            any("neither proven nor escalated" in p for p in declaration["rules"])
        )
        with mock.patch(
            "verification.verify_checklist.run_verification",
            return_value=dict(CHECKLIST_FAIL),
        ):
            checklist = verify.verify_checklist(
                verify.context(fake.client, self.root, run_id)
            )
        self.assertFalse(checklist["passed"])
        self.assertAlmostEqual(0.83, checklist["score"], places=2)
        self.assertTrue(checklist["feedback"])
        self.assertEqual(
            "answered", support.progress(self.root, run_id)["status"]
        )  # the run is unchanged

    def test_branch_continues_from_the_checklist_with_verification_on(self) -> None:
        run_id = self._session_one()
        fake = support.scripted(self.root, [SAD_CHECKLIST, support.PLAN, READ_ALL])
        with mock.patch(
            "verification.verify_checklist.run_verification",
            side_effect=[dict(CHECKLIST_FAIL), dict(CHECKLIST_PASS)],
        ):
            new_id = branch(fake.client, self.root, run_id)
            self.assertNotEqual(run_id, new_id)
            progress = support.progress(self.root, new_id)
            refused = json.loads(progress["messages"][-1]["output"])
            self.assertEqual({"error", "feedback"}, set(refused))
            self.assertEqual(
                (True, "paused", 0),
                (progress["verification"], progress["status"], progress["turn"]),
            )
            self.assertEqual(run_id, progress["notes"]["branched_from"])
            self.assertEqual("set_checklist", progress["messages"][-2]["name"])
            resumed = self.resume_run(
                root=self.root, run_id=new_id, client=fake.client, turns=3
            )
        self.assertEqual("paused", resumed["status"])
        first = support.agent_requests(fake)[0]
        self.assertIn("verification layer on", json.dumps(first["input"]))
        self.assertEqual(
            "checklist refused", json.loads(first["input"][-2]["output"])["error"]
        )
        case = support.case(self.root, new_id)
        self.assertEqual([False, True], [c["passed"] for c in case["checklist_checks"]])
        self.assertEqual(6, len(case["checklist"]))
        self.assertEqual(
            5, len(support.case(self.root, run_id)["checklist"])
        )  # the Session 1 run is unchanged

    def _session_one(self) -> str:
        os.environ["VERIFICATION"] = "off"
        try:
            fake = support.scripted(
                self.root,
                [SAD_PARTIAL, READ_ALL, FACTS[0], FACTS[1], EARLY_DECLARATION],
            )
            result = self.run_agent(root=self.root, client=fake.client, turns=10)
        finally:
            os.environ["VERIFICATION"] = "on"
        self.assertEqual("answered", result["status"])
        return result["run_id"]


if __name__ == "__main__":
    unittest.main()
