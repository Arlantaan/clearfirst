# ClearFirst Broker Console (`ui/`)

The broker-facing product: pick a shipment, have the agent prepare its SAD
declaration, watch the plan-act-observe timeline, review discrepancies and open
questions, sign off, and export the declaration as PDF or XML.

## Run

From the `clearfirst` folder:

```bash
python3 ui/ui.py
# open http://127.0.0.1:8765
```

It finds the project automatically (the folder that contains `ui/`).
`--project PATH` points it at a different clone; `--port` changes the port.
Python standard library only (PDF export needs reportlab on the console's
Python). Binds to 127.0.0.1.

## What the broker sees

- **Shipments** (left): one entry per folder under `cases/`, with the status of
  its latest run. **+ New shipment** uploads documents (PDF, JPG, PNG) into a
  new case folder and renders their page images.
- **Prepare declaration**: starts a run with 40 turns. The progress strip shows
  turn, facts, checks passed, refusals, and flags.
- **Timeline**: one card per turn. **Plan**: the agent's model call (tokens).
  **Act**: the one tool it chose and its arguments. **Observe**: what came
  back, coloured by outcome. Click a turn's header for **what the model saw
  and decided**.
- **Declaration**: the SAD as numbered boxes with citations, the duty estimate,
  discrepancies in amber, and open questions.
- **Broker sign-off**: flags to confirm, notes, **Approve** / **Send back**.
  After approval, **Export** downloads the SAD PDF or XML.
- **Handoff card** (the agent is waiting): what is blocked and why; reply to
  the agent and resume, or add the missing documents to the inbox and resume.
- **Developer** (bottom): tools available, raw state, raw case record,
  verify-this-run.

Money shows with thousands separators and two decimals (GMD 1,508,430.00),
weights with separators and no trailing decimals (28,560 kg).

## What it uses from the project

- Reads: `agent/workspace/runs/<run>/progress.json` (the conversation and each
  turn's tokens, saved by `agent_kit.progress`), `agent/workspace/case_records/<run>.json`,
  page images, `agent/.env` (only for CASE_DIR, the verification setting, and
  whether a key is set; the key itself is never sent to the browser), and each
  case folder's objective and page images.
- Runs: `./helper run [--resume]`, `./helper review`, `./helper verify`,
  `./helper branch`, `./helper reset`, `./helper describe`.
- Renders new shipments' page images with `agent_kit.page_images`.
- Writes `agent/workspace/control.json` (step mode), which `agent_kit.progress`
  reads after each saved turn, and the `CASE_DIR` line of `agent/.env` when you
  switch shipment (nothing else in `.env` is touched).
- Never imports the agent.
