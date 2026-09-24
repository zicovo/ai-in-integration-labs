"""The completion tier's skeleton: the activities declared, the tool call and the approval wait
wired, and the parts the tier asks you to write marked with a TODO.

The engine's own documentation is the reason this file exists: an activity with a retry policy
is observed as completed exactly once, and may be executed more than once. So every function
below has to be safe to run twice. Read them in that light, and ask of each: idempotent,
compensable, or neither?

    read_meter_data     reads. Idempotent by nature.
    propose_action      asks the model. Not idempotent (the model may answer differently), which
                        is why the engine records its result and never asks again on a resume.
    find_approval       reads the approval service. Idempotent.
    create_work_order   writes. Idempotent only if the key it sends is the same on every attempt,
                        and that is what `request_id_for` decides.

The plumbing (tokens, the gateway calls, the model call) is in labs/stack/workflow/aquaflux.py,
so that this file is the workflow's own logic and nothing else.
"""

from __future__ import annotations

import pathlib
import sys
import time
from dataclasses import dataclass, field
from uuid import UUID, uuid5

from temporalio import activity
from temporalio.exceptions import ApplicationError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "stack" / "workflow"))
import aquaflux  # noqa: E402
import telemetry  # noqa: E402

# The namespace every Aquaflux request id is derived in. Fixed, so that the same inputs give the
# same key on any machine.
AQUAFLUX_NS = UUID("3f8e1a2c-6d4b-4e0f-9a7c-2b5d8c1e4f60")


def request_id_for(run_id: str, step_id: str) -> str:
    """The idempotency key for one mutating step of one run.

    Completion tier, step one: write this so that the key survives a resume, and write the test
    beside it (test_request_id.py) before the function. Every input has to be a value the engine
    reproduces on a retry. The clock is not one. Neither is a fresh uuid4, the model's output,
    or anything read from the outside world after the crash.
    """
    raise NotImplementedError("request_id_for: derive the key from values the engine reproduces")


# ------------------------------------------------------------------ the shapes


@dataclass
class MeterCheckRequest:
    connection_id: str
    trace_id: str | None = None
    confirm_pause_seconds: int = 20
    approval_timeout_minutes: int = 15


@dataclass
class ProposeInput:
    connection_id: str
    readings: list[dict]
    trace_id: str | None = None


@dataclass
class FindApprovalInput:
    connection_id: str
    action: str
    not_before: str


@dataclass
class CreateInput:
    connection_id: str
    reason: str
    step_id: str
    approval_id: str
    confirm_pause_seconds: int
    trace_id: str | None = None


@dataclass
class CancelInput:
    work_order_id: str
    reason: str
    approval_id: str
    trace_id: str | None = None


@dataclass
class MeterCheckResult:
    connection_id: str
    work_order_id: str
    request_id: str
    created: bool
    http_status: int
    attempts: int
    approval_id: str
    approver: str
    model_answered: str | None
    trace_id: str | None
    work_orders_after: int = 0
    keys_sent: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ the activities


@activity.defn
def read_meter_data(connection_id: str) -> list[dict]:
    activity.heartbeat({"phase": "reading"})
    return aquaflux.readings(connection_id)


@activity.defn
def propose_action(inp: ProposeInput) -> dict:
    activity.heartbeat({"phase": "proposing"})
    return aquaflux.propose(inp.connection_id, inp.readings, activity.info().workflow_id,
                            inp.trace_id or telemetry.trace_id())


@activity.defn
def find_approval(inp: FindApprovalInput) -> dict | None:
    return aquaflux.approval_for(inp.connection_id, inp.action, not_before=inp.not_before)


@activity.defn
def cancel_work_order(inp: CancelInput) -> dict:
    """Completion tier, step three: the compensation.

    The work order was created and Sam then withdrew the approval, because after a retry the two
    arrived in the wrong order. Cancel it with a reason, against the same correlation as the
    creation. `aquaflux.cancel_work_order` is the call; the credential it needs is narrower than
    the one that created the order, and which scope to ask `aquaflux.token()` for is part of the
    step. Ask of this activity what you asked of the others: is it idempotent?
    """
    raise NotImplementedError("cancel_work_order: TODO, the compensation path")


@activity.defn
def create_work_order(inp: CreateInput) -> dict:
    """Create the work order through the tool gateway, then confirm to the engine.

    The pause between the write and the return is the lab's window: the handout has you kill the
    worker inside it. It stands in for everything that takes time between a side effect and its
    confirmation in a real system: a slow response, a network partition, a deploy. The engine
    sees a heartbeat every second while the pause runs; when the heartbeats stop, it times the
    attempt out and schedules the next one, and the next one runs this function again from the
    top, on whichever worker is polling by then.
    """
    info = activity.info()
    request_id = request_id_for(info.workflow_run_id, inp.step_id)
    activity.heartbeat({"phase": "calling", "attempt": info.attempt, "request_id": request_id})

    trace_id = telemetry.trace_id() or inp.trace_id
    note = (f"Reading assistant for Nadia. Approval {inp.approval_id}. "
            f"Run {info.workflow_id}. Trace {trace_id}.")[:300]
    try:
        outcome = aquaflux.create_meter_check(inp.connection_id, inp.reason, request_id, note,
                                              aquaflux.token())
    except aquaflux.GatewayRefused as refused:
        # A refusal by the gateway (no such tool, a token it will not accept, a policy deny) is
        # an answer, and the same answer on every attempt. Retrying it would spin until the
        # timeout; failing the run says what happened.
        raise ApplicationError(str(refused), non_retryable=True) from refused

    deadline = time.monotonic() + inp.confirm_pause_seconds
    while True:
        left = deadline - time.monotonic()
        activity.heartbeat({"phase": "created", "attempt": info.attempt, "request_id": request_id,
                            "work_order_id": outcome["work_order_id"],
                            "http_status": outcome["http_status"],
                            "confirm_in": max(0, round(left))})
        if left <= 0:
            break
        time.sleep(min(1.0, left))

    return {**outcome, "attempt": info.attempt, "run_id": info.workflow_run_id,
            "trace_id": trace_id}
