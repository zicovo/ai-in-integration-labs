#!/usr/bin/env python3
"""Check that the model behind the gateway can do what the labs require of it.

one-governed-call's handout says this is checked by the smoke test "because [these capabilities] depend on the
model the stack was built with", and HANDOFF-LAB.md puts it on the list to verify before every
delivery. It is checked here, by code, rather than trusted, because the model is the most
swappable thing in the stack and the least likely to announce that it has changed.

Two capabilities, and the labs fail differently without each:

    tool calling     one-governed-call, expose-one-operation, survive-the-crash and break-it-then-fix-it all turn on a model proposing a tool call. Without
                     it there is no lab, only a chat window.
    strict JSON      one-governed-call's output schema and ground-the-answer's judged scoring parse the reply. Without it
                     the learner debugs a parser instead of learning where the boundary is.

Exit code 0 when both work.
"""

from __future__ import annotations

import json
import os
import sys

import requests

GATEWAY = os.environ.get("AQUAFLUX_GATEWAY", "https://models.aquaflux.internal:4000")
KEY = os.environ.get("LAB_GATEWAY_KEY", "sk-aquaflux-lab")
MODEL = os.environ.get("AQUAFLUX_CHECK_MODEL", "aquaflux-default")
HEADERS = {"Authorization": f"Bearer {KEY}"}

TOOL = {
    "type": "function",
    "function": {
        "name": "get_meter_readings",
        "description": (
            "Return the meter readings for one Aquaflux connection over a period. "
            "Use it whenever a question is about consumption or a bill. "
            "Use the connection id exactly as given in the question."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "string", "description": "The Aquaflux connection id, digits only"},
                "from": {"type": "string", "format": "date"},
                "to": {"type": "string", "format": "date"},
            },
            "required": ["connection_id", "from", "to"],
            "additionalProperties": False,
        },
    },
}

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "confidence": {"type": "number"},
        "proposed_action": {"type": "string", "enum": ["none", "meter_check", "contact_customer"]},
    },
    "required": ["explanation", "confidence", "proposed_action"],
    "additionalProperties": False,
}


def post(body: dict) -> dict:
    reply = requests.post(
        f"{GATEWAY}/v1/chat/completions", headers=HEADERS, json=body, timeout=300
    )
    reply.raise_for_status()
    return reply.json()["choices"][0]["message"]


def fail(what: str, detail: str) -> None:
    print(f"      {what}: {detail}", file=sys.stderr)


def check_tool_calling() -> bool:
    message = post(
        {
            "model": MODEL,
            "temperature": 0,
            "tools": [TOOL],
            "messages": [
                {"role": "system", "content": "Use the tool for readings. Never guess a value."},
                {
                    "role": "user",
                    # one-governed-call's question verbatim, billing period included. Without the period the
                    # tool's required `from` and `to` have no answer, the instructions forbid
                    # guessing, and every model measured resolved that contradiction by inventing
                    # arguments rather than by asking. Keep this in step with the handout.
                    "content": (
                        "why is the bill for connection 4471 so high between 2026-01-01 and "
                        "2026-06-30, and can we check the meter?"
                    ),
                },
            ],
        }
    )
    calls = message.get("tool_calls") or []
    if not calls:
        fail("tool calling", f"the model answered in prose instead of calling a tool: {message.get('content')!r}")
        return False
    try:
        args = json.loads(calls[0]["function"]["arguments"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        fail("tool calling", f"the arguments did not parse as JSON: {error}")
        return False
    if calls[0]["function"]["name"] != "get_meter_readings":
        fail("tool calling", f"called {calls[0]['function']['name']!r}, expected get_meter_readings")
        return False
    if "connection_id" not in args:
        fail("tool calling", f"the call omitted the required connection_id: {args}")
        return False
    return True


def check_structured_output() -> bool:
    message = post(
        {
            "model": MODEL,
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "answer", "schema": ANSWER_SCHEMA, "strict": True},
            },
            "messages": [
                {"role": "system", "content": "You explain water consumption to Aquaflux service desk staff."},
                {
                    "role": "user",
                    "content": "Consumption on connection 4471 doubled in March. Explain it and propose an action.",
                },
            ],
        }
    )
    try:
        answer = json.loads(message["content"])
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        fail("strict JSON", f"the reply did not parse: {error}. Reply was {message.get('content')!r}")
        return False
    missing = {"explanation", "confidence", "proposed_action"} - set(answer)
    if missing:
        fail("strict JSON", f"the reply is missing {sorted(missing)}: {answer}")
        return False
    if answer["proposed_action"] not in ("none", "meter_check", "contact_customer"):
        fail("strict JSON", f"proposed_action {answer['proposed_action']!r} is outside the enum")
        return False
    return True


def main() -> int:
    try:
        tools_ok = check_tool_calling()
        json_ok = check_structured_output()
    except requests.RequestException as error:
        fail("gateway", str(error))
        return 1
    if tools_ok and json_ok:
        return 0
    print(
        "      The model behind the gateway cannot do what one-governed-call needs. Swap the model in\n"
        "      labs/stack/docker-compose.yml (AQUAFLUX_MODEL) and re-run, or ship the recorded\n"
        "      run sets instead, as the handout's instructor note allows.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
