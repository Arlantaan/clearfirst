"""The case record: the simulated case-management system the agent acts on.

One JSON record per run at workspace/case_records/<run-id>.json, written only
through this module and append-audited. The agent changes it through tools
(set_checklist, record_fact, flag_excluded, request_evidence, submit_declaration); people change
it through ./helper review (answer a request, approve or reject the declaration).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import document_text
from .progress import now

ITEM_STATUSES = ("open", "proven", "escalated")


MAX_FACTS_PER_ITEM = 3
MAX_CITATIONS = 3  # per header field or item

HEADER_FIELDS = (
    "declaration_type",
    "procedure_code",
    "importer.name",
    "importer.tin",
    "exporter.name",
    "exporter.country",
    "transport.vessel",
    "transport.bl_number",
    "transport.container",
    "transport.port_of_loading",
    "transport.port_of_discharge",
    "valuation.incoterm",
    "valuation.currency",
    "valuation.invoice_total",
)

ITEM_FIELDS = (
    "line",
    "description",
    "hs_code",
    "hs_justification",
    "origin",
    "packages",
    "package_kind",
    "gross_kg",
    "net_kg",
    "supplementary_qty",
    "supplementary_unit",
    "item_value",
)

BROKER_DECLARED = ("declaration_type", "procedure_code")


def _header_value(header: dict, path: str):
    """header["importer"]["tin"] for path "importer.tin"; None when absent."""
    value = header
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _is_blank(value) -> bool:
    """Missing, or a string with nothing in it. Numbers (even 0) count as present."""
    return value is None or (isinstance(value, str) and not value.strip())


class CaseError(ValueError):
    """A write the case record refused. The message is safe to show the model."""


class FactLimitError(CaseError):
    """The item already has MAX_FACTS_PER_ITEM facts. Not a rejected quote."""


ITEM_ID = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


class CaseRecord:
    def __init__(self, root: Path, run_id: str) -> None:
        self.root = root
        self.path = root / "workspace/case_records" / f"{run_id}.json"
        if self.path.is_file():
            self.data: dict[str, Any] = json.loads(self.path.read_text())
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.data = {
                "run_id": run_id,
                "created": now(),
                "checklist": {},
                "checklist_checks": [],
                "declaration_checks": [],
                "read_ids": [],
                "facts": [],
                "rejected_facts": [],
                "flags": [],
                "signature_checks": [],
                "requests": [],
                "declaration": None,
                "audit": [],
            }
            self._save("created", "runtime", {})

    # ---- persistence ----
    def _save(self, action: str, actor: str, detail: dict) -> None:
        self.data["audit"].append(
            {"at": now(), "actor": actor, "action": action, "detail": detail}
        )
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2))
        tmp.replace(self.path)

    def _item(self, item: str) -> dict:
        if not self.data["checklist"]:
            raise CaseError("there is no checklist yet: call set_checklist first")
        if item not in self.data["checklist"]:
            raise CaseError(
                f"unknown checklist item {item!r}; valid items: {', '.join(self.data['checklist'])}"
            )
        return self.data["checklist"][item]

    def flagged(self, document_id: str) -> bool:
        return any(
            flag["document_id"] == document_id and flag["kind"] == "excluded"
            for flag in self.data["flags"]
        )

    # ---- agent writes ----
    def parse_checklist(self, items: list) -> dict:
        """Validate checklist items and return the new checklist, without saving it."""
        if not isinstance(items, list) or not items:
            raise CaseError("the checklist needs at least one item")
        new: dict[str, dict] = {}
        for raw in items:
            if not isinstance(raw, dict):
                raise CaseError("each checklist item must be an object")
            item_id = str(raw.get("id", "")).strip()
            if not ITEM_ID.match(item_id):
                raise CaseError(
                    f"item id {item_id!r} must be snake_case, e.g. ready_statement"
                )
            if item_id in new:
                raise CaseError(f"duplicate checklist item {item_id}")
            question = str(raw.get("question", "")).strip()
            evidence = str(raw.get("evidence_needed", "")).strip()
            if not question:
                raise CaseError(f"{item_id}: question is empty")
            if not evidence:
                raise CaseError(
                    f"{item_id}: say what evidence would settle it (evidence_needed)"
                )
            old = self.data["checklist"].get(item_id, {})
            new[item_id] = {
                "question": question,
                "evidence_needed": evidence,
                "needs_signature_check": bool(raw.get("needs_signature_check")),
                "status": old.get("status", "open"),
                "facts": old.get("facts", []),
                "request": old.get("request"),
            }
        dropped = [
            k
            for k, v in self.data["checklist"].items()
            if k not in new and (v["facts"] or v["request"])
        ]
        if dropped:
            raise CaseError(
                f"keep the items that already have facts or requests: {', '.join(dropped)}"
            )
        return new

    def set_checklist(self, items: list) -> dict:
        """Replace the checklist. Items that already have facts or requests must be kept."""
        new = self.parse_checklist(items)
        checks = self.data.get("checklist_checks", [])
        first_draft = (
            set(checks[0]["draft"]) if checks and not checks[0]["passed"] else None
        )
        for item_id, entry in new.items():
            entry["added_after_check"] = (
                first_draft is not None and item_id not in first_draft
            )
        self.data["checklist"] = new
        self._save("checklist_set", "agent", {"items": list(new)})
        return new

    def record_checklist_check(self, items: list, result: dict) -> dict:
        """Store the outcome of the ground-truth checklist check for one draft."""
        record = {
            "draft": [str(i.get("id")) for i in items if isinstance(i, dict)],
            "passed": bool(result.get("passed")),
            "score": result.get("score"),
            "feedback": result.get("feedback", ""),
            "attempt": result.get("attempt"),
            "accepted": bool(result.get("accepted", result.get("passed"))),
            "at": now(),
        }
        self.data.setdefault("checklist_checks", []).append(record)
        self._save(
            "checklist_checked",
            "verification",
            {"passed": record["passed"], "accepted": record["accepted"]},
        )
        return record

    def record_declaration_check(self, check: str, problems: list) -> dict:
        """Store the outcome of a declaration check (declaration rules or claims) for one submitted declaration."""
        record = {
            "check": check,
            "passed": not problems,
            "problems": problems,
            "at": now(),
        }
        self.data.setdefault("declaration_checks", []).append(record)
        self._save(
            "declaration_checked", "verification", {"check": check, "passed": not problems}
        )
        return record

    def declaration_refusals(self) -> int:
        return sum(1 for c in self.data.get("declaration_checks", []) if not c["passed"])

    def mark_read(self, document_ids: list) -> None:
        """Remember which documents the agent has read (the escalation rule needs it)."""
        read = self.data.setdefault("read_ids", [])
        new = [d for d in document_ids if d not in read]
        if new:
            read += new
            self._save("documents_read", "agent", {"documents": new})

    def progress(self) -> dict:
        """Where the checklist stands: proven, escalated and open items, and what to do next."""
        checklist = self.data["checklist"]
        by_status = {
            status: [k for k, v in checklist.items() if v["status"] == status]
            for status in ("proven", "escalated", "open")
        }
        done = len(by_status["proven"]) + len(by_status["escalated"])
        if by_status["open"]:
            next_step = (
                f"Open: {', '.join(by_status['open'])}. Get one fact for each open item "
                "before adding more to any item."
            )
        else:
            next_step = (
                "Every item is proven or escalated: file the declaration now. Add another fact "
                f"only if one could be disputed (at most {MAX_FACTS_PER_ITEM} per item)."
            )
        return {
            "proven": len(by_status["proven"]),
            "escalated": len(by_status["escalated"]),
            "open": by_status["open"],
            "total": len(checklist),
            "summary": f"{done} of {len(checklist)} items proven or escalated. {next_step}",
        }

    def record_fact(
        self, item: str, document_id: str, page: int, quote: str, claim: str
    ) -> dict:
        """Mark evidence for a checklist item. Refused unless the quote is on that page.

        At most MAX_FACTS_PER_ITEM facts per item (FactLimitError). The returned fact
        carries `progress` (see progress()) so the model sees what is still open.
        """
        entry = self._item(item)
        if len(entry["facts"]) >= MAX_FACTS_PER_ITEM:
            raise FactLimitError(
                f"{item} already has {MAX_FACTS_PER_ITEM} facts, the most an item takes. "
                + self.progress()["summary"]
            )
        try:
            page = int(page)
            if not claim or not str(claim).strip():
                raise CaseError("claim must be non-empty")
            if self.flagged(document_id):
                raise CaseError(
                    f"{document_id} is flagged as confidential and can never be cited"
                )
            document_text.get_document(self.root, document_id)
            text = document_text.page_text(self.root, document_id, page)
            if text is None:
                raise CaseError(
                    f"{document_id} has not been analyzed yet; call analyze_document first"
                )
            if not document_text.quote_on_page(quote, text):
                raise CaseError(
                    f"quote not found on {document_id} page {page}; copy the exact words from the document"
                )
        except (CaseError, document_text.DocumentError, TypeError, ValueError) as error:
            self.data["rejected_facts"].append(
                {
                    "item": item,
                    "document_id": document_id,
                    "page": page,
                    "quote": quote,
                    "reason": str(error),
                    "at": now(),
                }
            )
            self._save(
                "fact_rejected",
                "agent",
                {"item": item, "document_id": document_id, "reason": str(error)},
            )
            raise CaseError(str(error)) from None
        fact = {
            "id": f"F{len(self.data['facts']) + 1}",
            "item": item,
            "document_id": document_id,
            "page": page,
            "quote": quote,
            "claim": str(claim),
            "at": now(),
        }
        self.data["facts"].append(fact)
        entry["facts"].append(fact["id"])
        entry["status"] = "proven"
        self._save(
            "fact_recorded",
            "agent",
            {
                "fact": fact["id"],
                "item": item,
                "document_id": document_id,
                "page": page,
            },
        )
        return dict(fact, progress=self.progress())

    def flag_excluded(self, document_id: str, reason: str) -> dict:
        document_text.get_document(self.root, document_id)
        if self.flagged(document_id):
            return next(
                f
                for f in self.data["flags"]
                if f["document_id"] == document_id and f["kind"] == "excluded"
            )
        flag = {
            "kind": "excluded",
            "document_id": document_id,
            "reason": str(reason),
            "review": "pending",
            "at": now(),
        }
        self.data["flags"].append(flag)
        withdrawn = [
            f["id"] for f in self.data["facts"] if f["document_id"] == document_id
        ]
        self.data["facts"] = [
            f for f in self.data["facts"] if f["document_id"] != document_id
        ]
        for entry in self.data["checklist"].values():
            entry["facts"] = [f for f in entry["facts"] if f not in withdrawn]
            if entry["status"] == "proven" and not entry["facts"]:
                entry["status"] = "open"
        self._save(
            "document_flagged",
            "agent",
            {"document_id": document_id, "withdrawn_facts": withdrawn},
        )
        return flag

    def add_signature_check(self, result: dict) -> dict:
        record = dict(result, at=now())
        self.data["signature_checks"].append(record)
        if result.get("verdict") in ("inconsistent", "unclear", "unsigned"):
            self.data["flags"].append(
                {
                    "kind": "signature",
                    "document_id": result.get("document_id"),
                    "reason": f"{result.get('verdict')}: {result.get('reason', '')}",
                    "review": "pending",
                    "at": now(),
                }
            )
        self._save(
            "signature_checked",
            "agent",
            {
                "document_id": result.get("document_id"),
                "verdict": result.get("verdict"),
            },
        )
        return record

    def open_request(
        self,
        item: str,
        need: str,
        rule: str,
        visible_ids: list,
        evidence_so_far: list | None = None,
    ) -> dict:
        entry = self._item(item)
        if not need or not str(need).strip():
            raise CaseError("need must say exactly what evidence is missing")
        request = {
            "id": f"R{len(self.data['requests']) + 1}",
            "item": item,
            "rule": rule,
            "need": str(need),
            "visible_ids": list(visible_ids),
            "evidence_so_far": evidence_so_far or list(self.data["facts"]),
            "status": "open",
            "response": None,
            "at": now(),
        }
        self.data["requests"].append(request)
        entry["request"] = request["id"]
        if entry["status"] == "open":
            entry["status"] = "escalated"
        self._save(
            "request_opened",
            "agent",
            {"request": request["id"], "item": item, "rule": rule},
        )
        return request

    def open_requests(self) -> list:
        return [r for r in self.data["requests"] if r["status"] == "open"]

    def file_declaration(self, declaration: dict, status: str) -> dict:
        """File the SAD declaration (header, items, discrepancies, open_questions).

        Refused unless every header box is filled, and every other header field and
        every item field is cited (1-3 quotes copied exactly from an analyzed page)
        or named in discrepancies/open_questions. declaration_type and procedure_code
        are the broker's choice and take no citation.
        """
        header = declaration.get("header") if isinstance(declaration, dict) else None
        items = declaration.get("items") if isinstance(declaration, dict) else None
        discrepancies = (
            declaration.get("discrepancies") if isinstance(declaration, dict) else None
        )
        open_questions = (
            declaration.get("open_questions") if isinstance(declaration, dict) else None
        )
        if not isinstance(header, dict):
            raise CaseError("the declaration needs a header object")
        if not isinstance(items, list):
            raise CaseError("the declaration needs an items list")
        if not isinstance(discrepancies, list):
            raise CaseError("the declaration needs a discrepancies list")
        if not isinstance(open_questions, list):
            raise CaseError("the declaration needs an open_questions list")
        named_fields = {
            str(d.get("field", "")).strip()
            for d in discrepancies
            if isinstance(d, dict) and str(d.get("field", "")).strip()
        }
        questions = [str(q) for q in open_questions]

        def named(path: str) -> bool:
            return path in named_fields or any(path in q for q in questions)

        citations = header.get("citations") or {}
        if not isinstance(citations, dict):
            raise CaseError("header citations must be an object keyed by field path")
        broker_cited = [p for p in BROKER_DECLARED if citations.get(p)]
        if len(broker_cited) == 1:
            raise CaseError(
                f"{broker_cited[0]} is declared by the broker and takes no "
                "citation; remove its citations"
            )
        if broker_cited:
            raise CaseError(
                f"{', '.join(broker_cited)} are declared by the broker and take "
                "no citation; remove their citations"
            )
        missing_values = [
            p for p in HEADER_FIELDS if _is_blank(_header_value(header, p))
        ]
        if missing_values:
            raise CaseError(
                "missing header values for: "
                + ", ".join(missing_values)
                + "; fill every header box"
            )
        missing = []
        for path in HEADER_FIELDS:
            if path in BROKER_DECLARED:
                continue
            cites = citations.get(path) or []
            if cites:
                self._check_citations(cites, f"header {path}")
            elif not named(path):
                missing.append(path)
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise CaseError(f"items[{index}] must be an object")
            cites = item.get("citations") or []
            if cites:
                self._check_citations(cites, f"items[{index}]")
            else:
                missing.extend(
                    f"items[{index}].{field}"
                    for field in ITEM_FIELDS
                    if not named(f"items[{index}].{field}")
                )
        if missing:
            raise CaseError(
                "missing citations for: "
                + ", ".join(missing)
                + "; cite each field or name it in discrepancies or open_questions"
            )
        record = dict(declaration, status=status, filed=now(), review=None)
        self.data["declaration"] = record
        self._save("declaration_filed", "agent", {"status": status})
        return record

    def _check_citations(self, cites: list, where: str) -> None:
        """One citation list: 1-3 quotes, each exactly on its page of an analyzed document."""
        if not isinstance(cites, list) or not cites:
            raise CaseError(f"{where} needs 1-3 citations")
        if len(cites) > MAX_CITATIONS:
            raise CaseError(
                f"{where} cites {len(cites)} quotes; "
                f"cite its {MAX_CITATIONS} strongest at most"
            )
        for cite in cites:
            if not isinstance(cite, dict):
                raise CaseError(f"{where} has a citation that is not an object")
            document_id = str(cite.get("document_id", ""))
            quote = str(cite.get("quote", ""))
            try:
                page = int(cite.get("page"))
            except (TypeError, ValueError):
                raise CaseError(
                    f"{where} cites {document_id or 'a document'} with no page number"
                ) from None
            if self.flagged(document_id):
                raise CaseError(
                    f"{document_id} is flagged as confidential and can never be cited"
                )
            try:
                document_text.get_document(self.root, document_id)
            except document_text.DocumentError as error:
                raise CaseError(str(error)) from None
            text = document_text.page_text(self.root, document_id, page)
            if text is None:
                raise CaseError(
                    f"{document_id} has not been analyzed yet; call analyze_document first"
                )
            if not document_text.quote_on_page(quote, text):
                raise CaseError(
                    f"quote not found on {document_id} page {page}; copy the exact words from the document"
                )

    # ---- people ----
    def answer_request(self, request_id: str, response: str) -> dict:
        for request in self.data["requests"]:
            if request["id"] == request_id:
                request["status"] = "answered"
                request["response"] = response
                request["answered"] = now()
                self._save("request_answered", "human", {"request": request_id})
                return request
        raise CaseError(f"no request {request_id}")

    def review_declaration(
        self, approve: bool, notes: str = "", flag_decisions: dict | None = None
    ) -> dict:
        declaration = self.data.get("declaration")
        if not declaration:
            raise CaseError("no declaration has been filed")
        declaration["review"] = {
            "decision": "approved" if approve else "rejected",
            "notes": notes,
            "at": now(),
        }
        declaration["status"] = "approved" if approve else "rejected"
        for flag in self.data["flags"]:
            flag["review"] = (flag_decisions or {}).get(
                flag["document_id"], "confirmed" if approve else flag["review"]
            )
        self._save("declaration_reviewed", "human", {"decision": declaration["status"]})
        return declaration

    # ---- reads ----
    def summary(self) -> dict:
        return {
            "checklist": {
                k: {
                    "status": v["status"],
                    "facts": len(v["facts"]),
                    "request": v["request"],
                }
                for k, v in self.data["checklist"].items()
            },
            "facts": len(self.data["facts"]),
            "flags": [
                {"kind": f["kind"], "document_id": f["document_id"]}
                for f in self.data["flags"]
            ],
            "open_requests": [r["id"] for r in self.open_requests()],
            "declaration": (self.data["declaration"] or {}).get("status"),
        }
