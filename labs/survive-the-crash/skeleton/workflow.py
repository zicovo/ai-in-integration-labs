"""The completion tier's skeleton of the meter check workflow. Two TODOs mark what you write.

Read it top to bottom: it is the sequence the handout describes. Read the meter, ask the model,
validate what it proposed, wait for Sam, create the work order. The engine records the result of
every activity as it completes, so when a worker dies half way and a new one picks the run up,
the code below runs again from the top and every step that had completed is answered from the
history rather than executed. That is what "the model was not asked twice" rests on, and you can
watch it in the run's history in the web interface.

Everything in this file has to be deterministic: no clock, no randomness, no network. Those
belong in activities.py, which is where the engine can retry them. The one time is the engine's
own, `workflow.now()`, which replays to the same value.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    import activities
    from activities import (CreateInput, FindApprovalInput, MeterCheckRequest, MeterCheckResult,
                            ProposeInput)

ACTION = "meter_check"


@workflow.defn(name="MeterCheck")
class MeterCheck:

    @workflow.run
    async def run(self, request: MeterCheckRequest) -> MeterCheckResult:
        await self.phase("reading", connection_id=request.connection_id)
        rows = await workflow.execute_activity(
            activities.read_meter_data, request.connection_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=5),
        )

        await self.phase("proposing", readings=len(rows))
        proposed = await workflow.execute_activity(
            activities.propose_action, ProposeInput(request.connection_id, rows, request.trace_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        proposal = proposed["proposal"]

        # Validation is workflow code, not an activity: it reads a recorded result and decides.
        if proposal.get("action") != ACTION:
            raise ApplicationError(
                f"the model proposed {proposal.get('action')!r}, and this workflow only runs meter "
                f"checks: {proposal.get('explanation')}", non_retryable=True)
        validated_at = workflow.now().strftime("%Y-%m-%dT%H:%M:%SZ")

        await self.phase("awaiting_approval", proposal=proposal, model=proposed.get("model_answered"),
                         since=validated_at)
        # TODO, completion tier step two: this wait has no timeout. Decide what happens when
        # Sam does not answer, using `request.approval_timeout_minutes` and `workflow.now()`,
        # and be ready to defend it. A timeout that defaults to proceeding is a control that
        # does nothing at three in the morning.
        approval = None
        while approval is None:
            approval = await workflow.execute_activity(
                activities.find_approval,
                FindApprovalInput(request.connection_id, ACTION, validated_at),
                start_to_close_timeout=timedelta(seconds=15),
            )
            if approval is None:
                await asyncio.sleep(3)

        await self.phase("approved", approval_id=approval["approval_id"], approver=approval["approver"],
                         approver_role=approval.get("approver_role"))

        await self.phase("creating", approval_id=approval["approval_id"])
        created = await workflow.execute_activity(
            activities.create_work_order,
            CreateInput(request.connection_id, proposal["reason"], "create-work-order",
                        approval["approval_id"], request.confirm_pause_seconds, request.trace_id),
            start_to_close_timeout=timedelta(seconds=request.confirm_pause_seconds + 90),
            # The heartbeat is how the engine learns the worker is gone: eight seconds without
            # one and the attempt is failed and the next one scheduled.
            heartbeat_timeout=timedelta(seconds=8),
            retry_policy=RetryPolicy(initial_interval=timedelta(seconds=1), backoff_coefficient=1.0),
        )

        # TODO, completion tier step three: the case this workflow does not yet handle. The work
        # order exists, and Sam has withdrawn the approval in the meantime (`approve.sh --revoke`).
        # Check the approval once more here; if it is gone, run the compensation activity,
        # `activities.cancel_work_order`, with the same approval id and trace id the creation
        # carried, and fail the run with a reason that names the cancelled work order.

        result = MeterCheckResult(
            connection_id=request.connection_id,
            work_order_id=created["work_order_id"],
            request_id=created["request_id"],
            created=created["created"],
            http_status=created["http_status"],
            attempts=created["attempt"],
            approval_id=approval["approval_id"],
            approver=approval["approver"],
            model_answered=proposed.get("model_answered"),
            trace_id=created.get("trace_id") or request.trace_id,
        )
        await self.phase("done", work_order_id=result.work_order_id, attempts=result.attempts,
                         http_status=result.http_status)
        return result

    async def phase(self, name: str, **detail) -> None:
        """Where the run is, written on the run itself so `run-workflow.sh` can read it from the
        engine whether or not a worker is alive."""
        workflow.upsert_memo({"phase": name, "detail": detail})
