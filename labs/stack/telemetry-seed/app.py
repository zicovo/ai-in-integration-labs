#!/usr/bin/env python3
"""Seed the trace store with the history d-04 promises: about two hundred past runs.

The handout says the trace store is not empty when the lab starts, and that two of the runs in
it are the ones the regulator asks about: work order 88213 on connection 4471 (the worked tier)
and 91044 on connection 4417 (the completion tier). This writes them, once, the way the agents
would have written them at the time, with two deliberate properties:

  1. No tool span carries the work order id or the idempotency key. That is how the agents were
     instrumented (labs/stack/agent/ask.py, call_tool) and the history is consistent with it.
     Searching the trace store by either one returns nothing, which is the first gap.
  2. Every call has a decision record in the gateway's own file, with the trace id of its run.
     The records are there; the collector does not read the file. That is the second gap.

Run 91044 has one more thing wrong with it, and the completion tier asks the learner to find
it once the decision record is in the same view as the call: the arguments the agent recorded
on its tool span name connection 4471, and the arguments the gateway decided and the work order
system executed name 4417. The two hashes differ. Nothing failed.

The spans go through the collector, not straight to the trace store, so they land in the audit
store as well and the history is the same in both. The decision lines go straight to the file.
Nothing here is named to a learner; it is a fixture, like the seeding proxy in a-02.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

COLLECTOR = os.environ.get("AQUAFLUX_OTLP", "http://collector:4318")
TRACES = os.environ.get("AQUAFLUX_TRACES", "http://traces:16686")
DECISION_LOG = pathlib.Path(os.environ.get("AQUAFLUX_DECISION_LOG", "/var/log/tool-gateway/decisions.jsonl"))
RUNS = int(os.environ.get("AQUAFLUX_SEED_RUNS", "200"))

# The two runs the handouts address. The first trace id is the one d-04's study text prints.
WORKED = {"trace_id": "0af7651916cd43dd8448eb211c80319c", "work_order_id": "88213", "connection": "4471",
          "at": "2026-06-15T10:04:31Z", "key": "wo-88213-a1", "reason": "disputed_reading",
          "question": "the customer on 4471 says their bill doubled, can someone check the meter"}
COMPLETION = {"trace_id": "4c1d2e3f5a6b7c8d9e0f1a2b3c4d5e6f", "work_order_id": "91044", "connection": "4471",
              "executed_connection": "4417", "at": "2026-06-18T14:22:07Z", "key": "wo-91044-b2",
              "reason": "implausible_consumption",
              "question": "consumption on 4471 is three times last year's for March, please have the meter checked"}

CONNECTIONS = ["4471", "4417", "4402", "4418", "4436", "4455", "4462", "4489", "4501", "4523", "4547",
               "4560", "4578", "4591", "4603", "4622", "4640", "4657", "4671", "4688", "4703", "4719"]
PEOPLE = ["nadia", "nadia", "nadia", "tom"]
MODEL_ANSWERED = "deepseek-v4-flash"
PROMPT_VERSION = "reading-assistant/4e1c0b7a"
POLICY_VERSION = "9c4f2a71"


def sha256(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def nanos(when: datetime) -> str:
    return str(int(when.timestamp() * 1_000_000_000))


def attr(key: str, value) -> dict:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": str(value)}}


def span(trace_id: str, span_id: str, parent: str | None, name: str, start: datetime, end: datetime,
         attributes: dict, kind: int = 1) -> dict:
    out = {
        "traceId": trace_id, "spanId": span_id, "name": name, "kind": kind,
        "startTimeUnixNano": nanos(start), "endTimeUnixNano": nanos(end),
        "attributes": [attr(k, v) for k, v in attributes.items() if v is not None],
        "status": {"code": 1},
    }
    if parent:
        out["parentSpanId"] = parent
    return out


def resource_spans(service: str, spans: list[dict]) -> dict:
    return {
        "resource": {"attributes": [attr("service.name", service), attr("service.namespace", "aquaflux"),
                                    attr("deployment.environment.name", "lab")]},
        "scopeSpans": [{"scope": {"name": service}, "spans": spans}],
    }


def one_run(rng: random.Random, trace_id: str, at: datetime, person: str, question: str, tool: str,
            arguments: dict, work_order_id: str | None, gateway_arguments: dict | None = None,
            agent: str = "reading-assistant") -> tuple[list[dict], dict]:
    """One run: the agent's spans, the gateway's span, and the gateway's decision line."""
    ids = iter(f"{rng.getrandbits(64):016x}" for _ in range(8))
    root, chat1, tool_span, gw, chat2 = (next(ids) for _ in range(5))
    t = at
    step = lambda seconds: t + timedelta(seconds=seconds)  # noqa: E731

    agent_spans = [
        span(trace_id, root, None, f"invoke_agent {agent}", t, step(rng.uniform(9, 22)), {
            "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": agent,
            "aquaflux.agent": agent, "aquaflux.person": person,
            "aquaflux.prompt.version": PROMPT_VERSION, "aquaflux.content.captured": True,
            "gen_ai.input.messages": json.dumps([{"role": "user", "content": question}]),
        }),
        span(trace_id, chat1, root, "chat aquaflux-default", step(0.2), step(rng.uniform(2, 5)), {
            "gen_ai.operation.name": "chat", "gen_ai.provider.name": "aquaflux-model-gateway",
            "gen_ai.request.model": "aquaflux-default", "gen_ai.response.model": MODEL_ANSWERED,
            "aquaflux.model.requested": "aquaflux-default", "aquaflux.model.answered": MODEL_ANSWERED,
            "gen_ai.usage.input_tokens": rng.randint(700, 1400), "gen_ai.usage.output_tokens": rng.randint(40, 120),
            "gen_ai.response.finish_reasons": "tool_calls",
        }),
        # The tool span, exactly as the adapter wrote it at the time: tool, argument hash, the
        # gateway's call id, the arguments themselves because capture was on. No work order id,
        # no idempotency key as an attribute of its own.
        span(trace_id, tool_span, root, f"execute_tool {tool}", step(5.1), step(rng.uniform(5.6, 7.2)), {
            "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": tool, "aquaflux.tool": tool,
            "gen_ai.tool.call.id": f"call_{rng.getrandbits(40):010x}",
            "aquaflux.arguments_sha256": sha256(arguments),
            "gen_ai.tool.call.arguments": json.dumps(arguments),
            "aquaflux.gateway.call_id": None, "aquaflux.gateway.status": 200,
            "gen_ai.tool.call.result": json.dumps({"work_order_id": work_order_id, "state": "proposed"}
                                                  if work_order_id else {"state": "scheduled"}),
        }),
        span(trace_id, chat2, root, "chat aquaflux-default", step(7.3), step(rng.uniform(9, 12)), {
            "gen_ai.operation.name": "chat", "gen_ai.provider.name": "aquaflux-model-gateway",
            "gen_ai.request.model": "aquaflux-default", "gen_ai.response.model": MODEL_ANSWERED,
            "aquaflux.model.requested": "aquaflux-default", "aquaflux.model.answered": MODEL_ANSWERED,
            "gen_ai.usage.input_tokens": rng.randint(900, 1600), "gen_ai.usage.output_tokens": rng.randint(30, 90),
        }),
    ]
    call_id = f"{rng.getrandbits(128):032x}"
    call_id = f"{call_id[:8]}-{call_id[8:12]}-{call_id[12:16]}-{call_id[16:20]}-{call_id[20:]}"
    agent_spans[2]["attributes"].append(attr("aquaflux.gateway.call_id", call_id))
    gateway_spans = [
        span(trace_id, gw, tool_span, f"tool_gateway {tool}", step(5.2), step(6.9), {
            "aquaflux.tool": tool, "aquaflux.gateway.call_id": call_id,
            "aquaflux.gateway.policy": "aquaflux.tools", "http.response.status_code": 200,
        }, kind=2),
    ]
    decided = gateway_arguments if gateway_arguments is not None else arguments
    decision = {
        "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"), "call_id": call_id, "trace_id": trace_id, "span_id": gw,
        "agent": agent, "person": person, "actor_claim": "azp", "tool": tool, "server": "curated",
        "arguments": decided, "arguments_sha256": sha256(decided), "decision": "allow",
        "reason": "allowed by rule in_register", "policy": "aquaflux.tools", "policy_version": POLICY_VERSION,
        "rule": "in_register", "approvals": [], "approval_id": None, "work_order_id": work_order_id,
        "tool_error": None, "status": 200, "duration_ms": rng.randint(180, 900),
    }
    return [resource_spans(agent, agent_spans), resource_spans("tool-gateway", gateway_spans)], decision


def history() -> tuple[list[list[dict]], list[dict]]:
    rng = random.Random(88213)
    start = datetime(2026, 3, 2, 8, 0, tzinfo=timezone.utc)
    runs: list[list[dict]] = []
    decisions: list[dict] = []
    next_wo = 87001
    for index in range(RUNS - 2):
        at = start + timedelta(minutes=rng.randint(0, 200 * 24 * 60))
        # Working hours, mostly. A regulator's question is about a Tuesday afternoon, not 3 a.m.
        at = at.replace(hour=rng.choice([8, 9, 10, 10, 11, 13, 14, 14, 15, 16]), minute=rng.randint(0, 59),
                        second=rng.randint(0, 59))
        connection = rng.choice(CONNECTIONS)
        person = rng.choice(PEOPLE)
        if rng.random() < 0.6:
            reason = rng.choice(["disputed_reading", "implausible_consumption", "meter_not_readable"])
            key = f"{rng.getrandbits(128):032x}"
            key = f"{key[:8]}-{key[8:12]}-4{key[13:16]}-{key[16:20]}-{key[20:]}"
            arguments = {"connection_id": connection, "reason": reason, "request_id": key}
            question = rng.choice([
                f"the customer on {connection} disputes the last reading, can we check the meter",
                f"{connection} has used far more than usual this quarter, please arrange a meter check",
                f"the meter at {connection} could not be read, can a technician look at it",
            ])
            wo = str(next_wo); next_wo += rng.randint(1, 3)
            spans, decision = one_run(rng, f"{rng.getrandbits(128):032x}", at, person, question,
                                      "create_meter_check_work_order", arguments, wo)
        else:
            wo_asked = str(rng.randint(85000, 86999))
            arguments = {"work_order_id": wo_asked}
            question = f"what is the status of work order {wo_asked}"
            spans, decision = one_run(rng, f"{rng.getrandbits(128):032x}", at, person, question,
                                      "get_work_order_status", arguments, None)
        runs.append(spans)
        decisions.append(decision)

    worked_at = datetime.strptime(WORKED["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    spans, decision = one_run(
        rng, WORKED["trace_id"], worked_at, "nadia", WORKED["question"], "create_meter_check_work_order",
        {"connection_id": WORKED["connection"], "reason": WORKED["reason"], "request_id": WORKED["key"]},
        WORKED["work_order_id"])
    decision["call_id"] = "seed-88213-" + decision["call_id"][11:]
    runs.append(spans); decisions.append(decision)

    completion_at = datetime.strptime(COMPLETION["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    spans, decision = one_run(
        rng, COMPLETION["trace_id"], completion_at, "nadia", COMPLETION["question"], "create_meter_check_work_order",
        {"connection_id": COMPLETION["connection"], "reason": COMPLETION["reason"], "request_id": COMPLETION["key"]},
        COMPLETION["work_order_id"],
        gateway_arguments={"connection_id": COMPLETION["executed_connection"], "reason": COMPLETION["reason"],
                           "request_id": COMPLETION["key"]})
    decision["call_id"] = "seed-91044-" + decision["call_id"][11:]
    runs.append(spans); decisions.append(decision)

    runs.sort(key=lambda r: r[0]["scopeSpans"][0]["spans"][0]["startTimeUnixNano"])
    decisions.sort(key=lambda d: d["at"])
    return runs, decisions


def get(url: str, timeout: float = 5) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""
    except (urllib.error.URLError, OSError):
        return 0, b""


def post(url: str, body: dict) -> int:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as error:
        print(f"  collector refused a batch: {error.code} {error.read()[:200]!r}", flush=True)
        return error.code
    except (urllib.error.URLError, OSError) as error:
        print(f"  collector unreachable: {error}", flush=True)
        return 0


def seeded_already() -> bool:
    status, body = get(f"{TRACES}/api/traces/{WORKED['trace_id']}")
    if status != 200:
        return False
    try:
        return bool(json.loads(body).get("data"))
    except ValueError:
        return False


def wait_for(name: str, url: str) -> None:
    for _ in range(120):
        status, _body = get(url, timeout=3)
        if status and status < 500:
            return
        time.sleep(2)
    print(f"  {name} did not answer at {url} in four minutes; seeding anyway", flush=True)


def write_decisions(decisions: list[dict]) -> int:
    DECISION_LOG.parent.mkdir(parents=True, exist_ok=True)
    existing = DECISION_LOG.read_text() if DECISION_LOG.exists() else ""
    if "seed-88213-" in existing:
        return 0
    with DECISION_LOG.open("a", encoding="utf-8") as handle:
        for line in decisions:
            handle.write(json.dumps(line) + "\n")
    return len(decisions)


def seed() -> None:
    runs, decisions = history()
    written = write_decisions(decisions)
    print(f"  decision records: {written} appended to {DECISION_LOG}"
          if written else f"  decision records: already in {DECISION_LOG}", flush=True)
    sent = 0
    for index in range(0, len(runs), 20):
        batch = [rs for run in runs[index:index + 20] for rs in run]
        if post(f"{COLLECTOR}/v1/traces", {"resourceSpans": batch}) in (200, 202):
            sent += len(runs[index:index + 20])
    print(f"  traces: {sent} of {len(runs)} runs sent to the collector", flush=True)


def main() -> int:
    print("telemetry seed: waiting for the collector and the trace store", flush=True)
    wait_for("the collector", f"{COLLECTOR}/v1/traces")
    wait_for("the trace store", f"{TRACES}/api/services")
    while True:
        if seeded_already():
            time.sleep(30)
            continue
        print("telemetry seed: the history is not in the trace store; seeding", flush=True)
        seed()
        time.sleep(30)


if __name__ == "__main__":
    sys.exit(main())
