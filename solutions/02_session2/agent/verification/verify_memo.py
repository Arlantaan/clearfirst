"""The memo rules. Called when the agent calls submit_memo with VERIFICATION=on, and by
./helper verify RUN --memo.

    run_verification(ctx, memo) -> {"passed": bool, "feedback": [problem, ...]}
"""

from __future__ import annotations

from agent_kit.document_text import normalize


def run_verification(ctx, memo: dict) -> dict:
    case = ctx.case
    checklist = case.data["checklist"]
    if not checklist:
        return {
            "passed": False,
            "feedback": ["there is no checklist yet: call set_checklist first"],
        }
    findings = {
        f.get("item"): f for f in memo.get("findings") or [] if isinstance(f, dict)
    }
    problems = []
    for item, entry in checklist.items():
        finding = findings.get(item)
        if finding is None:
            problems.append(f"no finding for {item}")
            continue
        problems += _item_problems(case, item, entry, finding)
    if case.open_requests():
        problems.append("an evidence request is still open")
    return {"passed": not problems, "feedback": problems}


def _item_problems(case, item: str, entry: dict, finding: dict) -> list:
    problems = []
    proven = finding.get("status") == "proven"
    citations = finding.get("citations") or []
    if entry["status"] == "open":
        problems.append(
            f"{item} is neither proven nor escalated: record a fact or call request_evidence"
        )
    if proven and entry["status"] != "proven":
        problems.append(f"{item} is marked proven but has no recorded fact")
    if proven and not citations:
        problems.append(f"{item} is marked proven but cites nothing")
    if proven and entry.get("needs_signature_check"):
        problems += _signature_problems(case, item, citations)
    for citation in citations:
        problems += _citation_problems(case, citation)
    return problems


def _signature_problems(case, item: str, citations: list) -> list:
    cited = {c.get("document_id") for c in citations}
    checks = [s for s in case.data["signature_checks"] if s.get("document_id") in cited]
    if not checks:
        return [
            f"{item} rests on a signature, but no cited document was checked with check_signatures"
        ]
    return [
        f"{item} is marked proven, but the signature on {s['document_id']} p{s.get('page')} is "
        f"{s.get('verdict')}: mark the item not proven and name it as a gap"
        for s in checks
        if s.get("verdict") != "consistent"
    ]


def _citation_problems(case, citation: dict) -> list:
    document_id, page = citation.get("document_id", ""), citation.get("page")
    if case.flagged(document_id):
        return [f"{document_id} is confidential and can never be cited"]
    quote = normalize(citation.get("quote", ""))
    if any(
        f["document_id"] == document_id
        and f["page"] == page
        and normalize(f["quote"]) == quote
        for f in case.data["facts"]
    ):
        return []
    return [f"citation has no matching recorded fact: {document_id} p{page}"]
