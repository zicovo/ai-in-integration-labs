"""The work order API, as much of it as two tools need.

Compare this with `generated/wom.py`. That one is a single function that can reach any operation,
because it was written without knowing which operations would be exposed. This one names the two
it uses, fixes what must never be an argument, and has somewhere for a rule to live.
"""

from __future__ import annotations

import os
import sys

import requests

BASE = os.environ.get("AQUAFLUX_WOM", "https://wom.aquaflux.internal/v4")
TIMEOUT = 30


class WorkOrderApiError(RuntimeError):
    """The API refused. The refusal is the answer, so it is raised rather than swallowed."""


def _check(response: requests.Response) -> dict:
    if response.status_code >= 400:
        # A refusal is an answer, so it is returned rather than raised. The SDK turns an
        # exception into "Error executing tool X" with no detail, and the reason the API gave
        # is the most useful thing in the exchange.
        return {"error": response.status_code, "detail": response.text[:300]}
    return response.json()


def create(
    *,
    type: str,
    connection_id: str,
    reason: str | None = None,
    note: str | None = None,
    idempotency_key: str,
) -> dict:
    """Create one work order.

    `type` is a keyword argument of this function and never an argument of a tool. That is the
    line the whole lab turns on: a tool that takes the type can reach every type.
    """
    response = requests.post(
        f"{BASE}/work-orders",
        json={"connection_id": connection_id, "type": type, "reason": reason, "note": note},
        headers={"Idempotency-Key": idempotency_key},
        timeout=TIMEOUT,
    )
    if response.status_code == 409:
        # The key was used before, so the API returned the original rather than creating a
        # second one. That is a success for the caller and it is what step five looks for, so
        # it is also written to this server's own log, where the handout sends the learner.
        original = response.json()
        print(f"409 from the work order API: Idempotency-Key {idempotency_key} was used before, "
              f"returning the original work order {original.get('work_order_id')} and creating nothing",
              file=sys.stderr, flush=True)
        return {**original, "duplicate_of_request_id": idempotency_key, "created": False}
    return {**_check(response), "created": True}


def get(work_order_id: str) -> dict:
    """Read one work order."""
    return _check(requests.get(f"{BASE}/work-orders/{work_order_id}", timeout=TIMEOUT))
