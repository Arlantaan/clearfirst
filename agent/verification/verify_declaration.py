"""The declaration rules. run_verification is not implemented yet.

Called when the agent calls submit_declaration with VERIFICATION=on, and by
./helper verify RUN --declaration.

    run_verification(ctx, declaration) -> {"passed": bool, "feedback": [problem, ...]}

declaration = {"conclusion": str, "findings": [{"item", "status", "summary", "citations": [
{"document_id", "page", "quote"}]}], "gaps": str}. ctx.case is the run's CaseRecord:
case.data["checklist"], case.data["facts"], case.data["signature_checks"] (each with
document_id, page, verdict), case.flagged(document_id), case.open_requests(). Compare
quotes with agent_kit.document_text.normalize.

Rules (one problem string per break, which the agent reads and fixes; passed = no problems):
- every checklist item has a finding, and is proven or escalated (status "open" is a problem);
- a finding marked "proven" has a recorded fact for its item, and cites at least one;
- every citation matches a recorded fact (same document, page, and quote);
- no citation is from a document flagged confidential;
- an item with needs_signature_check that is marked proven has a signature check on a
  document it cites, and every such check's verdict is "consistent" (otherwise the item
  is not proven: say so, and name it as a gap);
- no evidence request is still open.
"""

from __future__ import annotations


def run_verification(ctx, declaration: dict) -> dict:
    raise NotImplementedError("verification/verify_declaration.py is not implemented yet")
