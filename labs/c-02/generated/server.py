"""The work order API as MCP tools, generated from its OpenAPI document.

DO NOT EDIT. Regenerate with `python3 labs/c-02/generate.py`.

Twenty-three operations in, twenty-three tools out, each docstring copied from the operation
summary in the document. This file is c-02's starting point and its deliberate failure: read it,
run it, and read the gateway log before you read anything else.
"""

from __future__ import annotations

from mcp.server import MCPServer

from wom import call

mcp = MCPServer("aquaflux-work-orders-generated")


@mcp.tool()
def list_work_orders(connection_id: str | None = None, state: str | None = None) -> dict:
    """List work orders."""
    return call(
        "GET",
        "/v4/work-orders",
        path_params={},
        query={"connection_id": "connection_id", "state": "state"},
        body={},
        header={},
        values=locals(),
    )


@mcp.tool()
def create_work_order(idempotency_key: str, connection_id: str, type: str, reason: str | None = None, note: str | None = None) -> dict:
    """Create a work order of any type."""
    return call(
        "POST",
        "/v4/work-orders",
        path_params={},
        query={},
        body={"connection_id": "connection_id", "type": "type", "reason": "reason", "note": "note"},
        header={"idempotency_key": "Idempotency-Key"},
        values=locals(),
    )


@mcp.tool()
def get_work_order(work_order_id: str) -> dict:
    """Read one work order."""
    return call(
        "GET",
        "/v4/work-orders/{work_order_id}",
        path_params={"work_order_id": "work_order_id"},
        query={},
        body={},
        header={},
        values=locals(),
    )


@mcp.tool()
def update_work_order(work_order_id: str, reason: str | None = None, note: str | None = None, priority: str | None = None) -> dict:
    """Update the reason, note or priority of one work order."""
    return call(
        "PATCH",
        "/v4/work-orders/{work_order_id}",
        path_params={"work_order_id": "work_order_id"},
        query={},
        body={"reason": "reason", "note": "note", "priority": "priority"},
        header={},
        values=locals(),
    )


@mcp.tool()
def list_work_order_types() -> dict:
    """List the work order types this installation supports."""
    return call(
        "GET",
        "/v4/work-order-types",
        path_params={},
        query={},
        body={},
        header={},
        values=locals(),
    )


@mcp.tool()
def list_technicians(skill: str | None = None, region: str | None = None) -> dict:
    """List field technicians."""
    return call(
        "GET",
        "/v4/technicians",
        path_params={},
        query={"skill": "skill", "region": "region"},
        body={},
        header={},
        values=locals(),
    )


@mcp.tool()
def get_technician(technician_id: str) -> dict:
    """Read one field technician."""
    return call(
        "GET",
        "/v4/technicians/{technician_id}",
        path_params={"technician_id": "technician_id"},
        query={},
        body={},
        header={},
        values=locals(),
    )


@mcp.tool()
def get_technician_schedule(technician_id: str) -> dict:
    """List the work orders assigned to one technician."""
    return call(
        "GET",
        "/v4/technicians/{technician_id}/schedule",
        path_params={"technician_id": "technician_id"},
        query={},
        body={},
        header={},
        values=locals(),
    )


@mcp.tool()
def list_appointment_slots(region: str | None = None) -> dict:
    """List free appointment slots in the field force diary."""
    return call(
        "GET",
        "/v4/appointment-slots",
        path_params={},
        query={"region": "region"},
        body={},
        header={},
        values=locals(),
    )


@mcp.tool()
def list_work_orders_for_connection(connection_id: str) -> dict:
    """List every work order raised on one connection."""
    return call(
        "GET",
        "/v4/connections/{connection_id}/work-orders",
        path_params={"connection_id": "connection_id"},
        query={},
        body={},
        header={},
        values=locals(),
    )


@mcp.tool()
def get_work_order_history(work_order_id: str) -> dict:
    """Read the state history of one work order."""
    return call(
        "GET",
        "/v4/work-orders/{work_order_id}/history",
        path_params={"work_order_id": "work_order_id"},
        query={},
        body={},
        header={},
        values=locals(),
    )


@mcp.tool()
def list_work_order_notes(work_order_id: str) -> dict:
    """List the notes on one work order."""
    return call(
        "GET",
        "/v4/work-orders/{work_order_id}/notes",
        path_params={"work_order_id": "work_order_id"},
        query={},
        body={},
        header={},
        values=locals(),
    )


@mcp.tool()
def add_work_order_note(work_order_id: str, body: str, author: str | None = None) -> dict:
    """Add a note to one work order."""
    return call(
        "POST",
        "/v4/work-orders/{work_order_id}/notes",
        path_params={"work_order_id": "work_order_id"},
        query={},
        body={"body": "body", "author": "author"},
        header={},
        values=locals(),
    )


@mcp.tool()
def list_work_order_attachments(work_order_id: str) -> dict:
    """List the attachments on one work order."""
    return call(
        "GET",
        "/v4/work-orders/{work_order_id}/attachments",
        path_params={"work_order_id": "work_order_id"},
        query={},
        body={},
        header={},
        values=locals(),
    )


@mcp.tool()
def add_work_order_attachment(work_order_id: str, filename: str, media_type: str, description: str | None = None) -> dict:
    """Register an attachment against one work order."""
    return call(
        "POST",
        "/v4/work-orders/{work_order_id}/attachments",
        path_params={"work_order_id": "work_order_id"},
        query={},
        body={"filename": "filename", "media_type": "media_type", "description": "description"},
        header={},
        values=locals(),
    )


@mcp.tool()
def approve_work_order(work_order_id: str, decided_by: str, comment: str | None = None) -> dict:
    """Approve a proposed work order so it can be scheduled."""
    return call(
        "POST",
        "/v4/work-orders/{work_order_id}/approve",
        path_params={"work_order_id": "work_order_id"},
        query={},
        body={"decided_by": "decided_by", "comment": "comment"},
        header={},
        values=locals(),
    )


@mcp.tool()
def reject_work_order(work_order_id: str, decided_by: str, comment: str | None = None) -> dict:
    """Reject a proposed work order."""
    return call(
        "POST",
        "/v4/work-orders/{work_order_id}/reject",
        path_params={"work_order_id": "work_order_id"},
        query={},
        body={"decided_by": "decided_by", "comment": "comment"},
        header={},
        values=locals(),
    )


@mcp.tool()
def schedule_work_order(work_order_id: str, scheduled_for: str, slot_id: str | None = None) -> dict:
    """Schedule an approved work order for a date."""
    return call(
        "POST",
        "/v4/work-orders/{work_order_id}/schedule",
        path_params={"work_order_id": "work_order_id"},
        query={},
        body={"scheduled_for": "scheduled_for", "slot_id": "slot_id"},
        header={},
        values=locals(),
    )


@mcp.tool()
def assign_work_order(work_order_id: str, technician_id: str) -> dict:
    """Assign a work order to a field technician."""
    return call(
        "POST",
        "/v4/work-orders/{work_order_id}/assign",
        path_params={"work_order_id": "work_order_id"},
        query={},
        body={"technician_id": "technician_id"},
        header={},
        values=locals(),
    )


@mcp.tool()
def start_work_order(work_order_id: str) -> dict:
    """Mark a scheduled work order as started by the technician."""
    return call(
        "POST",
        "/v4/work-orders/{work_order_id}/start",
        path_params={"work_order_id": "work_order_id"},
        query={},
        body={},
        header={},
        values=locals(),
    )


@mcp.tool()
def complete_work_order(work_order_id: str, outcome: str, report: str | None = None) -> dict:
    """Complete a work order with an outcome."""
    return call(
        "POST",
        "/v4/work-orders/{work_order_id}/complete",
        path_params={"work_order_id": "work_order_id"},
        query={},
        body={"outcome": "outcome", "report": "report"},
        header={},
        values=locals(),
    )


@mcp.tool()
def cancel_work_order(work_order_id: str, decided_by: str, comment: str | None = None) -> dict:
    """Cancel a work order that has not been completed."""
    return call(
        "POST",
        "/v4/work-orders/{work_order_id}/cancel",
        path_params={"work_order_id": "work_order_id"},
        query={},
        body={"decided_by": "decided_by", "comment": "comment"},
        header={},
        values=locals(),
    )


@mcp.tool()
def reopen_work_order(work_order_id: str, decided_by: str, comment: str | None = None) -> dict:
    """Reopen a completed or cancelled work order."""
    return call(
        "POST",
        "/v4/work-orders/{work_order_id}/reopen",
        path_params={"work_order_id": "work_order_id"},
        query={},
        body={"decided_by": "decided_by", "comment": "comment"},
        header={},
        values=locals(),
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8851)
