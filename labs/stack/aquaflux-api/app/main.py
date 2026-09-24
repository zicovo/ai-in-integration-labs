"""The three Aquaflux stand-in APIs.

One image, three containers. `AQUAFLUX_SYSTEM` selects which system of record this container is:

    mdm   meter data management        mdm.aquaflux.internal
    cis   customer information system  cis.aquaflux.internal
    wom   work order management        wom.aquaflux.internal

They are stand-ins, not simulations. Each exposes exactly what the handouts that name it need, and
two of their design decisions are deliberate and are defended in c-02's debrief: `type` is an enum
at the API level, so the API cannot reject the wrong work order type on an agent's behalf, and
`Idempotency-Key` is a required header rather than an optional one, so a tool that omits it fails
loudly instead of quietly creating duplicates.

State is in memory. Restarting a container re-seeds it, which is what a learner re-running a lab
wants.
"""

from __future__ import annotations

import os
import re
from typing import Annotated, Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import bearer, seed, views

SYSTEM = os.environ.get("AQUAFLUX_SYSTEM", "").lower()

TITLES = {
    "mdm": "Aquaflux meter data management",
    "cis": "Aquaflux customer information system",
    "wom": "Aquaflux work order management",
}

if SYSTEM not in TITLES:
    raise SystemExit(
        f"AQUAFLUX_SYSTEM must be one of {', '.join(sorted(TITLES))}, got {SYSTEM!r}. "
        "labs/stack/docker-compose.yml sets it."
    )


def operation_id(route: APIRoute) -> str:
    """camelCase operation ids, derived from the handler name.

    FastAPI's default is `create_work_order_v4_work_orders_post`, which is unique and unreadable.
    A generator pointed at this document turns the operation id into a tool name, so c-02's
    catalogue would carry twenty-three of those. The names in the handout are `createWorkOrder`
    and `getWorkOrder`, which is what a hand-written API description looks like, so the stand-in
    produces those instead.
    """
    head, *rest = route.name.split("_")
    return head + "".join(word.capitalize() for word in rest)


# `docs_url=None` because the default page loads Swagger from a CDN, and a participant with no
# internet would get a blank page where the API should be. The assets are in the image.
app = FastAPI(
    title=TITLES[SYSTEM],
    version="4.2" if SYSTEM == "wom" else "1.0",
    docs_url=None,
    generate_unique_id_function=operation_id,
)
app.mount("/static", StaticFiles(directory="/srv/static"), name="static")


@app.get("/docs", include_in_schema=False)
def docs() -> object:
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=f"{TITLES[SYSTEM]}, API",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
    )


CONNECTIONS = set(seed.connection_ids())

# The read-only page at `/` (app/views.py). Out of the schema, because c-02's generated catalogue
# is every operation in the schema and a page is not a tool.
# A refresh outside two to sixty seconds is clamped rather than refused: a 422 in JSON is a poor
# answer to a URL typed into the lab browser.
Refresh = Annotated[int | None, Query()]


def _refresh(value: int | None) -> int | None:
    return None if not value else max(2, min(60, value))


@app.get("/health", include_in_schema=False)
def health() -> dict:
    return {"status": "ok", "system": SYSTEM, "connections": len(CONNECTIONS)}


# ---------------------------------------------------------------- meter data management


if SYSTEM == "mdm":

    @app.get("/readings")
    def get_readings(
        connection_id: Annotated[str, Query(description="The Aquaflux connection id, digits only")],
        from_: Annotated[str | None, Query(alias="from")] = None,
        to: Annotated[str | None, Query()] = None,
    ) -> list[dict]:
        """Monthly consumption for one connection over a period.

        `from` and `to` are ISO dates. A reading is returned when its period overlaps them. Both
        are optional here so that a learner exploring the API by hand is not blocked by them; the
        tool definition in a-02 requires them, which is the point of that lab.
        """
        if connection_id not in CONNECTIONS:
            raise HTTPException(404, f"No such connection: {connection_id}")
        rows = seed.readings(connection_id)
        if from_:
            rows = [r for r in rows if r["period_end"] >= from_]
        if to:
            rows = [r for r in rows if r["period_start"] <= to]
        return rows

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    def page(connection_id: Annotated[str, Query()] = seed.NADIA_CONNECTION,
             refresh: Refresh = None) -> str:
        known = connection_id in CONNECTIONS
        return views.readings(connection_id, seed.customer(connection_id) if known else None,
                              seed.readings(connection_id) if known else None, _refresh(refresh))


# ---------------------------------------------------------- customer information system


if SYSTEM == "cis":

    @app.get("/customers/{connection_id}")
    def get_customer(connection_id: str) -> dict:
        if connection_id not in CONNECTIONS:
            raise HTTPException(404, f"No such connection: {connection_id}")
        record = seed.customer(connection_id)
        record["in_arrears"] = seed.in_arrears(connection_id)
        return record

    # Dunning cases are the one thing in this system that moves: the collections agent sends
    # reminders and proposes disconnections against them, and f-01 swaps the note on case 4471.
    # State is in memory and re-seeded on restart or on `POST /dunning/_reset`, like work orders.
    _cases: dict[str, dict] = {}
    _fixture = ["note-variant-a"]
    # A learner's own note, f-01 step four. Kept across `_reset` so `--fixture own` reloads it.
    _own_note: dict[str, str] = {}

    def _reset_cases() -> None:
        _cases.clear()
        _fixture[0] = "note-variant-a"
        for connection_id in CONNECTIONS:
            case = seed.dunning_case(connection_id)
            if case is not None:
                case["customer"] = seed.customer(connection_id)["customer_name"]
                case["reminders"] = []
                case["proposals"] = []
                _cases[connection_id] = case

    _reset_cases()

    def _case(case_id: str) -> dict:
        if case_id not in CONNECTIONS:
            raise HTTPException(404, f"No such connection: {case_id}")
        if case_id not in _cases:
            raise HTTPException(404, f"Connection {case_id} is not in arrears, so it has no case")
        return _cases[case_id]

    class ReminderPayload(BaseModel):
        channel: Literal["letter", "email", "sms"] = "letter"

    class ProposalPayload(BaseModel):
        reason: str = Field(max_length=200)
        proposed_by: str | None = Field(default=None, max_length=60)

    class FixturePayload(BaseModel):
        note: str
        text: str | None = Field(default=None, max_length=1200)

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    def page(case: Annotated[str | None, Query()] = None, refresh: Refresh = None) -> str:
        return views.dunning_cases(list(_cases.values()), _fixture[0], case or None, _refresh(refresh))

    # The fixed paths first, so `_reset` and `_fixtures` are not read as case ids.

    @app.post("/dunning/_reset", include_in_schema=False)
    def reset_cases() -> dict:
        """Put every case back the way the seed left it. smoke.sh and verify.sh call it."""
        _reset_cases()
        return {"reset": True, "cases": len(_cases), "fixture": _fixture[0]}

    @app.get("/dunning/_fixtures", include_in_schema=False)
    def list_fixtures() -> dict:
        """Which notes case 4471 can carry, and which it carries now. `aqx fixture` reads this."""
        available = sorted(seed.NOTE_FIXTURES) + (["own"] if _own_note else [])
        return {"active": _fixture[0], "available": available}

    @app.get("/dunning/{case_id}")
    def get_dunning_case(case_id: str) -> dict:
        """The dunning state for one connection, with any customer notes attached.

        f-01 reads case 4471 and its note. The note is data. Whether anything downstream treats it
        as data is the question that lab exists to ask.
        """
        return _case(case_id)

    @app.get("/dunning/{case_id}/payments")
    def get_payments(case_id: str) -> list[dict]:
        """Recent invoices and payments for one overdue connection, newest first."""
        _case(case_id)
        return seed.payments(case_id)

    @app.post("/dunning/{case_id}/reminders", status_code=201)
    def send_reminder(case_id: str, body: ReminderPayload) -> dict:
        """Record the next reminder and advance the dunning state. Nothing is disconnected."""
        case = _case(case_id)
        steps = ["reminder_1", "reminder_2", "final_notice", "final_notice"]
        current = case["state"]
        if current in steps:
            case["state"] = steps[min(steps.index(current) + 1, len(steps) - 1)]
        reminder = {
            "reminder_id": f"rem-{case_id}-{len(case['reminders']) + 1}",
            "sent_at": seed.now(),
            "channel": body.channel,
            "state_after": case["state"],
        }
        case["reminders"].append(reminder)
        return reminder

    @app.post("/dunning/{case_id}/proposals", status_code=201)
    def propose_disconnection(case_id: str, body: ProposalPayload) -> dict:
        """Record a disconnection proposal for a team lead to review. Creates no work order."""
        case = _case(case_id)
        case["state"] = "disconnection_proposed"
        proposal = {
            "proposal_id": f"prop-{case_id}-{len(case['proposals']) + 1}",
            "proposed_at": seed.now(),
            "action": "disconnection",
            "reason": body.reason,
            "proposed_by": body.proposed_by,
            "state": "awaiting_team_lead",
        }
        case["proposals"].append(proposal)
        return proposal

    @app.post("/dunning/{case_id}/_fixture", include_in_schema=False)
    def load_fixture(case_id: str, body: FixturePayload) -> dict:
        """Swap the note on a case.

        f-01's second fixture arrives this way, through `aqx fixture`. So does the learner's own
        note in step four: `{"note": "own", "text": "..."}` stores the wording and applies it, and
        `{"note": "own"}` afterwards reapplies the stored one, so `--fixture own` works on a run.
        """
        case = _case(case_id)
        if body.note == "own":
            if body.text is not None and body.text.strip():
                _own_note["text"] = body.text.strip()
            if "text" not in _own_note:
                raise HTTPException(404, "No note of your own yet. Load it once with its text: "
                                         "aqx fixture load own --text '...' --case 4471")
            text: str | None = _own_note["text"]
        elif body.note in seed.NOTE_FIXTURES:
            text = seed.NOTE_FIXTURES[body.note]
        else:
            known = ", ".join(sorted(seed.NOTE_FIXTURES) + ["own"])
            raise HTTPException(404, f"No fixture called {body.note}. There is {known}.")
        case["notes"] = [] if text is None else [
            {"note_id": f"note-{case_id}-1", "created_at": "2026-06-14T09:12:00Z",
             "author": "customer_contact", "body": text}
        ]
        _fixture[0] = body.note
        return {"case_id": case_id, "fixture": body.note, "notes": case["notes"]}


# ------------------------------------------------------------ work order management


CONNECTION_PATTERN = re.compile(r"^[0-9]{4,8}$")

WorkOrderType = Literal[
    "inspection", "repair", "meter_swap", "meter_check", "disconnection", "reconnection"
]


class CreateWorkOrder(BaseModel):
    connection_id: str = Field(pattern=r"^[0-9]{4,8}$")
    type: WorkOrderType
    reason: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=300)


if SYSTEM == "wom":

    @app.get("/.well-known/oauth-protected-resource", include_in_schema=False)
    def protected_resource_metadata() -> dict:
        """RFC 9728. d-02's completion tier reads the audience and the scopes from here.

        The handout is explicit that the learner may not guess those two values, which is the
        point: a resource says what it is called and what may be asked of it, and a client reads
        that rather than copying another client's configuration. Copying another client's
        configuration is exactly the seeded fault.
        """
        return {
            "resource": "https://wom.aquaflux.internal/v4",
            "resource_name": "Aquaflux work order API",
            "authorization_servers": [bearer.ISSUER],
            "scopes_supported": ["workorder:create", "workorder:read", "workorder:close"],
            "bearer_methods_supported": ["header"],
            "token_audience": bearer.AUDIENCE or "wom-api",
        }

    _orders: dict[str, dict] = {}
    _by_key: dict[str, str] = {}
    _next_id = [92000]

    def _reset() -> None:
        _orders.clear()
        _by_key.clear()
        _next_id[0] = 92000
        for order in seed.SEEDED_WORK_ORDERS:
            record = dict(order)
            _orders[record["work_order_id"]] = record
            _by_key[record["idempotency_key"]] = record["work_order_id"]

    _reset()

    @app.get("/v4/work-orders", summary="List work orders")
    def list_work_orders(
        connection_id: Annotated[str | None, Query()] = None,
        state: Annotated[str | None, Query()] = None,
    ) -> list[dict]:
        rows = list(_orders.values())
        if connection_id:
            rows = [r for r in rows if r["connection_id"] == connection_id]
        if state:
            rows = [r for r in rows if r["state"] == state]
        return sorted(rows, key=lambda r: r["work_order_id"])

    @app.get("/v4/work-orders/{work_order_id}", summary="Read one work order")
    def get_work_order(work_order_id: str, request: Request) -> dict:
        bearer.authorise(request, scope="workorder:read")
        if work_order_id not in _orders:
            raise HTTPException(404, f"No such work order: {work_order_id}")
        return _orders[work_order_id]

    @app.post("/v4/work-orders", status_code=201, summary="Create a work order of any type")
    def create_work_order(
        body: CreateWorkOrder,
        request: Request,
        response: Response,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> dict:
        """Create a work order of any type.

        The API deliberately does not judge whether an agent should have chosen this type. That is
        c-02's lesson: a disconnection requested for a billing query is accepted here, because the
        enum says `disconnection` is a valid value and nothing at this layer knows who asked or
        why. The control belongs in the tool contract and in the policy, not here.
        """
        claims = bearer.authorise(request, scope="workorder:create")

        # An opaque string, not a UUID. The document says `format: uuid`, because a UUID is what
        # a caller should use, and the API stores whatever it is given. Two labs depend on that
        # lenience: c-02's generated catalogue drops the format along with every other
        # constraint, and e-03's `broken/` derives its key from the clock, which is the fault
        # that lab exists to show. An API that rejected both would hide both.
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise HTTPException(422, "Idempotency-Key must be a non-empty string of at most 200 characters")

        if idempotency_key in _by_key:
            original = _orders[_by_key[idempotency_key]]
            response.status_code = 409
            return original

        if body.connection_id not in CONNECTIONS:
            raise HTTPException(422, f"No such connection: {body.connection_id}")

        if body.type == "reconnection" and not any(
            o["connection_id"] == body.connection_id and o["type"] == "disconnection"
            and o["state"] == "completed"
            for o in _orders.values()
        ):
            raise HTTPException(
                422, f"Connection {body.connection_id} is not disconnected, so it cannot be reconnected"
            )

        _next_id[0] += 1
        work_order_id = str(_next_id[0])
        record = {
            "work_order_id": work_order_id,
            "connection_id": body.connection_id,
            "type": body.type,
            "state": "proposed",
            "reason": body.reason,
            "note": body.note,
            "created_at": seed.now(),
            "idempotency_key": idempotency_key,
            "scheduled_for": None,
            "technician": None,
            # Who asked, and on whose authority. Null when no token was presented, which is how
            # c-02 runs: that lab is about the tool contract and says nothing about identity.
            "created_by": bearer.actor(claims),
        }
        _orders[work_order_id] = record
        _by_key[idempotency_key] = work_order_id
        return record

    @app.delete("/v4/work-orders", include_in_schema=False)
    def clear_work_orders(connection_id: Annotated[str, Query()]) -> dict:
        """Clear one connection's work orders. Used by `smoke.sh e-03` between attempts.

        Not part of the API the handouts teach, which is why it is out of the schema.
        """
        removed = [r for r in _orders.values() if r["connection_id"] == connection_id]
        for record in removed:
            _orders.pop(record["work_order_id"], None)
            _by_key.pop(record["idempotency_key"], None)
        return {"cleared": len(removed), "connection_id": connection_id}

    @app.post("/v4/_reset", include_in_schema=False)
    def reset() -> dict:
        _reset()
        return {"reset": True, "work_orders": len(_orders)}

    # ---------------------------------------------------------- the rest of the API
    #
    # Twenty-three operations in total. That number is not decoration: c-02's `generated/` server
    # is produced by pointing a generator at this document, and the lab turns on the difference
    # between twenty-three tools and two. Its open tier asks the learner to name two of the
    # twenty-one they did not expose and the one they would refuse on principle, so the list has
    # to be a plausible work order API rather than three endpoints and some filler.
    #
    # They are thin on purpose. Nothing below is a simulation of field service management; each
    # one does the least that makes it honest to call it by its name.

    class WorkOrderPatch(BaseModel):
        reason: str | None = Field(default=None, max_length=120)
        note: str | None = Field(default=None, max_length=300)
        priority: Literal["low", "normal", "high"] | None = None

    class SchedulePayload(BaseModel):
        scheduled_for: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
        slot_id: str | None = None

    class AssignPayload(BaseModel):
        technician_id: str

    class DecisionPayload(BaseModel):
        decided_by: str
        comment: str | None = Field(default=None, max_length=300)

    class NotePayload(BaseModel):
        body: str = Field(max_length=300)
        author: str | None = None

    class AttachmentPayload(BaseModel):
        filename: str = Field(max_length=120)
        media_type: str = Field(max_length=80)
        description: str | None = Field(default=None, max_length=200)

    class CompletionPayload(BaseModel):
        outcome: Literal["resolved", "no_access", "not_required", "escalated"]
        report: str | None = Field(default=None, max_length=300)

    _history: dict[str, list[dict]] = {}
    _notes: dict[str, list[dict]] = {}
    _attachments: dict[str, list[dict]] = {}

    def _order(work_order_id: str) -> dict:
        if work_order_id not in _orders:
            raise HTTPException(404, f"No such work order: {work_order_id}")
        return _orders[work_order_id]

    def _record(work_order_id: str, event: str, detail: str | None = None) -> None:
        _history.setdefault(work_order_id, []).append(
            {"at": seed.now(), "event": event, "detail": detail}
        )

    def _transition(order: dict, to: str, allowed_from: tuple[str, ...]) -> None:
        if order["state"] not in allowed_from:
            raise HTTPException(
                409,
                f"A work order in state {order['state']} cannot become {to}; "
                f"this transition is allowed from {', '.join(allowed_from)}",
            )
        order["state"] = to

    @app.get("/v4/work-order-types", summary="List the work order types this installation supports")
    def list_work_order_types() -> list[dict]:
        """List the work order types this installation supports."""
        return seed.WORK_ORDER_TYPE_CATALOGUE

    @app.get("/v4/technicians", summary="List field technicians")
    def list_technicians(
        skill: Annotated[str | None, Query()] = None,
        region: Annotated[str | None, Query()] = None,
    ) -> list[dict]:
        """List field technicians."""
        rows = list(seed.TECHNICIANS)
        if skill:
            rows = [t for t in rows if skill in t["skills"]]
        if region:
            rows = [t for t in rows if t["region"] == region]
        return rows

    @app.get("/v4/technicians/{technician_id}", summary="Read one field technician")
    def get_technician(technician_id: str) -> dict:
        """Read one field technician."""
        for technician in seed.TECHNICIANS:
            if technician["technician_id"] == technician_id:
                return technician
        raise HTTPException(404, f"No such technician: {technician_id}")

    @app.get("/v4/technicians/{technician_id}/schedule", summary="List the work orders assigned to one technician")
    def get_technician_schedule(technician_id: str) -> list[dict]:
        """List the work orders assigned to one technician."""
        get_technician(technician_id)
        return [
            o for o in sorted(_orders.values(), key=lambda r: r["work_order_id"])
            if o.get("technician_id") == technician_id
        ]

    @app.get("/v4/appointment-slots", summary="List free appointment slots in the field force diary")
    def list_appointment_slots(
        region: Annotated[str | None, Query()] = None,
    ) -> list[dict]:
        """List free appointment slots in the field force diary."""
        rows = seed.appointment_slots()
        if region:
            rows = [s for s in rows if s["region"] == region]
        return rows

    @app.get("/v4/connections/{connection_id}/work-orders", summary="List every work order raised on one connection")
    def list_work_orders_for_connection(connection_id: str) -> list[dict]:
        """List every work order raised on one connection."""
        if connection_id not in CONNECTIONS:
            raise HTTPException(404, f"No such connection: {connection_id}")
        return [o for o in sorted(_orders.values(), key=lambda r: r["work_order_id"])
                if o["connection_id"] == connection_id]

    @app.get("/v4/work-orders/{work_order_id}/history", summary="Read the state history of one work order")
    def get_work_order_history(work_order_id: str, request: Request) -> list[dict]:
        """Read the state history of one work order."""
        bearer.authorise(request, scope="workorder:read")
        _order(work_order_id)
        return _history.get(work_order_id, [])

    @app.get("/v4/work-orders/{work_order_id}/notes", summary="List the notes on one work order")
    def list_work_order_notes(work_order_id: str, request: Request) -> list[dict]:
        """List the notes on one work order."""
        bearer.authorise(request, scope="workorder:read")
        _order(work_order_id)
        return _notes.get(work_order_id, [])

    @app.get("/v4/work-orders/{work_order_id}/attachments", summary="List the attachments on one work order")
    def list_work_order_attachments(work_order_id: str, request: Request) -> list[dict]:
        """List the attachments on one work order."""
        bearer.authorise(request, scope="workorder:read")
        _order(work_order_id)
        return _attachments.get(work_order_id, [])

    @app.patch("/v4/work-orders/{work_order_id}", summary="Update the reason, note or priority of one work order")
    def update_work_order(work_order_id: str, body: WorkOrderPatch, request: Request) -> dict:
        """Update the reason, note or priority of one work order."""
        bearer.authorise(request, scope="workorder:create")
        order = _order(work_order_id)
        for field, value in body.model_dump(exclude_none=True).items():
            order[field] = value
        _record(work_order_id, "updated")
        return order

    @app.post("/v4/work-orders/{work_order_id}/approve", summary="Approve a proposed work order so it can be scheduled")
    def approve_work_order(work_order_id: str, body: DecisionPayload, request: Request) -> dict:
        """Approve a proposed work order so it can be scheduled."""
        bearer.authorise(request, scope="workorder:create")
        order = _order(work_order_id)
        _transition(order, "approved", ("proposed",))
        order["approved_by"] = body.decided_by
        _record(work_order_id, "approved", body.decided_by)
        return order

    @app.post("/v4/work-orders/{work_order_id}/reject", summary="Reject a proposed work order")
    def reject_work_order(work_order_id: str, body: DecisionPayload, request: Request) -> dict:
        """Reject a proposed work order."""
        bearer.authorise(request, scope="workorder:create")
        order = _order(work_order_id)
        _transition(order, "rejected", ("proposed",))
        order["rejected_by"] = body.decided_by
        _record(work_order_id, "rejected", body.comment)
        return order

    @app.post("/v4/work-orders/{work_order_id}/schedule", summary="Schedule an approved work order for a date")
    def schedule_work_order(work_order_id: str, body: SchedulePayload, request: Request) -> dict:
        """Schedule an approved work order for a date."""
        bearer.authorise(request, scope="workorder:create")
        order = _order(work_order_id)
        _transition(order, "scheduled", ("proposed", "approved"))
        order["scheduled_for"] = body.scheduled_for
        order["slot_id"] = body.slot_id
        _record(work_order_id, "scheduled", body.scheduled_for)
        return order

    @app.post("/v4/work-orders/{work_order_id}/assign", summary="Assign a work order to a field technician")
    def assign_work_order(work_order_id: str, body: AssignPayload, request: Request) -> dict:
        """Assign a work order to a field technician."""
        bearer.authorise(request, scope="workorder:create")
        order = _order(work_order_id)
        technician = get_technician(body.technician_id)
        if not technician["active"]:
            raise HTTPException(422, f"Technician {body.technician_id} is not active")
        order["technician_id"] = technician["technician_id"]
        order["technician"] = technician["name"]
        _record(work_order_id, "assigned", technician["name"])
        return order

    @app.post("/v4/work-orders/{work_order_id}/start", summary="Mark a scheduled work order as started by the technician")
    def start_work_order(work_order_id: str, request: Request) -> dict:
        """Mark a scheduled work order as started by the technician."""
        bearer.authorise(request, scope="workorder:close")
        order = _order(work_order_id)
        _transition(order, "in_progress", ("scheduled",))
        _record(work_order_id, "started")
        return order

    @app.post("/v4/work-orders/{work_order_id}/complete", summary="Complete a work order with an outcome")
    def complete_work_order(work_order_id: str, body: CompletionPayload, request: Request) -> dict:
        """Complete a work order with an outcome."""
        bearer.authorise(request, scope="workorder:close")
        order = _order(work_order_id)
        _transition(order, "completed", ("in_progress", "scheduled"))
        order["outcome"] = body.outcome
        order["report"] = body.report
        _record(work_order_id, "completed", body.outcome)
        return order

    @app.post("/v4/work-orders/{work_order_id}/cancel", summary="Cancel a work order that has not been completed")
    def cancel_work_order(work_order_id: str, body: DecisionPayload, request: Request) -> dict:
        """Cancel a work order that has not been completed."""
        bearer.authorise(request, scope="workorder:close")
        order = _order(work_order_id)
        _transition(order, "cancelled", ("proposed", "approved", "scheduled", "in_progress"))
        _record(work_order_id, "cancelled", body.comment)
        return order

    @app.post("/v4/work-orders/{work_order_id}/reopen", summary="Reopen a completed or cancelled work order")
    def reopen_work_order(work_order_id: str, body: DecisionPayload, request: Request) -> dict:
        """Reopen a completed or cancelled work order."""
        bearer.authorise(request, scope="workorder:close")
        order = _order(work_order_id)
        _transition(order, "proposed", ("completed", "cancelled", "rejected"))
        _record(work_order_id, "reopened", body.comment)
        return order

    @app.get("/", include_in_schema=False, response_class=HTMLResponse)
    def page(connection_id: Annotated[str | None, Query()] = None, refresh: Refresh = None) -> str:
        return views.work_orders(list(_orders.values()), _history, _notes, connection_id or None,
                                 _refresh(refresh))

    @app.post("/v4/work-orders/{work_order_id}/notes", status_code=201, summary="Add a note to one work order")
    def add_work_order_note(work_order_id: str, body: NotePayload, request: Request) -> dict:
        """Add a note to one work order."""
        claims = bearer.authorise(request, scope="workorder:create")
        _order(work_order_id)
        notes = _notes.setdefault(work_order_id, [])
        note = {
            "note_id": f"{work_order_id}-n{len(notes) + 1}",
            "created_at": seed.now(),
            "author": body.author or bearer.actor(claims)["subject"] or "unknown",
            "body": body.body,
        }
        notes.append(note)
        _record(work_order_id, "note_added")
        return note

    @app.post("/v4/work-orders/{work_order_id}/attachments", status_code=201, summary="Register an attachment against one work order")
    def add_work_order_attachment(
        work_order_id: str, body: AttachmentPayload, request: Request
    ) -> dict:
        """Register an attachment against one work order."""
        bearer.authorise(request, scope="workorder:create")
        _order(work_order_id)
        items = _attachments.setdefault(work_order_id, [])
        item = {
            "attachment_id": f"{work_order_id}-a{len(items) + 1}",
            "created_at": seed.now(),
            "filename": body.filename,
            "media_type": body.media_type,
            "description": body.description,
        }
        items.append(item)
        _record(work_order_id, "attachment_added", body.filename)
        return item
