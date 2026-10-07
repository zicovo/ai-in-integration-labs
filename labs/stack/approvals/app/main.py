"""The Aquaflux approval service: a notary, not a judge.

block-the-call turns on the difference between an approval that is evidence and one that is theatre. The
study text gives three properties of the first kind: bound to the arguments, given by somebody who
re-authenticated, and given by somebody other than the person who initiated. This service records
the first two and leaves the third to the policy, on purpose.

    bound to the arguments   the record carries the action and the connection id it was given
                             for, and a hash of exactly those, so the gateway can say "this
                             approval is for this call" and nothing else
    re-authenticated         an approval is a POST carrying a fresh bearer token from the identity
                             provider. `approve.sh` signs the approver in at the moment of
                             approving; there is no session to reuse
    not the initiator        not checked here. The policy checks it, because the policy is the
                             place a learner is asked to write it, and a fixture that quietly
                             enforced the rule would make the lab's step five impossible

So this service will record Els approving her own case. It records who she is and which roles the
identity provider says she holds, and the policy engine, reading the record, is what refuses to
treat that as an approval. That is the division of labour the module teaches: evidence is
collected in one place and judged in another.

The gateway fetches the active approvals before every decision and hands them to the policy as
`input.approvals`. Records expire; the default lifetime is short, because an approval given this
morning is not a decision taken now.

**An approval is spent by the call it released.** When a decision names the approval it relied
on, the gateway claims it here (`POST /approvals/{id}/use`) before it forwards the call, and a
used approval is no longer active, so it cannot release a second call. The claim is the check:
two calls racing for one approval get one 200 and one 409. Until 2026-09-24 an approval stayed
valid for its whole lifetime and any number of calls, which is not what anybody signing one
means.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid

import jwt
from fastapi import FastAPI, HTTPException, Request
from jwt import PyJWKClient
from pydantic import BaseModel, Field

ISSUER = os.environ.get("AQUAFLUX_ISSUER", "https://idp.aquaflux.internal/realms/aquaflux")
JWKS_URL = os.environ.get(
    "AQUAFLUX_JWKS_URL",
    "http://identity:8080/realms/aquaflux/protocol/openid-connect/certs",
)
# The audience an approval token has to be addressed to. A token cut for the reading assistant is
# not a token for approving disconnections, which is carry-the-authority's lesson applied to this door.
AUDIENCE = os.environ.get("AQUAFLUX_AUDIENCE", "approvals-api")
DEFAULT_TTL_MINUTES = int(os.environ.get("AQUAFLUX_APPROVAL_TTL_MINUTES", "30"))

# Which of an approver's roles the record names as *the* role they approved under, most senior
# first. A person holding several roles approves under the most senior one that is relevant here.
# The policy reads `approver_role`; `approver_roles` carries the full list for a policy that
# wants to decide differently.
ROLE_PRECEDENCE = [
    r for r in os.environ.get(
        "AQUAFLUX_ROLE_PRECEDENCE",
        "collections-team-lead,collections-officer,service-desk,field-technician,integration-engineer",
    ).split(",") if r
]

app = FastAPI(title="Aquaflux approval service", version="1.0")

_approvals: list[dict] = []
_jwks: PyJWKClient | None = None


def _keys() -> PyJWKClient:
    global _jwks
    if _jwks is None:
        _jwks = PyJWKClient(JWKS_URL, cache_keys=True, lifespan=300)
    return _jwks


def _refuse(error: str, description: str, status: int = 401) -> HTTPException:
    challenge = f'Bearer realm="aquaflux", error="{error}", error_description="{description}"'
    return HTTPException(status_code=status, detail=description, headers={"WWW-Authenticate": challenge})


def approver_from(request: Request) -> dict:
    """Who is approving, from a fresh token and nothing else."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise _refuse("invalid_request", "An approval needs a bearer token for the approver; none was presented")
    token = header.split(" ", 1)[1].strip()
    try:
        key = _keys().get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["RS256", "ES256"], issuer=ISSUER,
                            options={"verify_aud": False})
    except jwt.ExpiredSignatureError:
        raise _refuse("invalid_token", "The token has expired")
    except Exception as error:  # noqa: BLE001 - the learner needs the reason, whatever it is
        raise _refuse("invalid_token", f"The token did not verify: {error}")

    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience] if audience else []
    if AUDIENCE and AUDIENCE not in audiences:
        raise _refuse(
            "invalid_token",
            f"This token is addressed to {audiences or ['nothing']}, and an approval needs a token "
            f"addressed to {AUDIENCE}",
        )

    roles = list((claims.get("realm_access") or {}).get("roles") or [])
    role = next((r for r in ROLE_PRECEDENCE if r in roles), roles[0] if roles else None)
    return {
        "approver": claims.get("preferred_username") or claims.get("sub"),
        "approver_role": role,
        "approver_roles": sorted(roles),
        "authenticated_at": claims.get("auth_time") or claims.get("iat"),
        "token_expires_at": claims.get("exp"),
    }


class ApprovalRequest(BaseModel):
    action: str = Field(pattern=r"^[a-z_]{2,40}$")
    connection_id: str = Field(pattern=r"^[0-9]{4,8}$")
    case_reference: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=300)
    ttl_minutes: int | None = Field(default=None, ge=1, le=240)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _active(record: dict) -> bool:
    return (record["expires_at_epoch"] > time.time() and not record.get("revoked")
            and not record.get("used_at"))


def _public(record: dict) -> dict:
    return {k: v for k, v in record.items() if k != "expires_at_epoch"}


@app.get("/health", include_in_schema=False)
def health() -> dict:
    return {"status": "ok", "approvals": len([r for r in _approvals if _active(r)])}


@app.post("/approvals", status_code=201)
def approve(body: ApprovalRequest, request: Request) -> dict:
    """Record one approval. The approver is whoever the token says, with the roles it carries."""
    who = approver_from(request)
    # The arguments this approval is for, and a hash of exactly those. The gateway hands the
    # policy the record; the policy compares fields. The hash is here so that a policy, or an
    # auditor, can also say "this approval covers this call and no other" in one comparison.
    arguments = {"action": body.action, "connection_id": body.connection_id}
    ttl = (body.ttl_minutes or DEFAULT_TTL_MINUTES) * 60
    record = {
        "approval_id": f"apr-{uuid.uuid4().hex[:8]}",
        "at": _now(),
        "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + ttl)),
        "expires_at_epoch": time.time() + ttl,
        "action": body.action,
        "connection_id": body.connection_id,
        "arguments": arguments,
        "arguments_sha256": hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest()[:16],
        "case_reference": body.case_reference,
        "note": body.note,
        **who,
    }
    _approvals.append(record)
    return _public(record)


@app.get("/approvals")
def list_approvals(active: bool = True) -> list[dict]:
    rows = [r for r in _approvals if _active(r)] if active else list(_approvals)
    return [_public(r) for r in rows]


@app.get("/approvals/{approval_id}")
def get_approval(approval_id: str) -> dict:
    for record in _approvals:
        if record["approval_id"] == approval_id:
            return _public(record)
    raise HTTPException(404, f"no approval {approval_id}")


class UsePayload(BaseModel):
    call_id: str = Field(max_length=80)
    tool: str | None = Field(default=None, max_length=80)


@app.post("/approvals/{approval_id}/use")
def use(approval_id: str, body: UsePayload) -> dict:
    """Spend one approval on one call. The gateway calls this before it forwards the call.

    409 when it has been used, revoked or has expired, with the reason, so the gateway can refuse
    the call and say which. The record keeps the call that spent it, so "which call did Sam's yes
    release" has one answer.
    """
    for record in _approvals:
        if record["approval_id"] != approval_id:
            continue
        if record.get("used_at"):
            raise HTTPException(409, f"approval {approval_id} was already used by call {record.get('used_by_call')}")
        if record.get("revoked"):
            raise HTTPException(409, f"approval {approval_id} was revoked")
        if record["expires_at_epoch"] <= time.time():
            raise HTTPException(409, f"approval {approval_id} expired at {record['expires_at']}")
        record["used_at"] = _now()
        record["used_by_call"] = body.call_id
        record["used_for_tool"] = body.tool
        return _public(record)
    raise HTTPException(404, f"no approval {approval_id}")


@app.delete("/approvals/{approval_id}")
def revoke(approval_id: str) -> dict:
    for record in _approvals:
        if record["approval_id"] == approval_id:
            record["revoked"] = True
            return {"revoked": approval_id}
    raise HTTPException(404, f"no approval {approval_id}")


@app.delete("/approvals", include_in_schema=False)
def clear() -> dict:
    """Used by `smoke.sh` and `verify.sh`, so an approval from an earlier session cannot quietly
    make a refusal succeed. No handout calls it."""
    count = len(_approvals)
    _approvals.clear()
    return {"cleared": count}
