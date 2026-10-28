"""The Legal Agent: the agentic loop. Not implemented yet.

run_agent works the case; resume_run continues a run that stopped.
"""

from __future__ import annotations

import json
from pathlib import Path

from openai import OpenAI

from agent_kit import progress, tools
from agent_kit.settings import case_dir, model


def run_agent(*, root: Path, client: OpenAI, turns: int = 30) -> dict:
    root = Path(root)
    instructions = (root / "legal_agent/system_instructions.md").read_text()
    objective = (case_dir(root) / "objective.md").read_text()
    run_id = progress.new_run(root, instructions=instructions, objective=objective)
    messages: list = [{"role": "user", "content": objective}]
    return _drive(root, client, run_id, messages, instructions, turns)


def resume_run(*, root: Path, run_id: str, client: OpenAI, turns: int = 15) -> dict:
    root = Path(root)
    saved = progress.load_progress(root, run_id)
    step = progress.resume(root, run_id)
    if step["message"] is None:
        return {
            "run_id": run_id,
            "status": step["status"],
            "turn": saved["turn"],
            "note": step.get("note", ""),
        }
    instructions = (root / "legal_agent/system_instructions.md").read_text()
    messages: list = list(saved["messages"]) + [
        {"role": "user", "content": step["message"]}
    ]
    return _drive(root, client, run_id, messages, instructions, turns)


def _drive(
    root: Path, client: OpenAI, run_id: str, messages: list, instructions: str, turns: int
) -> dict:
    for i in range(turns):
        if i == turns - 1:
            messages.append(
                {
                    "role": "user",
                    "content": "This is your last turn. File your memo now with submit_memo using what you have.",
                }
            )
        try:
            response = client.responses.create(
                model=model(),
                instructions=instructions,
                input=messages,
                tools=tools.definitions(root, run_id),
            )
        except Exception:
            progress.save_progress(root, run_id, messages, status="paused")
            saved = progress.load_progress(root, run_id)
            return {"run_id": run_id, "status": "paused", "turn": saved["turn"]}
        messages += response.output
        call = _first_call(response.output)
        if call is None:
            messages.append(
                {
                    "role": "user",
                    "content": "Call exactly one tool per turn. Never answer in plain text.",
                }
            )
            progress.save_progress(root, run_id, messages, response)
            continue
        result = tools.run(client, root, run_id, call)
        messages.append(
            {
                "type": "function_call_output",
                "call_id": _field(call, "call_id"),
                "output": json.dumps(result),
            }
        )
        status = result.get("status", "running")
        if status != "running":
            progress.save_progress(root, run_id, messages, response, status=status)
            saved = progress.load_progress(root, run_id)
            return {"run_id": run_id, "status": status, "turn": saved["turn"]}
        progress.save_progress(root, run_id, messages, response)
    progress.save_progress(root, run_id, messages, status="paused")
    saved = progress.load_progress(root, run_id)
    return {"run_id": run_id, "status": "paused", "turn": saved["turn"]}


def _first_call(output: list):
    for item in output or []:
        if _field(item, "type") == "function_call":
            return item
    return None


def _field(call: object, key: str) -> object:
    if isinstance(call, dict):
        return call.get(key)
    return getattr(call, key, None)
