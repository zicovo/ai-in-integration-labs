#!/usr/bin/env python3
"""The Aquaflux collections agent: one dunning case, one named configuration.

This is the agent break-it-then-fix-it runs, and it shares its plumbing with the reading assistant in `ask.py`:
sign the person in, exchange for a token the agent holds while acting for them, hand the gateway's
catalogue to the model unchanged, call what it chooses, print what it says. What is different is
in the configuration file, and the configuration file is the lab:

    tools          which of the gateway's tools this agent is given. The weak configuration
                   holds the executing tool; a proposing-only one does not
    token_exchange how wide a token it asks for. The weak one asks for everything Els may do
    instructions   the system prompt, which is where everybody puts the first fix

`aqx run collections-agent --case 4471 --config weak` is how a handout says it. The configuration
is read from config/collections-agent.yaml where you stand, or from labs/break-it-then-fix-it/ if there is none,
so a learner editing their own copy runs their own copy.

Nothing here reads the customer note. The model does, through `read_dunning_state`, and what it
does next is the point.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

import requests
import yaml

import ask  # the reading assistant's plumbing, from the same directory
import telemetry

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
IDP = os.environ.get("AQUAFLUX_IDP", "https://idp.aquaflux.internal/realms/aquaflux")
TOOLS = os.environ.get("AQUAFLUX_TOOLS", "https://tools.aquaflux.internal:4444")
CIS = os.environ.get("AQUAFLUX_CIS", "https://cis.aquaflux.internal")


def find_config(explicit: str | None) -> pathlib.Path:
    for candidate in ([pathlib.Path(explicit)] if explicit else []) + [
        pathlib.Path("config/collections-agent.yaml"),
        REPO / "labs" / "break-it-then-fix-it" / "config" / "collections-agent.yaml",
    ]:
        if candidate.is_file():
            return candidate
    raise SystemExit("no config/collections-agent.yaml here and none in labs/break-it-then-fix-it/")


def token(document: dict, config: dict) -> str:
    """Els's authority, carried by the agent, as wide as the configuration asks for."""
    endpoint = f"{IDP}/protocol/openid-connect/token"
    person = document["acts_for"]
    password = os.environ.get(f"LAB_{person.upper()}_PASSWORD", person)
    exchange = config["token_exchange"]

    person_token = requests.post(endpoint, data={
        "grant_type": "password", "client_id": "service-desk",
        "username": person, "password": password,
        "scope": "openid " + exchange["scope"],
    }, timeout=30)
    person_token.raise_for_status()

    secret = os.environ.get("LAB_COLLECTIONS_AGENT_SECRET", "collections-agent-secret")
    agent_token = requests.post(endpoint, data={
        "grant_type": "client_credentials", "client_id": document["agent"], "client_secret": secret,
    }, timeout=30)
    agent_token.raise_for_status()

    exchanged = requests.post(endpoint, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "client_id": document["agent"], "client_secret": secret,
        "subject_token": person_token.json()["access_token"],
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "actor_token": agent_token.json()["access_token"],
        "actor_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "audience": exchange["audience"], "scope": exchange["scope"],
    }, timeout=30)
    if exchanged.status_code >= 400:
        raise SystemExit(f"the exchange failed: {exchanged.text[:300]}")
    return exchanged.json()["access_token"]


def load_fixture(name: str, case: str) -> None:
    response = requests.post(f"{CIS}/dunning/{case}/_fixture", json={"note": name}, timeout=30)
    if response.status_code >= 400:
        raise SystemExit(f"could not load fixture {name}: {response.text[:200]}")


def reset_case(case: str, fixture: str | None) -> str:
    """Put the case back the way the seed left it, carrying the note asked for.

    A dunning case moves when the agent acts on it: a reminder advances its state, a proposal
    leaves it awaiting a team lead. break-it-then-fix-it runs the same case five or six times and reads what the
    note did each time, so every run starts from the seeded state, the way the measurements in
    `check_collections_agent.py` do. Without this, the third run finds a case that is already
    proposed and does nothing, whatever the note says, and step five has no refusal to show.
    """
    if fixture is None:
        active = requests.get(f"{CIS}/dunning/_fixtures", timeout=30)
        fixture = active.json().get("active", "note-variant-a") if active.ok else "note-variant-a"
    requests.post(f"{CIS}/dunning/_reset", timeout=30).raise_for_status()
    load_fixture(fixture, case)
    return fixture


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the collections agent against one dunning case.")
    parser.add_argument("--case", required=True, help="the connection id of the dunning case")
    parser.add_argument("--config", default="weak", help="a named configuration in the file")
    parser.add_argument("--config-file", default=None, help="which file (default: ./config/collections-agent.yaml)")
    parser.add_argument("--fixture", default=None, help="load this note onto the case first")
    parser.add_argument("--json", action="store_true", help="print the whole run as JSON")
    args = parser.parse_args()

    path = find_config(args.config_file)
    document = yaml.safe_load(path.read_text())
    if args.config not in document["configs"]:
        raise SystemExit(f"no configuration called {args.config} in {path}. "
                         f"There is {', '.join(sorted(document['configs']))}.")
    config = document["configs"][args.config]

    fixture = reset_case(args.case, args.fixture)
    if not args.json:
        print(f"\n  case {args.case} starts from its seeded state, carrying the note {fixture}")

    # The catalogue the gateway publishes, narrowed to what this configuration gives the agent.
    # The narrowing is the agent's own configuration, not the gateway's, which is why break-it-then-fix-it's
    # weak state is an over-broad list here and not a gateway setting.
    published = {tool["name"]: tool for tool in ask.catalogue()}
    missing = [name for name in config["tools"] if name not in published]
    if missing:
        raise SystemExit(f"the gateway does not publish {', '.join(missing)}; "
                         "run labs/stack/smoke.sh break-it-then-fix-it to register the collections tools")
    tools = [published[name] for name in config["tools"]]

    bearer = token(document, config)
    instructions = config["instructions"].strip()
    task = document["task"].format(case=args.case)
    messages = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": task},
    ]

    # One trace per run, like the reading assistant's. The spans underneath come from ask.py.
    tracer = telemetry.setup(document["agent"])
    transcript: list[dict] = []
    with telemetry.start_run(tracer, document["agent"], document["acts_for"], instructions, task,
                             **{"aquaflux.case_id": args.case, "aquaflux.agent.config": args.config,
                                "aquaflux.fixture": fixture}):
        run_trace_id = telemetry.trace_id()
        reply = ask.ask_model(messages, ask.as_openai(tools), model=document.get("model"))
        for _round in range(8):
            calls = reply.get("tool_calls") or []
            if not calls:
                break
            messages.append({"role": "assistant", "content": reply.get("content"), "tool_calls": calls})
            for call in calls:
                name = call["function"]["name"]
                try:
                    arguments = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    arguments = {"_unparseable": call["function"]["arguments"]}
                result, status = ask.call_tool(name, arguments, bearer, call.get("id"))
                decision = (result.get("result") or {}).get("_gateway", {}).get("decision") \
                    or (result.get("error") or {}).get("data", {}).get("decision")
                transcript.append({"tool": name, "arguments": arguments, "status": status,
                                   "decision": decision, "result": result})
                if not args.json:
                    print(f"\n  the agent called:  {name}")
                    print(f"  with arguments:    {json.dumps(arguments)}")
                    print(f"  the gateway said:  {status}  decision {decision}")
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": json.dumps(result.get("result") or result.get("error") or result)[:3000]})
            reply = ask.ask_model(messages, ask.as_openai(tools), model=document.get("model"))

    if args.json:
        print(json.dumps({"case": args.case, "config": args.config, "fixture": fixture,
                          "trace_id": run_trace_id, "calls": transcript,
                          "answer": reply.get("content")}, indent=2))
    else:
        if not transcript:
            print("\n  the agent called no tool.")
        print(f"\n  {reply.get('content') or '(no answer)'}\n")
        print(f"  Read the decision log:  aqx log --last {max(len(transcript), 1)}")
        if telemetry.exporting():
            print(f"  Read the trace:         aqx trace {run_trace_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
