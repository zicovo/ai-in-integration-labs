"""Two Aquaflux work order intents, published as MCP tools.

This is the worked tier's answer, and it is meant to be read beside `generated/server.py`. The
difference between the two files is the lab.

Read the tools in this order: the name, then the docstring, then the type hints, then the line
in the adapter that fixes `type`.
"""

from __future__ import annotations

from typing import Literal

from mcp.server import MCPServer

import wom

mcp = MCPServer("aquaflux-work-orders")


@mcp.tool(annotations={
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
})
def create_meter_check_work_order(
    connection_id: str,
    reason: Literal["disputed_reading", "implausible_consumption", "meter_not_readable"],
    request_id: str,
    note: str | None = None,
) -> dict:
    """Create a work order for a technician to inspect the water meter of one connection.

    Use this when a customer disputes a reading or when consumption is implausible for the
    connection. Do not use it for leaks, outages or disconnections. The work order is created
    in proposed state and needs approval by the service desk before it is scheduled.
    Returns the work order id and its state.

    connection_id: the Aquaflux connection number as printed on the invoice, four to eight digits.
    reason: why the meter should be checked.
    request_id: idempotency key, a UUID. Reuse the same value when retrying the same request.
    note: free text for the technician. Never include payment or contact details.
    """
    return wom.create(type="meter_check", connection_id=connection_id,
                      reason=reason, note=note, idempotency_key=request_id)


@mcp.tool(annotations={
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
})
def get_work_order_status(work_order_id: str) -> dict:
    """Read the current state of one Aquaflux work order.

    Use this to answer "what happened to the job I raised". Do not use it to find work orders for
    a connection or a customer; it takes a work order id and nothing else. The state is one of
    proposed, approved, scheduled, in progress, completed, cancelled or rejected.
    Returns the state, the type, the connection, and the date and technician once one is assigned.

    work_order_id: the identifier returned when the work order was created.
    """
    order = wom.get(work_order_id)
    return {
        "work_order_id": order["work_order_id"],
        "state": order["state"],
        "type": order["type"],
        "connection_id": order["connection_id"],
        "scheduled_for": order.get("scheduled_for"),
        "technician": order.get("technician"),
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8850)
