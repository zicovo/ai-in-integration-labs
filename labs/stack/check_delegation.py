#!/usr/bin/env python3
"""Check the delegation chain carry-the-authority is built on, and which claim carries the actor.

`HANDOFF-LAB.md` puts this on the list to verify before every delivery, in these words: "That the
identity provider still issues an `act` claim on a standard token exchange with an `actor_token`.
carry-the-authority's handout says to check this per release; a change there breaks the lab's central teaching
artefact."

It does not, as of Keycloak 26.7.4. See `OD-024`. This script is what found that and is what will
notice if a later release puts it back, so the answer is measured on the day rather than
remembered from this one.

Exit code 0 when the chain works end to end. The actor claim is reported either way, because
which claim carries it is the finding, not a pass or a fail.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import sys

import requests

REALM = os.environ.get("AQUAFLUX_REALM", "https://idp.aquaflux.internal/realms/aquaflux")
TOKEN_ENDPOINT = f"{REALM}/protocol/openid-connect/token"
NADIA_PASSWORD = os.environ.get("LAB_NADIA_PASSWORD", "nadia")
AGENT_SECRET = os.environ.get("LAB_AGENT_SECRET", "reading-assistant-secret")

EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
ACCESS_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:access_token"


def claims(token: str) -> dict:
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


def post(**form) -> dict:
    reply = requests.post(TOKEN_ENDPOINT, data=form, timeout=30)
    body = reply.json()
    if "access_token" not in body:
        raise SystemExit(
            f"  FAIL  {form.get('grant_type')}: {body.get('error')}: {body.get('error_description')}"
        )
    return body


def main() -> int:
    failures = []

    nadia = post(
        grant_type="password",
        client_id="service-desk",
        username="nadia",
        password=NADIA_PASSWORD,
    )["access_token"]
    n = claims(nadia)
    print(f"  Nadia          sub={n.get('preferred_username')}  aud={n.get('aud')}")
    if "reading-assistant" not in json.dumps(n.get("aud")):
        failures.append(
            "Nadia's token does not name the reading assistant in its audience, so the agent "
            "cannot exchange it. Keycloak refuses with 'Client is not within the token audience'."
        )

    agent = post(
        grant_type="client_credentials",
        client_id="reading-assistant",
        client_secret=AGENT_SECRET,
    )["access_token"]
    print(f"  Agent          azp={claims(agent).get('azp')}")

    exchanged = post(
        grant_type=EXCHANGE,
        client_id="reading-assistant",
        client_secret=AGENT_SECRET,
        subject_token=nadia,
        subject_token_type=ACCESS_TOKEN_TYPE,
        actor_token=agent,
        actor_token_type=ACCESS_TOKEN_TYPE,
        audience="wom-api",
        scope="workorder:create",
    )["access_token"]
    e = claims(exchanged)
    lifetime = e["exp"] - e["iat"]
    print(
        f"  Exchanged      sub={e.get('preferred_username')}  aud={e.get('aud')}  "
        f"scope={e.get('scope')!r}  azp={e.get('azp')}  act={e.get('act')}  life={lifetime}s"
    )

    # carry-the-authority's acceptance check, line by line.
    if e.get("preferred_username") != "nadia":
        failures.append("the exchanged token's subject is not Nadia")
    if e.get("aud") != "wom-api":
        failures.append(f"aud is {e.get('aud')!r}, and the check wants the work order API and nothing else")
    if e.get("scope") != "workorder:create":
        failures.append(f"scope is {e.get('scope')!r}, and the check wants workorder:create alone")
    if not 0 < lifetime <= 900:
        failures.append(f"lifetime is {lifetime}s, and the check wants minutes")

    print()
    if e.get("act"):
        print(f"  The actor is in the act claim, as RFC 8693 describes it: {e['act']}")
    else:
        print(
            "  NOTE  There is no act claim. This identity provider records the actor of a\n"
            "        standard exchange in azp instead, which names "
            f"{e.get('azp')!r} above.\n"
            "        carry-the-authority's acceptance check asks for act, so this is OD-024, open. The lab's\n"
            "        substance is unaffected: the token is still delegated, still narrowed to\n"
            "        one audience and one scope, and still attributable to both parties."
        )

    # The other half of the delegation lesson: the narrowing has to be real. The values below
    # are read from the agent's own deployed configuration rather than written here, because
    # that file is where carry-the-authority's seeded fault lives and a copy of it here would drift.
    print()
    deployed = json.loads(
        (pathlib.Path(__file__).resolve().parent / "agent" / "reading-assistant.json").read_text()
    )["token_exchange"]
    wide = post(
        grant_type=EXCHANGE,
        client_id="reading-assistant",
        client_secret=AGENT_SECRET,
        subject_token=nadia,
        subject_token_type=ACCESS_TOKEN_TYPE,
        actor_token=agent,
        actor_token_type=ACCESS_TOKEN_TYPE,
        audience=deployed["audience"],
        scope=deployed["scope"],
    )["access_token"]
    w = claims(wide)
    print(f"  Seeded fault   aud={w.get('aud')}  scope={w.get('scope')!r}")
    if w.get("aud") != "mdm-api":
        failures.append(
            "the agent's deployed configuration no longer produces a token for the meter data "
            "system, so carry-the-authority's seeded fault has stopped being a fault"
        )
    if "workorder:close" not in (w.get("scope") or ""):
        failures.append(
            "the agent's deployed configuration no longer over-scopes, so carry-the-authority's second fault "
            "has gone"
        )

    if failures:
        print()
        for line in failures:
            print(f"  FAIL  {line}", file=sys.stderr)
        return 1
    print("\nThe delegation chain works: Nadia to the agent to one audience and one scope.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
