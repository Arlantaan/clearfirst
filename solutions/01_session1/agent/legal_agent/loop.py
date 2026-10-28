"""The Legal Agent: the agentic loop.

Each turn: ask the model what to do next, run the one tool it picks (agent_kit.tools),
send the result back, save progress. Stops when the result says the run must stop (memo
filed, a person needed), at the turn limit, or if the Model API keeps failing ("paused").
"""

from __future__ import annotations

import json
from pathlib import Path

import openai
from agent_kit import settings, tools
from agent_kit.progress import load_progress, new_run, resume, save_progress
from openai import OpenAI


def instructions() -> str:
    """The agent's behaviour: system_instructions.md, sent unchanged as the system prompt."""
    return (Path(__file__).parent / "system_instructions.md").read_text()


def user(text: str) -> dict:
    return {"role": "user", "content": text}


def tool_output(call_id: str, result: dict) -> dict:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps(result),
    }


def drive(
    client: OpenAI, root: Path, run_id: str, messages: list, turn: int, last_turn: int
) -> dict:
    status = "running"
    while status == "running":
        turn += 1
        if turn == last_turn:
            messages.append(
                user("This is your last turn. Call submit_memo now with what you have.")
            )
        try:
            response = client.responses.create(  # plan: the model picks the next step
                model=settings.model(),
                instructions=instructions(),
                input=messages,
                tools=tools.definitions(root, run_id),
                parallel_tool_calls=False,
                store=False,  # the whole conversation is kept in messages and sent every turn
            )
        except openai.APIError as error:  # still failing after the SDK's retries
            save_progress(root, run_id, messages, status="paused", error=str(error))
            return {
                "run_id": run_id,
                "status": "paused",
                "turn": turn - 1,
                "note": str(error),
            }
        messages += response.output
        calls = [item for item in response.output if item.type == "function_call"]
        if calls:
            result = tools.run(client, root, run_id, calls[0])  # act
            messages.append(tool_output(calls[0].call_id, result))  # observe
            status = result.get("status", "running")
        else:
            messages.append(user("Plain text is not accepted. Call exactly one tool."))
        if status == "running" and turn >= last_turn:
            status = "paused"
        save_progress(root, run_id, messages, response, status=status)
    return {"run_id": run_id, "status": status, "turn": turn}


def run_agent(*, root: Path, client: OpenAI, turns: int = 30) -> dict:
    objective = (settings.case_dir(root) / "objective.md").read_text()
    run_id = new_run(root, instructions=instructions(), objective=objective)
    return drive(client, root, run_id, [user(objective)], 0, turns)


def resume_run(*, root: Path, run_id: str, client: OpenAI, turns: int = 15) -> dict:
    """Continue a stopped run: after the turn limit, a person's answer, or the attorney's review."""
    step = resume(root, run_id)
    if step["message"] is None:
        return {"run_id": run_id, "status": step["status"], "note": step["note"]}
    progress = load_progress(root, run_id)
    messages = progress["messages"] + [user(step["message"])]
    return drive(
        client, root, run_id, messages, progress["turn"], progress["turn"] + turns
    )
