"""The Customs Agent: the agentic loop. Not implemented yet.

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
    instructions = (Path(__file__).resolve().parent / "system_instructions.md").read_text()
    objective = (case_dir(root) / "objective.md").read_text()
    run_id = progress.new_run(root, instructions=instructions, objective=objective)
    messages: list = [{"role": "user", "content": objective}]
    return _drive(root, client, run_id, messages, instructions, limit=turns)


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
    instructions = (Path(__file__).resolve().parent / "system_instructions.md").read_text()
    messages: list = _without_reasoning(saved["messages"]) + [
        {"role": "user", "content": step["message"]}
    ]
    limit = saved["turn"] + turns
    return _drive(root, client, run_id, messages, instructions, limit=limit)


def _without_reasoning(messages: list) -> list:
    """Messages minus reasoning items, whose server-side refs expire on long pauses.

    Never drops function_call or function_call_output items: tool history stays.
    """
    return [m for m in messages if _field(m, "type") != "reasoning"]


def _is_expired_reasoning(error: Exception) -> bool:
    """A 400 whose message blames a reasoning item (expired server-side ref)."""
    status = getattr(error, "status_code", None)
    text = str(error).lower()
    return (status == 400 or "400" in text) and "reasoning" in text


def _respond(client: OpenAI, instructions: str, messages: list, offered: list):
    """One model call; on an expired-reasoning 400, retry once without reasoning."""
    try:
        return client.responses.create(
            model=model(), instructions=instructions, input=messages, tools=offered
        )
    except Exception as error:
        if _is_expired_reasoning(error) and any(
            _field(m, "type") == "reasoning" for m in messages
        ):
            messages[:] = _without_reasoning(messages)
            return client.responses.create(
                model=model(), instructions=instructions, input=messages, tools=offered
            )
        raise


def _drive(
    root: Path, client: OpenAI, run_id: str, messages: list, instructions: str, limit: int
) -> dict:
    """Drive the run until `limit` total turns, then pause. Each iteration is one turn."""
    while True:
        turn = progress.load_progress(root, run_id)["turn"]
        if turn >= limit:
            break
        if turn + 1 >= limit:
            messages.append(
                {
                    "role": "user",
                    "content": "This is your last turn. File your declaration now with submit_declaration using what you have.",
                }
            )
        try:
            response = _respond(
                client, instructions, messages, tools.definitions(root, run_id)
            )
        except Exception as error:
            note = f"{type(error).__name__}: {error}"[:300]
            progress.save_progress(root, run_id, messages, status="paused", error=note)
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
