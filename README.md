# ClearFirst

**Declarations that clear first time.**

ClearFirst is an AI customs-broker agent. Give it a shipment's documents — commercial invoice, packing list, bill of lading, certificate of origin — and it produces a customs declaration (SAD / IM4) in which **every box is proven**: each figure carries the document, page and exact quote it came from, the documents are cross-checked against each other, the HS classification is justified, the duty is estimated from the country's tariff structure, and a licensed broker reviews and signs off before anything is exported.

Built solo for the Meta Global AI Developer Hackathon (Indie track), Oct 26 – Nov 4, 2026. All code was written by **Muse Code**; the agent reasons with **Muse Spark 1.3** and checks signatures and stamps with **SAM 3.1**, both through the Meta Model API.

---

## Why

In The Gambia and across West Africa, customs declarations are typed by hand into ASYCUDA by brokers reading paper documents. A mistyped weight, a package count that disagrees with the bill of lading, or a wrong HS code means the declaration is queried, the container sits at the port, and the importer pays demurrage and storage for every day it waits. Most clearance delays are not fraud — they are documents that do not agree with each other and nobody checked.

No AI tooling exists for this workflow in ASYCUDA countries today. Extraction products pull numbers out of PDFs; ClearFirst is built the other way round: **a figure that cannot be proven from the documents is refused**, and a disagreement between documents is reported as a discrepancy rather than silently resolved.

## What it does

1. **Reads the shipment** — the four documents are rendered to page images and read by the model.
2. **Sets a checklist** of the SAD boxes it must settle (parties, transport, goods, weights, packages, value, origin, classification).
3. **Records facts with proof** — a fact is only accepted if its quote appears verbatim on the cited page. Weights, packages, HS code and the parties must be supported by **two independent documents**.
4. **Cross-checks** — where the bill of lading says 806 packages and the packing list says 860, the agent cannot pick one; it files a named discrepancy with both documents.
5. **Classifies and costs** — HS code with a written justification, then duty, VAT and levies from the tariff pack (`tariff/gm.json`: GRA import duty, processing fee 1.5%, AU levy 0.2%, ECOWAS levy 0.5%, GNSW 1.0%, VAT).
6. **Submits the declaration** — refused by the verification layer until every box is cited, every item is proven or escalated, the numbers are sane (net ≤ gross, item values add up, valid HS format) and nothing cites an excluded document.
7. **Escalates** — after three refusals it must stop and ask the broker a specific question.
8. **Broker sign-off** — the broker reviews the SAD, discrepancies and open questions in the console, approves or rejects, and exports the signed declaration as **PDF**, **XML**, or via the **ASYCUDA adapter** (a stub today; the door for DTI integration).

### The verification layer

The checks live inside the tools, so the model cannot skip them:

| Check | Where | What it refuses |
|---|---|---|
| Quote check | `record_fact` | a fact whose quote is not on that page |
| Checklist check | `set_checklist` | a checklist that misses what the case actually requires (judged against hidden ground truth; feedback never leaks the truth) |
| Declaration rules | `submit_declaration` | uncited boxes, items not proven, single-document support for critical fields, excluded documents, arithmetic and format errors |
| Signature check | `check_signatures` | SAM 3.1 segments signatures/stamps on two pages, Spark compares the ink; missing or inconsistent → broker flag |
| Claims judge | after submission | a Spark judge reads the free-text boxes against the record; disagreements become advisory flags for the broker |

## Demo shipments

Three fictional shipments into Banjul, with documents generated to match the layout of real Gambian clearance paperwork:

- **`cases/gypsum-boards-tr`** — gypsum plasterboard from Türkiye (HS 6809.19.00, 1,245 pallets, USD 21,000 CIF). Clean documents: the baseline case. Duty, VAT and levies computed under the normal procedure (20% CET band, VAT 15%).
- **`cases/ceramic-tiles-cn`** — porcelain tiles from China (HS 6907.21.00, 860 pallets, USD 17,000). The bill of lading **deliberately disagrees** with the packing list on package count (806 vs 860) and gross weight (24,080 vs 24,800 kg). The agent files both as discrepancies and the broker sees them before signing.

- **`cases/rice-vn`** — long grain rice from Vietnam (HS 1006.30.00, 500 bags, 25,000 kg, USD 13,500). Weights and counts agree everywhere, but the **invoice states origin Thailand** while the certificate of origin certifies Viet Nam. Origin decides tariff treatment, so the agent must flag it rather than pick one.

`ground_truth/` holds what the checklist check compares against. It is never shown to the agent.

## Run it

```bash
git clone https://github.com/Arlantaan/clearfirst.git
cd clearfirst/agent
cp .env.example .env          # add your MODEL_API_KEY from dev.meta.ai; set VERIFICATION=on
./helper setup                # creates .venv, copies the case's documents, checks the key
./helper test                 # offline tests, no API calls

# Console (shipments, live runs, SAD view, sign-off, export)
.venv/bin/python ../ui/ui.py  # http://127.0.0.1:8765

# or from the terminal
./helper run --turns 40
./helper review RUN_ID --approve --notes "Checked against the originals."
```

Switch shipment with `CASE_DIR` in `.env` (`../cases/ceramic-tiles-cn`), or upload a new one from the console.

## Structure

```
agent/
  customs_agent/     the agentic loop and the SAD playbook (system_instructions.md)
  agent_kit/         tools (one file each), case record with quote-checked facts, tariff lookup, settings
  verification/      checklist check, declaration rules, claims judge
  tests/             offline tests with a fake model
adapters/            SAD PDF, SAD XML, ASYCUDA stub
tariff/gm.json       Gambia tariff pack: exchange rates, levies, HS schedule
cases/               shipments: objective.md + documents/ (+ rendered pages/)
ground_truth/        hidden reference per case for the checklist check
ui/                  ClearFirst console (single HTML page + small Python server)
```

## Meta tooling

- **Muse Code** wrote every line of code in this repository, from the agentic loop to the console, directed through prompts over the hackathon.
- **Muse Spark 1.3** is the agent: reads page images, sets the checklist, records facts, justifies HS codes, drafts the declaration; a second Spark instance is the claims judge.
- **SAM 3.1** segments signatures and stamps for the signature consistency check.
- Meta Model API via the OpenAI-compatible Responses API with tool calling.

## Origins

ClearFirst started from Meta's `legal-agent-workshop` kit (an agentic loop with a case record, quote-checked facts and a verification layer for legal memos). Everything domain-specific is new: the SAD declaration schema and rules, two-document support, discrepancy filing, the tariff pack and duty computation, the signature check with SAM, the export adapters, the two shipments with ground truth, and the ClearFirst console.

## Roadmap

- ASYCUDA World DTI integration through `adapters/asycuda_stub.py`
- Tariff packs for Senegal, Ghana, Nigeria, Sierra Leone (same schema)
- Broker accounts and per-shipment audit export
- Learning from queried declarations: what customs actually challenged

## Disclaimer

All companies, TINs, vessel voyages and document numbers in `cases/` are fictional. Tariff rates are transcribed for demonstration; a deployment loads the current schedule from the revenue authority.
