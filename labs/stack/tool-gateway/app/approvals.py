"""The active approvals, fetched before every decision.

The approval service is the notary; the policy is the judge. This module is the clerk that
carries the records from one to the other. It fetches whatever is active and hands the list to
the engine, whichever engine, as `input.approvals`. It does not filter by tool or by connection:
binding an approval to a call is exactly the thing the policy is asked to do, and a clerk that
pre-filtered would be doing the judge's work out of sight.

When the service is not running, the list is empty and the log says so. Nothing else changes:
a hold stays a hold, an approval rule finds nothing to match. That is the right failure, because
"no approvals could be found" is what the absence of an approval service means.
"""

from __future__ import annotations

import os

import httpx

URL = os.environ.get("AQUAFLUX_APPROVALS_URL", "http://approvals:80")
TIMEOUT = 5.0


async def active() -> tuple[list[dict], str | None]:
    """The active approval records, and an error string if they could not be fetched."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(f"{URL}/approvals", params={"active": "true"})
            response.raise_for_status()
            rows = response.json()
    except Exception as error:  # noqa: BLE001
        return [], f"approvals unavailable: {str(error)[:120]}"
    return [row for row in rows if isinstance(row, dict)], None


async def use(approval_id: str, call_id: str, tool: str) -> str | None:
    """Spend the approval a decision relied on. None when it was spent, the reason when not.

    The clerk does not choose the approval: the decision names it, and this only carries the
    spending back to the notary. A failure to reach the service is a refusal too, because an
    approval that cannot be marked used could be used again.
    """
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(f"{URL}/approvals/{approval_id}/use",
                                         json={"call_id": call_id, "tool": tool})
    except Exception as error:  # noqa: BLE001
        return f"approval {approval_id} could not be marked used: {str(error)[:120]}"
    if response.status_code == 200:
        return None
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    return str(detail or f"approval {approval_id} could not be marked used: HTTP {response.status_code}")


def compact(rows: list[dict]) -> list[dict]:
    """What the decision record keeps of each approval presented: enough to find it again."""
    return [
        {
            "approval_id": row.get("approval_id"),
            "action": row.get("action"),
            "connection_id": row.get("connection_id"),
            "approver": row.get("approver"),
            "approver_role": row.get("approver_role"),
        }
        for row in rows
    ]
