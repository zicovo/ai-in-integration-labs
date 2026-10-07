"""The Aquaflux tool gateway.

One door in front of every MCP server the labs publish. It federates them, decides each call
against a named policy, forwards the ones it allows, and writes one log line per call whatever
it decided (ADR-021).

Four handouts grade on what this writes rather than on what it returns:

    expose-one-operation  the log line names the agent, the person, the tool, the arguments, the decision,
          the policy version and the work order id
    carry-the-authority  two lines: the refusal of a wrongly addressed token with its reason, and the allowed
          call with both identities
    block-the-call  the same line with the decision coming from Open Policy Agent (app/opa.py) instead
          of the rules in app/policy.py, and with the approval that released it, if one did
    reconstruct-one-transaction  the same line, in the gateway's own decision file, joined to the run's trace by the
          trace id the caller sent

So the log is the product here and the proxying is plumbing. `GET /logs` is the endpoint every
handout reads, and its field names are fixed in labs/README.md. When AQUAFLUX_DECISION_LOG names
a file, every line is appended there too, with the trace and span ids of the call, and when
AQUAFLUX_OTLP names a collector, each call is one span (app/telemetry.py). The span never carries
the decision. That split is reconstruct-one-transaction's seeded fault, and it is a realistic one: the decision is
durable in the gateway's own file whatever the telemetry pipeline does, and it reaches the audit
trail only if somebody wires the file into the collector.

The MCP surface is `POST /mcp`, plain JSON-RPC, stateless: no initialize handshake, no session
id, no event stream. A real MCP server would do all three. This one does not, because a handout
has to be able to say `curl -d '{"jsonrpc":...}'` and have a learner see the whole request. What
the gateway speaks to the servers behind it *is* the real thing, through the SDK's client, so
the protocol is exercised where it is being taught and simplified where it is only being typed.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from opentelemetry import trace as trace_api
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import approvals, identity, opa, policy, telemetry
from .registry import Registry

VERSION = "1.2"
LOG_LIMIT = 500
DECISION_LOG = os.environ.get("AQUAFLUX_DECISION_LOG", "")

app = FastAPI(title="Aquaflux tool gateway", version=VERSION, docs_url="/docs")

registry = Registry()
policies = policy.available()
active = policies[os.environ.get("AQUAFLUX_POLICY", "wo-tools-1")]
logs: list[dict] = []
tracer = telemetry.setup()


# ------------------------------------------------------------------ the decision log


def record(**fields: Any) -> dict:
    """Append one decision record and return it.

    Arguments are logged in full and hashed. In a real gateway the full arguments are often the
    thing you must not keep, which is why the hash is there; here both are kept, because expose-one-operation
    asks a learner to read what the model actually sent and a hash of it teaches nothing.
    """
    arguments = fields.get("arguments") or {}
    trace_id, span_id = telemetry.ids()
    line = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "call_id": fields.get("call_id") or str(uuid.uuid4()),
        # The run this call belongs to, from the caller's `traceparent`. This is the join reconstruct-one-transaction
        # depends on: the collector reads this file and puts the decision on the same trace.
        "trace_id": trace_id,
        "span_id": span_id,
        "agent": fields.get("agent"),
        "person": fields.get("person"),
        "actor_claim": fields.get("actor_claim"),
        "tool": fields.get("tool"),
        "server": fields.get("server"),
        "arguments": arguments,
        "arguments_sha256": hashlib.sha256(
            json.dumps(arguments, sort_keys=True).encode()
        ).hexdigest()[:16],
        "decision": fields.get("decision"),
        "reason": fields.get("reason"),
        "policy": active.id,
        "policy_version": fields.get("policy_version") or active.version,
        "rule": fields.get("rule"),
        # The approvals the policy was shown, and the one that released a hold if one did. An
        # allow that rests on an approval has to say which, or the log cannot answer "who said
        # yes to this" (block-the-call's acceptance check).
        "approvals": fields.get("approvals") or [],
        "approval_id": fields.get("approval_id"),
        "work_order_id": fields.get("work_order_id"),
        # The policy allowed the call and the tool failed anyway. Both belong in one line: a log
        # that only records the decision cannot answer "did it work", and a log that only
        # records the outcome cannot answer "was it allowed".
        "tool_error": fields.get("tool_error"),
        # False when the active policy is log-only and the call went through whatever the
        # decision above says. A shadow run is only worth something if its log cannot be
        # mistaken for an enforced one.
        "enforced": fields.get("enforced", True),
        "status": fields.get("status"),
        "duration_ms": fields.get("duration_ms"),
    }
    logs.append(line)
    del logs[:-LOG_LIMIT]
    if DECISION_LOG:
        try:
            with open(DECISION_LOG, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, default=str) + "\n")
        except OSError:
            pass
    return line


def work_order_id(result: Any) -> str | None:
    """Pull the work order id out of whatever the tool returned.

    A gateway cannot know what a tool returns, so this is a convention rather than a contract:
    if the result carries a field called `work_order_id`, the log line carries it too. expose-one-operation's
    acceptance check asks for it, because a decision record that cannot be joined to the thing
    that was decided is an audit trail with a hole in it.
    """
    for blob in _texts(result):
        try:
            parsed = json.loads(blob)
        except (TypeError, ValueError):
            continue
        if isinstance(parsed, dict) and parsed.get("work_order_id"):
            return str(parsed["work_order_id"])
    return None


def _texts(result: Any) -> list[str]:
    out: list[str] = []
    if isinstance(result, dict):
        # mcp 2.x spells this `structured_content` on the model and `structuredContent` on the
        # wire. Both are read, because which one arrives depends on how the SDK serialised it.
        for key in ("structuredContent", "structured_content"):
            if isinstance(result.get(key), dict):
                out.append(json.dumps(result[key]))
        for item in result.get("content") or []:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                out.append(item["text"])
    return out


# ------------------------------------------------------------------ housekeeping


@app.get("/health", include_in_schema=False)
def health() -> dict:
    return {
        "status": "ok",
        "version": VERSION,
        "servers": len(registry.servers),
        "tools": len(registry.tools()),
        "policy": active.id,
    }


async def current_policy_version() -> str:
    """The version the next log line will carry. Live for the OPA engine, static otherwise."""
    if active.engine == "opa":
        return await opa.version(active.opa_url)
    return active.version


@app.get("/version")
async def version() -> dict:
    """What `smoke.sh` prints, so a handout can say "it prints the gateway version"."""
    return {"name": "Aquaflux tool gateway", "version": VERSION, "policy": active.id,
            "policy_version": await current_policy_version(), "engine": active.engine}


# ------------------------------------------------------------------ the registry


class Registration(BaseModel):
    name: str
    url: str


@app.get("/servers")
def list_servers() -> list[dict]:
    return [server.as_dict() for server in registry.servers.values()]


@app.post("/servers")
async def register_server(body: Registration) -> dict:
    try:
        server = await registry.register(body.name, body.url)
    except ValueError as error:
        raise HTTPException(409, str(error))
    except Exception as error:  # noqa: BLE001
        raise HTTPException(
            502,
            f"could not reach an MCP server at {body.url}: {error}. Is it running, and is it "
            "serving Streamable HTTP on that address?",
        )
    return server.as_dict()


@app.delete("/servers/{name}")
def deregister_server(name: str) -> dict:
    if not registry.deregister(name):
        raise HTTPException(404, f"no server named {name} is registered")
    return {"deregistered": name}


@app.get("/tools")
def list_tools() -> list[dict]:
    """The catalogue, exactly as the servers behind the gateway publish it."""
    return registry.tools()


# ------------------------------------------------------------------ the policy


@app.get("/policies")
def list_policies() -> list[dict]:
    return [{"id": p.id, "version": p.version, "description": p.description,
             "active": p.id == active.id} for p in policies.values()]


@app.get("/policy")
async def get_policy() -> dict:
    """The active policy, plus which of its rules name a tool nobody publishes.

    That last list is not decoration. expose-one-operation's completion tier asks the learner to write a rule
    holding `create_disconnection_work_order` for an approver, and the point of the exercise is
    that the rule became *writable* the moment the catalogue was split, whether or not anybody
    has published that tool yet. The gateway says so rather than silently ignoring the rule.
    """
    published = {tool["name"] for tool in registry.tools()}
    return {
        **active.as_dict(),
        "version": await current_policy_version(),
        "rules_without_a_tool": sorted(
            rule.tool for rule in active.rules if rule.tool not in published and rule.tool != "*"
        ),
    }


@app.put("/policy/{policy_id}")
def activate_policy(policy_id: str) -> dict:
    global active
    if policy_id not in policies:
        raise HTTPException(
            404, f"no policy called {policy_id}. There is {', '.join(sorted(policies))}."
        )
    active = policies[policy_id]
    return {"active": active.id, "version": active.version}


# ------------------------------------------------------------------ the log


@app.get("/logs")
def get_logs(limit: int = 50, tool: str | None = None, decision: str | None = None) -> list[dict]:
    rows = logs
    if tool:
        rows = [r for r in rows if r["tool"] == tool]
    if decision:
        rows = [r for r in rows if r["decision"] == decision]
    return rows[-limit:]


@app.delete("/logs", include_in_schema=False)
def clear_logs() -> dict:
    """Used by `smoke.sh` and `verify.sh` between runs. No handout calls it."""
    count = len(logs)
    logs.clear()
    return {"cleared": count}


# ------------------------------------------------------------------ the MCP surface


def rpc_error(request_id: Any, code: int, message: str, status: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
    )


@app.post("/mcp")
async def mcp(request: Request, authorization: str | None = Header(default=None)) -> Any:
    """One JSON-RPC request. `initialize`, `tools/list` and `tools/call` and nothing else."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return rpc_error(None, -32700, "the body is not JSON", status=400)

    request_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": params.get("protocolVersion", "2026-07-28"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "aquaflux-tool-gateway", "version": VERSION},
            },
        }

    if method in ("notifications/initialized", "ping"):
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {
                        "name": tool["name"],
                        "description": tool["description"],
                        "inputSchema": tool["inputSchema"],
                        "annotations": tool["annotations"],
                    }
                    for tool in registry.tools()
                ]
            },
        }

    if method != "tools/call":
        return rpc_error(request_id, -32601, f"this gateway does not implement {method}")

    name = params.get("name")
    arguments = params.get("arguments") or {}
    call_id = str(uuid.uuid4())
    # One span per call, a child of the caller's trace when it sent one. It names the tool and
    # the call id and nothing about the decision; see the module docstring for why.
    with tracer.start_as_current_span(f"tool_gateway {name}", context=telemetry.parent(request.headers),
                                      kind=trace_api.SpanKind.SERVER) as span:
        span.set_attribute("aquaflux.tool", str(name))
        span.set_attribute("aquaflux.gateway.call_id", call_id)
        span.set_attribute("aquaflux.gateway.policy", active.id)
        response = await call_tool(request_id, name, arguments, authorization, call_id)
        span.set_attribute("http.response.status_code", getattr(response, "status_code", 200))
        return response


async def call_tool(request_id: Any, name: str, arguments: dict, authorization: str | None,
                    call_id: str) -> Any:
    caller = identity.read(authorization)
    started = time.monotonic()

    if caller["error"]:
        line = record(call_id=call_id, tool=name, arguments=arguments, decision="deny",
                      reason=caller["error"], status=401)
        return refusal(request_id, line, 401)

    found = registry.find(name)
    if found is None:
        line = record(call_id=call_id, agent=caller["agent"], person=caller["person"],
                      actor_claim=caller["actor_claim"], tool=name, arguments=arguments,
                      decision="deny", reason="no server behind this gateway publishes that tool",
                      status=404)
        return refusal(request_id, line, 404)

    server, _tool = found
    verdict, shown, policy_version = await decide(name, arguments, caller, server.name)

    # Log-only: the decision is recorded as the engine gave it and not enforced. A hold spends no
    # approval and a deny stops nothing; the one line for the call says both.
    shadow = active.enforcement == "log-only" and verdict.decision != "allow"

    if verdict.decision != "allow" and not shadow:
        line = record(call_id=call_id, agent=caller["agent"], person=caller["person"],
                      actor_claim=caller["actor_claim"], tool=name, server=server.name,
                      arguments=arguments, decision=verdict.decision, reason=verdict.reason,
                      rule=verdict.rule, status=verdict.status, approvals=shown,
                      policy_version=policy_version,
                      duration_ms=int((time.monotonic() - started) * 1000))
        return refusal(request_id, line, verdict.status)

    # The approval that released this call is spent before the call goes out, not after: two
    # calls racing for one approval must not both get through, and the claim is what decides.
    if verdict.approval_id and not shadow:
        spent = await approvals.use(verdict.approval_id, call_id, name)
        if spent:
            line = record(call_id=call_id, agent=caller["agent"], person=caller["person"],
                          actor_claim=caller["actor_claim"], tool=name, server=server.name,
                          arguments=arguments, decision="deny", reason=spent,
                          rule=verdict.rule, status=409, approvals=shown,
                          approval_id=verdict.approval_id, policy_version=policy_version,
                          duration_ms=int((time.monotonic() - started) * 1000))
            return refusal(request_id, line, 409)

    try:
        result = await registry.call(server, name, arguments)
    except Exception as error:  # noqa: BLE001
        line = record(call_id=call_id, agent=caller["agent"], person=caller["person"],
                      actor_claim=caller["actor_claim"], tool=name, server=server.name,
                      arguments=arguments, decision="error", reason=str(error)[:400], status=502,
                      approvals=shown, policy_version=policy_version,
                      duration_ms=int((time.monotonic() - started) * 1000))
        return refusal(request_id, line, 502)

    failed = bool(result.get("is_error") or result.get("isError"))
    reason = verdict.reason
    if shadow:
        reason = f"{verdict.reason} (log-only: not enforced, the call went through)"
    line = record(call_id=call_id, agent=caller["agent"], person=caller["person"],
                  actor_claim=caller["actor_claim"], tool=name, server=server.name,
                  arguments=arguments, decision=verdict.decision, reason=reason,
                  enforced=not shadow,
                  rule=verdict.rule, work_order_id=work_order_id(result),
                  approvals=shown, approval_id=verdict.approval_id,
                  policy_version=policy_version,
                  tool_error=failed or None, status=200,
                  duration_ms=int((time.monotonic() - started) * 1000))
    result = dict(result)
    result["_gateway"] = {"call_id": line["call_id"], "decision": line["decision"],
                          "policy": line["policy"], "policy_version": line["policy_version"],
                          "rule": line["rule"], "enforced": line["enforced"]}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


async def decide(tool: str, arguments: dict, caller: dict, server: str) -> tuple[policy.Decision, list[dict], str]:
    """One decision, from whichever engine the active policy names.

    Returns the decision, the approvals the engine was shown (compacted for the log), and the
    policy version the log line should carry. The approvals are fetched here rather than inside
    either engine so that both see the same list and the log records what was presented.
    """
    shown_full, approvals_error = await approvals.active()
    shown = approvals.compact(shown_full)

    if active.engine == "opa":
        opa_input = opa.build_input(tool, arguments, caller, shown_full, server)
        answer = await opa.ask(active.opa_url, active.opa_package, opa_input)
        version = await opa.version(active.opa_url)
        rule = answer.get("rule")
        if answer["effect"] == "allow":
            verdict = policy.Decision("allow", answer.get("reason") or f"allowed by rule {rule}", rule=rule,
                                      approval_id=answer.get("approval_id"))
        elif answer["effect"] == "hold":
            verdict = policy.Decision("hold", answer.get("reason") or f"held by rule {rule} for {answer.get('approver') or 'an approver'}",
                                      rule=rule, approver=answer.get("approver"), status=202)
        elif answer["effect"] == "deny":
            verdict = policy.Decision("deny", answer.get("reason") or f"refused by rule {rule}", rule=rule, status=403)
        else:
            # The engine could not answer. Fail closed, and say why in the reason, because a
            # deny that reads like a policy decision when it was an outage is the wrong lesson.
            verdict = policy.Decision("deny", answer.get("reason") or "the policy engine gave no decision",
                                      rule="engine_unavailable", status=503)
    else:
        verdict = policy.decide(active, tool, caller, arguments, shown_full)
        version = active.version

    if approvals_error and verdict.decision in ("hold", "deny"):
        verdict.reason = f"{verdict.reason} ({approvals_error})"
    return verdict, shown, version


def refusal(request_id: Any, line: dict, status: int) -> JSONResponse:
    """A refusal a learner can act on, in the protocol and in the HTTP status.

    The reason is in the body and, for anything to do with a token, in `WWW-Authenticate` as well.
    carry-the-authority turns on a participant reading that header rather than guessing, so it says which of the
    two faults was caught and not just "unauthorized".
    """
    headers = {}
    if status == 401:
        headers["WWW-Authenticate"] = (
            f'Bearer realm="aquaflux", error="invalid_token", '
            f'error_description="{line["reason"]}"'
        )
    elif status == 403:
        headers["WWW-Authenticate"] = (
            f'Bearer realm="aquaflux", error="insufficient_scope", '
            f'error_description="{line["reason"]}"'
        )
    return JSONResponse(
        status_code=status,
        headers=headers,
        content={
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32000,
                "message": line["reason"],
                "data": {
                    "decision": line["decision"],
                    "tool": line["tool"],
                    "policy": line["policy"],
                    "policy_version": line["policy_version"],
                    "rule": line["rule"],
                    "call_id": line["call_id"],
                },
            },
        },
    )
