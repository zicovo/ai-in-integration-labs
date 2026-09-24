"""What the meter check workflow needs from the rest of the stack. Plumbing, not the lesson.

e-03 is about one function, `request_id_for`, and about what a durable engine does and does not
guarantee. Everything the workflow's activities need from the stack around it lives here so that
`labs/e-03/<tier>/activities.py` can be read in one sitting and edited in one place:

    token()             Nadia's authority, carried by the agent: the same exchange d-02 turns on,
                        with the audience and scope the work order API publishes
    readings()          the meter data for one connection, from the meter data API
    propose()           one model call through the model gateway, strict JSON out, and the model
                        version recorded at the moment the proposal is produced
    approval_for()      the newest active approval the approval service holds for one action on
                        one connection, given after a moment the caller names
    create_meter_check() the tool call through the tool gateway, with the trace on the wire
    cancel_work_order() the compensation the completion tier writes: straight to the API, because
                        the curated catalogue publishes no cancel tool, and that is deliberate

Every call that leaves this process carries `traceparent` (labs/stack/agent/telemetry.py), so the
gateway's decision record and the model gateway's span join the run's trace. The trace context
itself travels in the workflow's headers, put there by the engine's OpenTelemetry interceptor,
which is why a worker started five minutes after the crash still writes onto the same trace.

Addresses are the stack's public names, because this code runs in the dev container, which is on
the lab network. The engine alone is reached by service name (`workflow:7233`): that is gRPC that
never leaves the network, and labs/README.md says which of the two forms is used where.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from typing import Any

import requests

STACK = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STACK / "agent"))
import telemetry  # noqa: E402  the spans, shared with the reading assistant

IDP = os.environ.get("AQUAFLUX_IDP", "https://idp.aquaflux.internal/realms/aquaflux")
MDM = os.environ.get("AQUAFLUX_MDM", "https://mdm.aquaflux.internal")
WOM = os.environ.get("AQUAFLUX_WOM", "https://wom.aquaflux.internal/v4")
TOOLS = os.environ.get("AQUAFLUX_TOOLS", "https://tools.aquaflux.internal:4444")
MODELS = os.environ.get("AQUAFLUX_GATEWAY", "https://models.aquaflux.internal:4000")
APPROVALS = os.environ.get("AQUAFLUX_APPROVALS", "https://approvals.aquaflux.internal")
WORKFLOW_ENGINE = os.environ.get("AQUAFLUX_WORKFLOW", "workflow:7233")
MODEL_KEY = os.environ.get("LAB_GATEWAY_KEY", "sk-aquaflux-lab")
MODEL = os.environ.get("AQUAFLUX_MODEL_NAME", "aquaflux-default")

TASK_QUEUE = "aquaflux-meter-check"
AGENT = "meter-check-workflow"         # the client the workflow acts as, its own identity
AGENT_SECRET = os.environ.get("LAB_WORKFLOW_SECRET", "meter-check-workflow-secret")
ACTS_FOR = "nadia"                     # the person whose authority it carries
TIMEOUT = 300

TOOL = "create_meter_check_work_order"
ACTION = "meter_check"                 # the action Sam approves, as approve.sh spells it

SYSTEM_PROMPT = "\n".join([
    "You are the Aquaflux reading assistant. A service desk agent has asked whether the water",
    "meter of one connection should be checked by a technician, because the customer disputes",
    "the invoice. You are given the monthly readings. Decide whether a meter check is warranted",
    "and answer in the schema you are given. Propose a meter check when consumption changes in a",
    "way the customer's household cannot plausibly explain; otherwise propose none. The reason",
    "is one of: implausible_consumption (the readings jump or fall without a plausible cause),",
    "disputed_reading (the customer says a specific reading is wrong), meter_not_readable (a",
    "reading is missing or estimated). Choose the one the readings support.",
])

PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": [ACTION, "none"]},
        "reason": {
            "type": "string",
            "enum": ["disputed_reading", "implausible_consumption", "meter_not_readable"],
        },
        "explanation": {"type": "string"},
    },
    "required": ["action", "reason", "explanation"],
    "additionalProperties": False,
}


# ------------------------------------------------------------------ identity


def token(scope: str = "workorder:create") -> str:
    """Nadia's authority, narrowed to one audience and the scopes named, held by the agent.

    The same three calls as labs/stack/agent/ask.py, with the two lines d-02's seeded fault gets
    wrong written correctly: the audience is the work order API and the scope is what the tool
    needs. The completion tier's compensation asks for `workorder:close` and nothing else.
    """
    endpoint = f"{IDP}/protocol/openid-connect/token"
    person = requests.post(endpoint, data={
        "grant_type": "password", "client_id": "service-desk",
        "username": ACTS_FOR, "password": os.environ.get("LAB_NADIA_PASSWORD", "nadia"),
        "scope": "openid meter:read workorder:create workorder:read workorder:close",
    }, timeout=30)
    person.raise_for_status()
    agent = requests.post(endpoint, data={
        "grant_type": "client_credentials", "client_id": AGENT,
        "client_secret": AGENT_SECRET,
    }, timeout=30)
    agent.raise_for_status()
    exchanged = requests.post(endpoint, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
        "client_id": AGENT,
        "client_secret": AGENT_SECRET,
        "subject_token": person.json()["access_token"],
        "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "actor_token": agent.json()["access_token"],
        "actor_token_type": "urn:ietf:params:oauth:token-type:access_token",
        "audience": "wom-api",
        "scope": scope,
    }, timeout=30)
    exchanged.raise_for_status()
    return exchanged.json()["access_token"]


# ------------------------------------------------------------------ the systems of record


def readings(connection_id: str) -> list[dict]:
    """The monthly readings the model is shown. The meter data API asks for no token."""
    response = requests.get(f"{MDM}/readings", params={"connection_id": connection_id},
                            headers=telemetry.headers(), timeout=30)
    response.raise_for_status()
    return response.json()


def work_orders(connection_id: str) -> list[dict]:
    response = requests.get(f"{WOM}/work-orders", params={"connection_id": connection_id},
                            timeout=30)
    response.raise_for_status()
    return response.json()


def cancel_work_order(work_order_id: str, reason: str, bearer: str, decided_by: str = ACTS_FOR) -> dict:
    """The compensation: cancel one work order with a reason, straight against the API.

    The curated catalogue publishes create and read and nothing else, on purpose (c-02). A
    compensation that cannot go through the tool it undoes is the usual shape, and where that
    call goes, with which credential, is a decision the completion tier asks the learner to make.
    """
    response = requests.post(
        f"{WOM}/work-orders/{work_order_id}/cancel",
        json={"decided_by": decided_by, "comment": reason[:300]},
        headers=telemetry.headers({"Authorization": f"Bearer {bearer}"}),
        timeout=30,
    )
    return {"status": response.status_code, **(response.json() if response.content else {})}


# ------------------------------------------------------------------ the model


def propose(connection_id: str, rows: list[dict], run_id: str, trace_id: str | None) -> dict:
    """One model call, strict JSON out, the answering model recorded beside the answer.

    `user` is the run id: the model gateway writes it to its call log as `end_user`, which is how
    the handout's step seven counts the calls one run made. The span is a `chat` span on the
    run's trace, filled the way the reading assistant fills it.
    """
    tracer = telemetry.setup("meter-check-worker")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({
            "connection_id": connection_id,
            "question": "The customer says the bill doubled. Should a technician check the meter?",
            "readings": [{"month": r.get("period") or r.get("read_at") or r.get("date"),
                          "volume_m3": r.get("volume_m3")} for r in rows],
        })},
    ]
    body = {
        "model": MODEL, "temperature": 0, "messages": messages, "user": run_id,
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": "proposal", "schema": PROPOSAL_SCHEMA,
                                            "strict": True}},
    }
    with tracer.start_as_current_span(f"chat {MODEL}") as span:
        response = requests.post(f"{MODELS}/v1/chat/completions",
                                 headers=telemetry.headers({"Authorization": f"Bearer {MODEL_KEY}"}),
                                 json=body, timeout=TIMEOUT)
        response.raise_for_status()
        answer = response.json()
        telemetry.record_model_call(span, MODEL, messages, answer, dict(response.headers))
    content = answer["choices"][0]["message"]["content"]
    proposal = json.loads(content)
    headers = {k.lower(): v for k, v in response.headers.items()}
    return {
        "proposal": proposal,
        # The model version at the moment the proposal was produced: what the gateway answered,
        # the deployment behind it, and the gateway's own id for the call. The open tier's
        # second constraint, kept here so every tier records it.
        "model_requested": MODEL,
        "model_answered": answer.get("model"),
        "deployment_id": (headers.get("x-litellm-model-id") or "")[:16],
        "gateway_call_id": headers.get("x-litellm-call-id"),
        "usage": answer.get("usage"),
        "trace_id": trace_id,
    }


def model_calls_for(run_id: str) -> int:
    """How many calls the model gateway logged for one run, by the `end_user` it recorded."""
    response = requests.get(f"{MODELS}/spend/logs", headers={"Authorization": f"Bearer {MODEL_KEY}"},
                            timeout=60)
    response.raise_for_status()
    return sum(1 for row in response.json() if row.get("end_user") == run_id)


# ------------------------------------------------------------------ approvals


def approval_for(connection_id: str, action: str = ACTION, not_before: str | None = None) -> dict | None:
    """The newest active approval for this action on this connection, given after `not_before`.

    An approval given for an earlier run is not an approval of this proposal. The workflow
    passes the moment its proposal was validated, and anything Sam recorded before that is
    ignored, which is what "bound to the arguments" means once time is one of the arguments.
    """
    response = requests.get(f"{APPROVALS}/approvals", params={"active": "true"}, timeout=30)
    response.raise_for_status()
    rows = [r for r in response.json()
            if r.get("action") == action and r.get("connection_id") == connection_id
            and (not_before is None or r.get("at", "") >= not_before)]
    rows.sort(key=lambda r: r.get("at", ""))
    return rows[-1] if rows else None


# ------------------------------------------------------------------ the tool call


class GatewayRefused(RuntimeError):
    """The gateway answered the call with a refusal rather than a result.

    A refusal is an answer, not a fault: nothing about the token, the policy or the catalogue
    changes between one attempt and the next, so an activity that meets one must not be retried
    into the same wall. The activities raise it as non-retryable; the run prints the reason.
    """

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def create_meter_check(connection_id: str, reason: str, request_id: str, note: str,
                       bearer: str) -> dict:
    """One tool call through the gateway, on its own `execute_tool` span.

    Returns what the run needs to say about the write: the work order id, whether the API created
    it (201) or answered with the original it had already created for that key (409), and the
    gateway's call id. The span carries the key and the work order id from the start: e-03 runs
    after d-04, where those two lines were the second fix.
    """
    tracer = telemetry.setup("meter-check-worker")
    arguments = {"connection_id": connection_id, "reason": reason, "request_id": request_id,
                 "note": note}
    with tracer.start_as_current_span(f"execute_tool {TOOL}") as span:
        telemetry.record_tool_call(span, TOOL, arguments, None)
        span.set_attribute("aquaflux.idempotency_key", request_id)
        response = requests.post(
            f"{TOOLS}/mcp",
            headers=telemetry.headers({"Authorization": f"Bearer {bearer}",
                                       "Content-Type": "application/json"}),
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": TOOL, "arguments": arguments}},
            timeout=TIMEOUT,
        )
        result = response.json()
        telemetry.record_tool_result(span, result, response.status_code)
        if response.status_code != 200 or result.get("error"):
            error = result.get("error") or {}
            raise GatewayRefused(
                f"the tool gateway refused {TOOL}: {response.status_code} {error.get('message')} "
                f"(decision {((error.get('data') or {}).get('decision'))})",
                status=response.status_code,
            )
        payload = _structured(result.get("result") or {})
        if payload.get("error"):
            raise RuntimeError(f"the work order API refused: {payload.get('error')} {payload.get('detail')}")
        work_order_id = str(payload.get("work_order_id") or "")
        created = bool(payload.get("created", True))
        span.set_attribute("aquaflux.work_order.id", work_order_id)
        span.set_attribute("aquaflux.work_order.created", created)
        return {
            "work_order_id": work_order_id,
            "created": created,
            "http_status": 201 if created else 409,
            "state": payload.get("state"),
            "gateway_call_id": ((result.get("result") or {}).get("_gateway") or {}).get("call_id"),
            "request_id": request_id,
        }


def _structured(result: dict) -> dict:
    for key in ("structuredContent", "structured_content"):
        if isinstance(result.get(key), dict):
            return result[key]
    for item in result.get("content") or []:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            try:
                parsed = json.loads(item["text"])
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
