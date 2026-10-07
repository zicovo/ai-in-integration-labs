"""Bearer token validation for the Aquaflux stand-ins.

carry-the-authority's instructor note asks for "the work order API stand-in accepting a bearer token and
rejecting a wrong audience with 401 and `WWW-Authenticate`". That refusal is the moment the lab
turns on: the learner has a token that is perfectly valid, signed by the right issuer, naming the
right person, and it is refused because it was addressed to the meter data system.

**A token is validated when one is presented, and not demanded when one is not.** That is
deliberate and it is a property of the stand-in, not of the architecture it stands in for. expose-one-operation
exercises the tool contract and never mentions identity; carry-the-authority exercises identity. Demanding a
token everywhere would break the first lab to teach nothing the second does not already. Set
`AQUAFLUX_BEARER=required` on the service to demand one, which is what a delivery that has
reached carry-the-authority should do.

Signatures are checked against the realm's published keys, fetched by the identity provider's
Compose service name over plain HTTP. The issuer inside the token is the public https address and
is checked as such. That split is deliberate: public names go through the ingress and carry TLS,
service to service traffic never leaves the network and has no reason to, so no container but the
dev container and the lab browser needs the lab's certificate authority.
"""

from __future__ import annotations

import os
import time

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient

MODE = os.environ.get("AQUAFLUX_BEARER", "optional").lower()
AUDIENCE = os.environ.get("AQUAFLUX_AUDIENCE", "")
ISSUER = os.environ.get(
    "AQUAFLUX_ISSUER", "https://idp.aquaflux.internal/realms/aquaflux"
)
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


def _refuse(error: str, description: str, status: int = 401) -> HTTPException:
    """A refusal a learner can act on: RFC 6750 says which error, and why, go in the header."""
    challenge = f'Bearer realm="aquaflux", error="{error}", error_description="{description}"'
    if AUDIENCE:
        challenge += f', resource_metadata="https://wom.aquaflux.internal/.well-known/oauth-protected-resource"'
    return HTTPException(status_code=status, detail=description, headers={"WWW-Authenticate": challenge})


def authorise(request: Request, scope: str | None = None) -> dict | None:
    """Validate the bearer token if there is one. Return its claims, or None when there is none."""
    header = request.headers.get("authorization", "")

    if not header:
        if MODE == "required":
            raise _refuse("invalid_request", "No bearer token was presented")
        return None

    if not header.lower().startswith("bearer "):
        raise _refuse("invalid_request", "Authorization must be a Bearer token")

    token = header.split(" ", 1)[1].strip()

    try:
        signing_key = _keys().get_signing_key_from_jwt(token)
    except Exception as error:  # noqa: BLE001 - the learner needs the reason, whatever it is
        raise _refuse("invalid_token", f"The signing key could not be resolved: {error}")

    # Audience is checked separately, so that its refusal can say something more useful than
    # "invalid token". Getting the audience wrong is the whole of carry-the-authority's seeded fault.
    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            issuer=ISSUER,
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise _refuse("invalid_token", "The token has expired")
    except jwt.InvalidIssuerError:
        raise _refuse("invalid_token", f"The token was not issued by {ISSUER}")
    except Exception as error:  # noqa: BLE001
        raise _refuse("invalid_token", f"The token did not verify: {error}")

    if AUDIENCE:
        audience = claims.get("aud")
        audiences = audience if isinstance(audience, list) else [audience] if audience else []
        if AUDIENCE not in audiences:
            raise _refuse(
                "invalid_token",
                f"This token is addressed to {audiences or ['nothing']}, and this API only "
                f"accepts a token addressed to {AUDIENCE}",
            )

    if scope:
        granted = (claims.get("scope") or "").split()
        if scope not in granted:
            raise _refuse(
                "insufficient_scope",
                f"This call needs the scope {scope}, and the token carries {granted or ['none']}",
                status=403,
            )

    return claims


def actor(claims: dict | None) -> dict:
    """Who acted, and on whose authority, in the shape a log line wants.

    RFC 8693 puts the actor in `act`. This identity provider does not emit that claim on a
    standard exchange and records the acting party in `azp` instead, so both are read and the
    log says which one it found. That gap is OD-024, and `labs/stack/check_delegation.py` is what
    notices if a later release closes it.
    """
    if not claims:
        return {"subject": None, "actor": None, "actor_claim": None}
    act = claims.get("act")
    if isinstance(act, dict) and act.get("sub"):
        return {"subject": claims.get("preferred_username") or claims.get("sub"),
                "actor": act["sub"], "actor_claim": "act"}
    if claims.get("azp") and claims.get("azp") != claims.get("aud"):
        return {"subject": claims.get("preferred_username") or claims.get("sub"),
                "actor": claims["azp"], "actor_claim": "azp"}
    return {"subject": claims.get("preferred_username") or claims.get("sub"),
            "actor": None, "actor_claim": None}


def lifetime(claims: dict | None) -> int | None:
    if not claims or "exp" not in claims:
        return None
    return int(claims["exp"] - time.time())
