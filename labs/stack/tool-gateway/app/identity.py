"""Who is calling, and on whose authority.

The gateway validates a bearer token when one is presented: signature against the realm's
published keys, issuer, expiry. What it does with the audience and the scope is the policy's
business, not this module's, because those are the two things carry-the-authority asks a learner to get right
and a gateway that hard-codes them has nothing left to teach.

This is deliberately the same shape as `labs/stack/aquaflux-api/app/bearer.py`, including the
`act` then `azp` reading of the acting party (`dec:OD-024`). Two services reading a token the
same way is not duplication worth removing: they are separate images, and the day one of them
changes, the other should not.
"""

from __future__ import annotations

import os

import jwt
from jwt import PyJWKClient

ISSUER = os.environ.get("AQUAFLUX_ISSUER", "https://idp.aquaflux.internal/realms/aquaflux")
JWKS_URL = os.environ.get(
    "AQUAFLUX_JWKS_URL",
    "http://identity:8080/realms/aquaflux/protocol/openid-connect/certs",
)

_jwks: PyJWKClient | None = None


def _keys() -> PyJWKClient:
    global _jwks
    if _jwks is None:
        _jwks = PyJWKClient(JWKS_URL, cache_keys=True, lifespan=300)
    return _jwks


def read(authorization: str | None) -> dict:
    """Read the caller out of an Authorization header.

    Returns the shape the decision log wants, whether or not there was a token. `error` is set
    when a token was presented and did not verify, and the caller turns that into a refusal; a
    missing token is not an error here, because whether one is required is a policy question.
    """
    blank = {
        "token": False,
        "agent": None,
        "person": None,
        "actor_claim": None,
        "audiences": [],
        "scopes": [],
        "expires_in": None,
        "error": None,
    }

    if not authorization:
        return blank
    if not authorization.lower().startswith("bearer "):
        return {**blank, "error": "Authorization must be a Bearer token"}

    token = authorization.split(" ", 1)[1].strip()

    try:
        signing_key = _keys().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            issuer=ISSUER,
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        return {**blank, "error": "the token has expired"}
    except jwt.InvalidIssuerError:
        return {**blank, "error": f"the token was not issued by {ISSUER}"}
    except Exception as error:  # noqa: BLE001 - the learner needs the reason, whatever it is
        return {**blank, "error": f"the token did not verify: {error}"}

    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience] if audience else []

    person = claims.get("preferred_username") or claims.get("sub")
    act = claims.get("act")
    if isinstance(act, dict) and act.get("sub"):
        agent, actor_claim = act["sub"], "act"
    elif claims.get("azp") and claims.get("azp") not in audiences:
        agent, actor_claim = claims["azp"], "azp"
    else:
        agent, actor_claim = None, None

    return {
        "token": True,
        "agent": agent,
        "person": person,
        "actor_claim": actor_claim,
        "audiences": sorted(audiences),
        "scopes": sorted((claims.get("scope") or "").split()),
        "expires_in": claims.get("exp"),
        "error": None,
    }
