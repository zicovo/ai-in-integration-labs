#!/usr/bin/env python3
"""Check that one-governed-call's seeded failure still fails.

`.ai/PEDAGOGY.md` requires a deliberate failure in every lab, and in one-governed-call it is seeded state: a
second virtual model name whose tool calls name connection 4417 instead of 4471. The learner's
schema check passes that call and their content check catches it, which is the whole lesson.

A seeded failure that stops failing is worse than no lab: the room runs the exercise, every check
is green, and nobody learns what the green meant. So it is checked by code, like everything else
that a model might quietly stop doing (AGENTS.md rule 11).

Run it before every delivery, and after any change to the seeded instruction in
labs/stack/model-seed/app.py or to one-governed-call's tool description.

Exit code 0 when the failure still fires on `aquaflux-alt` and does not fire on
`aquaflux-default`.
"""

from __future__ import annotations

import json
import os
import sys

import requests

GATEWAY = os.environ.get("AQUAFLUX_GATEWAY", "https://models.aquaflux.internal:4000")
KEY = os.environ.get("LAB_GATEWAY_KEY", "sk-aquaflux-lab")
HEADERS = {"Authorization": f"Bearer {KEY}"}
RUNS = int(os.environ.get("AQUAFLUX_RUNS", "5"))

# one-governed-call's worked tier verbatim.
DESCRIPTION = (
    "Return the meter readings for one Aquaflux connection over a period. "
    "Use it whenever a question is about consumption or a bill. "
    "Use the connection id exactly as given in the question."
)
INSTRUCTIONS = (
    "You explain water consumption to Aquaflux service desk staff. "
    "Use the tool for readings. Never guess a value."
)
QUESTION = (
    "why is the bill for connection 4471 so high between 2026-01-01 and 2026-06-30, "
    "and can we check the meter?"
)


def tool(description: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "get_meter_readings",
            "description": description,
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


def connection_ids(model: str, description: str, runs: int) -> list[str]:
    out = []
    for _ in range(runs):
        message = requests.post(
            f"{GATEWAY}/v1/chat/completions",
            headers=HEADERS,
            timeout=300,
            json={
                "model": model,
                "temperature": 0,
                "tools": [tool(description)],
                "messages": [
                    {"role": "system", "content": INSTRUCTIONS},
                    {"role": "user", "content": QUESTION},
                ],
            },
        ).json()["choices"][0]["message"]
        calls = message.get("tool_calls") or []
        out.append(
            json.loads(calls[0]["function"]["arguments"]).get("connection_id") if calls else "no call"
        )
    return out


def main() -> int:
    failures = []

    default = connection_ids("aquaflux-default", DESCRIPTION, RUNS)
    right = sum(1 for c in default if c == "4471")
    print(f"aquaflux-default  asked for {default}")
    if right != RUNS:
        failures.append(
            f"aquaflux-default named connection 4471 in only {right} of {RUNS} runs. "
            "one-governed-call's check set has to be green on every one of these."
        )

    alt = connection_ids("aquaflux-alt", DESCRIPTION, RUNS)
    transposed = sum(1 for c in alt if c == "4417")
    print(f"aquaflux-alt      asked for {alt}")
    if transposed == 0:
        failures.append(
            "aquaflux-alt never transposed the connection. The seeded failure is not firing, so "
            "one-governed-call's content check has nothing to catch and the lab teaches nothing. Re-measure "
            "the seeded instruction in labs/stack/model-seed/app.py."
        )

    if failures:
        print()
        for line in failures:
            print(f"  FAIL  {line}", file=sys.stderr)
        return 1

    print(f"\nSeeded failure fires: {transposed} of {RUNS} runs on aquaflux-alt name 4417.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
