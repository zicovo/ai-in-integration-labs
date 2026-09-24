"""The second engine behind `policy.decide()`: Open Policy Agent, asked per call.

d-03 moves the decision out of the gateway and into a policy engine the learner can test, diff
and deploy. The gateway's part is small and fixed, and it is written down here because three
labs read what comes out of it:

    input     who is asking, on whose authority, what tool, with what arguments, and which
              approvals are currently active. Nothing about the model, nothing about the note
              the model read. The policy cannot read the prompt, and that is the property f-01
              turns on
    query     `data.aquaflux.tools`, the learner's package. `decision` is the contract: an
              object with `effect` (allow, deny, hold) and `rule`. A package that only defines
              the older `allow` boolean idiom is read too, so a policy written that way still
              decides rather than failing closed for the wrong reason
    version   the hash of every policy the engine currently holds, so a log line names the
              text that decided it. There is no other honest version for a file a learner edits
              and pushes; a counter would say "the third time" and not "this text"

When the engine cannot be reached, or holds no decision for the package, the call is denied and
the reason says so. A gateway that allowed calls because its policy engine was down would be a
gateway that fails open, and d-03's whole argument is against that.
"""

from __future__ import annotations

import hashlib
import os

import httpx

DEFAULT_URL = os.environ.get("AQUAFLUX_OPA_URL", "http://policy:8181")
TIMEOUT = 10.0


async def version(url: str | None = None) -> str:
    """The short hash of everything the engine holds, or `unreachable`."""
    base = url or DEFAULT_URL
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{base}/v1/policies")
            response.raise_for_status()
            policies = response.json().get("result") or []
    except Exception:  # noqa: BLE001
        return "unreachable"
    if not policies:
        return "empty"
    digest = hashlib.sha256()
    for policy in sorted(policies, key=lambda p: p.get("id", "")):
        digest.update(policy.get("id", "").encode())
        digest.update(b"\0")
        digest.update((policy.get("raw") or "").encode())
        digest.update(b"\0")
    return digest.hexdigest()[:8]


def build_input(tool: str, arguments: dict, identity: dict, approvals: list[dict],
                server: str | None) -> dict:
    return {
        "agent": identity.get("agent"),
        "on_behalf_of": identity.get("person"),
        "actor_claim": identity.get("actor_claim"),
        "tool": tool,
        "server": server,
        "arguments": arguments,
        "approvals": approvals,
        "token": {
            "present": bool(identity.get("token")),
            "audiences": identity.get("audiences") or [],
            "scopes": identity.get("scopes") or [],
        },
    }


async def ask(url: str | None, package: str, opa_input: dict) -> dict:
    """Put one call to the engine and return a normalised decision.

    Returns a dict with `effect`, `rule`, `reason`, `approver` and `raw`. `effect` is `error`
    when the engine could not answer, which the caller turns into a deny.
    """
    base = url or DEFAULT_URL
    path = package.strip("/")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(f"{base}/v1/data/{path}", json={"input": opa_input})
            response.raise_for_status()
            document = response.json().get("result")
    except Exception as error:  # noqa: BLE001
        return {"effect": "error", "rule": None, "approver": None, "raw": None,
                "reason": f"the policy engine at {base} could not be asked: {str(error)[:200]}"}

    if not isinstance(document, dict):
        return {"effect": "error", "rule": None, "approver": None, "raw": document,
                "reason": f"the policy engine holds no package data.{path.replace('/', '.')}; "
                          "load one with aqx policy apply <dir>"}

    decision = document.get("decision")
    if isinstance(decision, dict) and decision.get("effect"):
        effect = str(decision["effect"]).lower()
        if effect in ("require_approval", "approval", "held"):
            effect = "hold"
        return {
            "effect": effect,
            "rule": decision.get("rule"),
            "reason": decision.get("reason"),
            "approver": decision.get("approver"),
            # A policy that says which approval it relied on can put its id here, and the log
            # line carries it. The handout's policy does not; the presented approvals are in the
            # line either way.
            "approval_id": decision.get("approval_id"),
            "raw": decision,
        }

    # The boolean idiom: `default allow := false` plus an optional `deny_reason`.
    if "allow" in document:
        allowed = bool(document.get("allow"))
        return {
            "effect": "allow" if allowed else "deny",
            "rule": "allow" if allowed else "not_allowed",
            "reason": None if allowed else document.get("deny_reason"),
            "approver": None,
            "raw": {k: v for k, v in document.items() if k in ("allow", "deny_reason")},
        }

    return {"effect": "error", "rule": None, "approver": None, "raw": document,
            "reason": f"the package data.{path.replace('/', '.')} defines neither `decision` "
                      "nor `allow`, so the gateway has nothing to read"}
