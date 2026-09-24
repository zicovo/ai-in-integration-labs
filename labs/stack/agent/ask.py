#!/usr/bin/env python3
"""The Aquaflux reading assistant: one question, whatever tools the gateway currently publishes.

This is the agent c-02 runs. It is deliberately small enough to read in one sitting, because the
lab is about what the model does with a tool catalogue and everything else here is scaffolding:

    1. sign in as Nadia, and exchange her token for one the agent holds while acting for her
    2. ask the tool gateway what it publishes, and hand those schemas to the model unchanged
    3. let the model choose
    4. make the call it chose, through the gateway, with the exchanged token
    5. give the result back to the model and print what it says

Step two is the line that matters. The descriptions and schemas the model sees are the ones the
learner wrote, transcribed by the SDK and passed on by the gateway. Nothing in this file improves
them, and that is why the lab works: whatever the model books, the catalogue let it.

`--token` prints the exchanged token and stops, so c-02's worked tier can make one call by hand
with the same identity the agent uses, and read the two log lines side by side. d-02 is where the
token is the lesson; here it is plumbing.

Every run is one trace (telemetry.py): a root span for the run, a `chat` span per model call and
an `execute_tool` span per tool call, with `traceparent` sent to both gateways so their spans
join it. d-04 is the lab that reads it, and its second seeded fault lives in `call_tool()` below:
the work order API returns an id, the gateway passes it on, and nothing here writes it, or the
idempotency key, onto the span. Two lines, and the handout has the learner add them.

Run it through `labs/stack/ask.sh`.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

import requests

import telemetry  # the spans, from the same directory

HERE = pathlib.Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "reading-assistant.json").read_text())

IDP = os.environ.get("AQUAFLUX_IDP", "https://idp.aquaflux.internal/realms/aquaflux")
TOOLS = os.environ.get("AQUAFLUX_TOOLS", "https://tools.aquaflux.internal:4444")
MODELS = os.environ.get("AQUAFLUX_GATEWAY", "https://models.aquaflux.internal:4000")
MODEL_KEY = os.environ.get("LAB_GATEWAY_KEY", "sk-aquaflux-lab")
TIMEOUT = 300
SYSTEM_PROMPT = "\n".join(CONFIG["system_prompt"])

tracer = telemetry.setup(CONFIG["client_id"])


def token() -> str:
    """Nadia's authority, carried by the agent. d-02 is the lab about this; here it is plumbing."""
    endpoint = f"{IDP}/protocol/openid-connect/token"
    person = requests.post(
        endpoint,
        data={
            "grant_type": "password",
            "client_id": "service-desk",
            "username": CONFIG["acts_for"],
            "password": os.environ.get("LAB_NADIA_PASSWORD", "nadia"),
            # The service desk console can do everything Nadia can do, so her own token
            # carries all four scopes. Narrowing to the one the tool needs is the
            # exchange's job, and the exchange below is where it does not happen.
            "scope": "openid meter:read workorder:create workorder:read workorder:close",
        },
        timeout=30,
    )
    person.raise_for_status()

    agent = requests.post(
        endpoint,
        data={
            "grant_type": "client_credentials",
            "client_id": CONFIG["client_id"],
            "client_secret": os.environ.get("LAB_AGENT_SECRET", "reading-assistant-secret"),
        },
        timeout=30,
    )
    agent.raise_for_status()

    exchange = CONFIG["token_exchange"]
    exchanged = requests.post(
        endpoint,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "client_id": CONFIG["client_id"],
            "client_secret": os.environ.get("LAB_AGENT_SECRET", "reading-assistant-secret"),
            "subject_token": person.json()["access_token"],
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "actor_token": agent.json()["access_token"],
            "actor_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "audience": exchange["audience"],
            "scope": exchange["scope"],
        },
        timeout=30,
    )
    exchanged.raise_for_status()
    return exchanged.json()["access_token"]


def catalogue() -> list[dict]:
    response = requests.get(f"{TOOLS}/tools", timeout=30)
    response.raise_for_status()
    return response.json()


def as_openai(tools: list[dict]) -> list[dict]:
    """MCP tool definitions, in the shape the model gateway's API wants.

    A rename and a reshuffle, nothing more. The description and the schema cross unchanged,
    which is the whole reason a tool description is worth arguing about.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["inputSchema"],
            },
        }
        for tool in tools
    ]


def returned_work_order(result: dict) -> dict | None:
    """The work order in a tool result, when the tool returned one. The API returns it; the
    curated server passes it through, with `created: false` when the API answered 409 with the
    original for a key it had seen before; the gateway lifts the id onto its own log line."""
    inner = result.get("result") or {}
    for blob in [inner.get("structuredContent"), inner.get("structured_content")] + [
        item.get("text") for item in inner.get("content") or [] if isinstance(item, dict)
    ]:
        if isinstance(blob, str):
            try:
                blob = json.loads(blob)
            except ValueError:
                continue
        if isinstance(blob, dict) and blob.get("work_order_id"):
            return blob
    return None


def returned_work_order_id(result: dict) -> str | None:
    order = returned_work_order(result)
    return str(order["work_order_id"]) if order else None


def call_tool(name: str, arguments: dict, bearer: str, call_id: str | None = None) -> tuple[dict, int]:
    """One tool call through the gateway, on its own span.

    The span carries the tool, the argument hash and the gateway's call id. It does not carry
    what the tool created: the API returned a work order id and the adapter's job was to create
    the work order, which it did. d-04 finds out what that costs.
    """
    with tracer.start_as_current_span(f"execute_tool {name}") as span:
        telemetry.record_tool_call(span, name, arguments, call_id)
        response = requests.post(
            f"{TOOLS}/mcp",
            headers=telemetry.headers({"Authorization": f"Bearer {bearer}",
                                       "Content-Type": "application/json"}),
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            timeout=TIMEOUT,
        )
        result = response.json()
        telemetry.record_tool_result(span, result, response.status_code)
        return result, response.status_code


def ask_model(messages: list[dict], tools: list[dict], model: str | None = None) -> dict:
    requested = model or CONFIG["model"]
    body = {"model": requested, "messages": messages, "temperature": 0}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    with tracer.start_as_current_span(f"chat {requested}") as span:
        response = requests.post(
            f"{MODELS}/v1/chat/completions",
            headers=telemetry.headers({"Authorization": f"Bearer {MODEL_KEY}"}),
            json=body,
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        answer = response.json()
        telemetry.record_model_call(span, requested, messages, answer, dict(response.headers))
        return answer["choices"][0]["message"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the reading assistant against the gateway.")
    parser.add_argument("question", nargs="*", help="what to ask")
    parser.add_argument("--dump-tools", action="store_true",
                        help="print the schemas the model is given, and stop")
    parser.add_argument("--json", action="store_true", help="print the whole run as JSON")
    parser.add_argument("--token", action="store_true",
                        help="print the token the agent would call the gateway with, and stop")
    args = parser.parse_args()

    if args.token:
        print(token())
        return 0

    tools = catalogue()

    if args.dump_tools:
        print(json.dumps(as_openai(tools), indent=2))
        return 0

    if not args.question:
        parser.error("say what to ask, or pass --dump-tools or --token")

    question = " ".join(args.question)
    bearer = token()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]

    with telemetry.start_run(tracer, CONFIG["client_id"], CONFIG["acts_for"], SYSTEM_PROMPT,
                             question):
        run_trace_id = telemetry.trace_id()
        # An agent loop, not a single call. The model may read before it writes, and with a
        # twenty-three tool catalogue it usually does. `rounds` is a stop, not a design: an agent
        # that has not finished in six turns is not going to.
        transcript: list[dict] = []
        reply = ask_model(messages, as_openai(tools))

        for _round in range(6):
            calls = reply.get("tool_calls") or []
            if not calls:
                break

            messages.append({"role": "assistant", "content": reply.get("content"),
                             "tool_calls": calls})

            for call in calls:
                name = call["function"]["name"]
                try:
                    arguments = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    arguments = {"_unparseable": call["function"]["arguments"]}

                result, status = call_tool(name, arguments, bearer, call.get("id"))
                transcript.append({"tool": name, "arguments": arguments, "status": status,
                                   "result": result})

                if not args.json:
                    order = returned_work_order(result)
                    print(f"\n  the model chose: {name}")
                    print(f"  with arguments:  {json.dumps(arguments)}")
                    outcome = ""
                    if order and order.get("created", True) is False:
                        outcome = (f", work order {order['work_order_id']} returned again: the API "
                                   f"answered 409, this key was used before, nothing was created")
                    elif order:
                        outcome = f", work order {order['work_order_id']} created"
                    print(f"  the gateway said: {status}{outcome}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps(result.get("result") or result.get("error") or result)[:2000],
                })

            reply = ask_model(messages, as_openai(tools))

    if args.json:
        print(json.dumps({"question": question, "trace_id": run_trace_id, "calls": transcript,
                          "answer": reply.get("content")}, indent=2))
    else:
        if not transcript:
            print("\n  the model chose no tool.")
        print(f"\n  {reply.get('content') or '(no answer)'}\n")
        # Point at the write, when there was one: the model often reads after it writes, and
        # the last line is then a harmless list_* call rather than the one c-02 asks about.
        writes = [c["tool"] for c in transcript if c["tool"].startswith("create_")]
        query = f"tool={writes[-1]}&limit=1" if writes else "limit=1"
        print(f"  Read the decision log:  curl -s '{TOOLS}/logs?{query}' | python3 -m json.tool")
        if telemetry.exporting():
            print(f"  Read the trace:         aqx trace {run_trace_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
