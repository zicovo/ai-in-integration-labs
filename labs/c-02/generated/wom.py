"""The HTTP call behind every generated tool.

One function, because a generated adapter has one shape: take the flat bag of arguments a tool
call arrives with, put each one back where the API expects it, and return what came back.

It holds no business rule. That is correct here and it is also the point: there is nowhere in a
generated adapter for a rule to live, so a catalogue built this way can only be governed by the
names in it.
"""

from __future__ import annotations

import os

import requests

BASE = os.environ.get("AQUAFLUX_WOM", "https://wom.aquaflux.internal/v4")
TIMEOUT = 30


class WorkOrderApiError(RuntimeError):
    """The API refused, and the refusal is the answer the caller needs to see."""


def call(
    method: str,
    route: str,
    *,
    path_params: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
    body: dict[str, str] | None = None,
    header: dict[str, str] | None = None,
    values: dict[str, object] | None = None,
) -> dict:
    """Send one request. `values` is the tool's `locals()`; the maps say where each one goes."""
    values = dict(values or {})

    url = BASE + route.removeprefix("/v4")
    for argument, wire in (path_params or {}).items():
        url = url.replace("{" + wire + "}", str(values.get(argument, "")))

    params = {wire: values[arg] for arg, wire in (query or {}).items()
              if values.get(arg) is not None}
    headers = {wire: str(values[arg]) for arg, wire in (header or {}).items()
               if values.get(arg) is not None}
    payload = {wire: values[arg] for arg, wire in (body or {}).items()
               if values.get(arg) is not None}

    response = requests.request(
        method,
        url,
        params=params or None,
        json=payload if payload else None,
        headers=headers or None,
        timeout=TIMEOUT,
    )
    if response.status_code >= 400:
        # Returned, not raised. The SDK turns an exception into "Error executing tool X" with
        # no detail, so a raise here costs the model the reason and the learner the message.
        # A refusal is an answer.
        return {"error": response.status_code, "detail": response.text[:300],
                "request": f"{method} {url}"}
    if not response.content:
        return {"status": response.status_code}
    result = response.json()
    return result if isinstance(result, dict) else {"items": result}
