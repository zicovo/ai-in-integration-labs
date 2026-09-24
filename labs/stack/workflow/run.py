#!/usr/bin/env python3
"""Start one meter check run and follow it from the engine's side.

    labs/stack/run-workflow.sh --connection 4471 [--pause 20] [--approval-timeout 15]
    labs/stack/run-workflow.sh --follow <workflow-id>       pick a run up again
    labs/stack/run-workflow.sh --connection 4471 --detach   start it and print the id
    labs/stack/run-workflow.sh --follow <id> --until created   return when the write is in its
                                                               pause window (verify.sh uses it)

Everything printed here is read from the engine, not from the worker: the run's memo says which
step it is on, the pending activity's heartbeat says what the write is doing, the history says
what completed. So this keeps narrating after the worker is killed, which is the moment the lab
is about, and it says when no worker is left to pick the run up.

The request opens the trace. Its id is passed to the workflow so the note on the work order can
carry it, and the engine's OpenTelemetry interceptor carries the context in the workflow's
headers so every activity, on whichever worker, joins the same trace.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from temporalio.api.enums.v1 import TaskQueueType  # noqa: E402
from temporalio.api.taskqueue.v1 import TaskQueue  # noqa: E402
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest  # noqa: E402
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowFailureError  # noqa: E402
from temporalio.contrib.opentelemetry import TracingInterceptor  # noqa: E402

import aquaflux  # noqa: E402
import telemetry  # noqa: E402

PID_FILE = HERE.parent / ".worker" / "pid"
UI = os.environ.get("AQUAFLUX_WORKFLOW_UI", "https://workflow.aquaflux.internal:8233")
TTY = sys.stdout.isatty()


def say(text: str) -> None:
    print(f"  {text}", flush=True)


def worker_process_alive() -> bool | None:
    """True or False from the pid file start-worker.sh keeps; None when there is no file."""
    try:
        pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


async def pollers(client: Client) -> int:
    """Workers polling the queue in the last minute, from the engine's own poller list."""
    seen = 0
    for kind in (TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY,):
        reply = await client.workflow_service.describe_task_queue(DescribeTaskQueueRequest(
            namespace=client.namespace, task_queue=TaskQueue(name=aquaflux.TASK_QUEUE),
            task_queue_type=kind))
        for poller in reply.pollers:
            if time.time() - poller.last_access_time.ToSeconds() < 70:
                seen += 1
    return seen


async def heartbeat(client: Client, pending) -> dict:
    if not pending.heartbeat_details.payloads:
        return {}
    values = await client.data_converter.decode(list(pending.heartbeat_details.payloads))
    return values[0] if values and isinstance(values[0], dict) else {}


async def scheduled_counts(handle) -> dict[str, int]:
    """How many times the engine scheduled each activity, from the history. An activity that
    completed before a crash appears once whatever happened afterwards; that is the replay."""
    counts: dict[str, int] = {}
    async for event in handle.fetch_history_events():
        if event.HasField("activity_task_scheduled_event_attributes"):
            name = event.activity_task_scheduled_event_attributes.activity_type.name
            counts[name] = counts.get(name, 0) + 1
    return counts


async def follow(client: Client, handle, until: str | None, as_json: bool) -> dict:
    printed: set[str] = set()
    last_phase = None
    last_hb: tuple = ()
    worker_warned = False
    countdown_line = False

    def once(key: str, text: str) -> None:
        if key not in printed:
            printed.add(key)
            nonlocal countdown_line
            if as_json:
                return  # a script is reading the outcome; the narration would break its JSON
            if countdown_line and TTY:
                print()
                countdown_line = False
            say(text)

    while True:
        desc = await handle.describe()
        memo = await desc.memo()
        phase = memo.get("phase")
        detail = memo.get("detail") or {}
        status = desc.status

        if phase != last_phase and phase:
            last_phase = phase
            if phase == "reading":
                once("reading", f"reading the meter data for connection {detail.get('connection_id')}")
            elif phase == "proposing":
                once("proposing", f"asking the model through the gateway, {detail.get('readings')} readings in hand")
            elif phase == "awaiting_approval":
                p = detail.get("proposal") or {}
                once("proposal", f"the model proposed {p.get('action')}, reason {p.get('reason')} "
                                 f"(answered by {detail.get('model')}). Validated.")
                once("waiting", "waiting for Sam. In another terminal:  labs/stack/approve.sh --as sam")
            elif phase == "approved":
                once("approved", f"approved by {detail.get('approver')} as {detail.get('approver_role')} "
                                 f"({detail.get('approval_id')})")
            elif phase == "creating":
                pass
            elif phase == "done":
                pass
            if until and phase == until:
                return {"workflow_id": handle.id, "phase": phase}

        pending = list(desc.raw_description.pending_activities)
        for act in pending:
            name = act.activity_type.name
            if name != "create_work_order":
                continue
            hb = await heartbeat(client, act)
            attempt = act.attempt
            # A new attempt inherits the last heartbeat of the one before it (that is how a
            # retry can resume from where its predecessor got to), so details from an earlier
            # attempt say what stopped, not what is happening.
            if hb and hb.get("attempt", attempt) < attempt:
                failure = act.last_failure.message.strip() if act.HasField("last_failure") else "no heartbeat"
                if hb.get("phase") == "created":
                    once(f"retry-{attempt}",
                         f"attempt {hb.get('attempt')} stopped heartbeating after creating work order "
                         f"{hb.get('work_order_id') or '(unknown)'} and never confirmed: {failure}. "
                         f"The engine scheduled attempt {attempt}; it runs when a worker polls.")
                else:
                    # The attempt never got as far as a write: the call itself failed. Say what
                    # the worker reported rather than describe a confirmation that was never due.
                    once(f"retry-{attempt}",
                         f"attempt {hb.get('attempt')} failed before anything was written: {failure}. "
                         f"The engine scheduled attempt {attempt}; it runs when a worker polls.")
                hb = {}
            if hb.get("phase") == "calling":
                once(f"calling-{attempt}", f"attempt {attempt}: creating the work order with key {hb.get('request_id')}")
            elif hb.get("phase") == "created":
                status_word = ("created (201)" if hb.get("http_status") == 201
                               else "answered 409, the original for this key")
                once(f"calling-{attempt}", f"attempt {attempt}: creating the work order with key {hb.get('request_id')}")
                once(f"created-{attempt}",
                     f"attempt {attempt}: work order {hb.get('work_order_id')} {status_word}. "
                     f"Confirming to the engine in {hb.get('confirm_in')} s.")
                if attempt == 1:
                    once("kill-hint", "to kill the worker inside this window:  labs/stack/kill-worker.sh")
                if until == "created":
                    return {"workflow_id": handle.id, "phase": "created", "attempt": attempt,
                            "work_order_id": hb.get("work_order_id")}
                if TTY and not as_json:
                    print(f"\r      {hb.get('confirm_in'):>3} s left  ", end="", flush=True)
                    countdown_line = True

        alive = worker_process_alive()
        if status == WorkflowExecutionStatus.RUNNING and alive is False and not worker_warned:
            worker_warned = True
            once("worker-gone", "the worker process is gone. The engine holds the run; nothing is lost "
                                "and nothing moves until a worker returns:  labs/stack/start-worker.sh")
        if alive and worker_warned:
            worker_warned = False
            printed.discard("worker-gone")
            once("worker-back", "a worker is back and polling")

        if status != WorkflowExecutionStatus.RUNNING:
            break
        await asyncio.sleep(1)

    if countdown_line and TTY:
        print()

    if status == WorkflowExecutionStatus.COMPLETED:
        result = await handle.result()
        counts = await scheduled_counts(handle)
        orders = aquaflux.work_orders(result["connection_id"])
        result["work_orders_after"] = len(orders)
        result["keys_sent"] = sorted({o["idempotency_key"] for o in orders})
        model_calls = aquaflux.model_calls_for(handle.id)
        summary = {"workflow_id": handle.id, "run_id": desc.run_id, "trace_id": result.get("trace_id"),
                   "result": result, "scheduled": counts, "model_gateway_calls": model_calls,
                   "work_orders": orders}
        if as_json:
            print(json.dumps(summary, indent=2))
            return summary
        print()
        say(f"run completed. Work order {result['work_order_id']}, "
            f"{'created' if result['created'] else 'already existed, 409'} on attempt {result['attempts']}, "
            f"key {result['request_id']}.")
        say(f"connection {result['connection_id']} now has {len(orders)} meter check work order(s): "
            + ", ".join(o["work_order_id"] for o in orders))
        say(f"the engine asked the model {counts.get('propose_action', 0)} time(s) and the write took "
            f"{result['attempts']} attempt(s); the model gateway logged {model_calls} call(s) for this run.")
        print()
        say("Prove it, from the systems and not from the code:")
        say(f"  curl -s 'https://wom.aquaflux.internal/v4/work-orders?connection_id={result['connection_id']}' | python3 -m json.tool")
        say(f"  aqx log --last 5 --tool {aquaflux.TOOL}")
        say(f"  curl -s {aquaflux.MODELS}/spend/logs -H \"Authorization: Bearer $LAB_GATEWAY_KEY\" | jq '[.[] | select(.end_user == \"{handle.id}\")] | length'")
        say(f"  {UI}/namespaces/default/workflows/{handle.id}/{desc.run_id}/history")
        if result.get("trace_id"):
            say(f"  aqx trace {result['trace_id']}")
        return summary

    failure = ""
    try:
        await handle.result()
    except WorkflowFailureError as error:
        # The engine wraps the reason: "Activity task failed" is the outer layer, and the message
        # the activity raised is at the bottom of the cause chain. Print the chain, outermost
        # first, so the reason a learner needs is on the line and not only in the web interface.
        parts: list[str] = []
        cause: BaseException | None = error.cause or error
        while cause is not None and str(cause) not in parts:
            parts.append(str(cause))
            cause = getattr(cause, "cause", None)
        # Innermost first, and drop a layer that only repeats the one inside it.
        kept: list[str] = []
        for part in reversed([p for p in parts if p]):
            if not any(part in k or k in part for k in kept):
                kept.append(part)
        failure = "; ".join(kept)
    summary = {"workflow_id": handle.id, "status": status.name, "failure": failure}
    if as_json:
        print(json.dumps(summary, indent=2))
    else:
        print()
        say(f"run {status.name.lower()}: {failure}")
        say(f"history: {UI}/namespaces/default/workflows/{handle.id}")
    return summary


async def main() -> int:
    parser = argparse.ArgumentParser(description="Start and follow one meter check run.")
    parser.add_argument("--connection", help="the connection to check, for example 4471")
    parser.add_argument("--pause", type=int, default=int(os.environ.get("AQUAFLUX_CONFIRM_PAUSE", "20")),
                        help="seconds between the write and its confirmation (default 20)")
    parser.add_argument("--approval-timeout", type=int, default=15, help="minutes to wait for Sam")
    parser.add_argument("--follow", metavar="WORKFLOW_ID", help="follow an existing run instead")
    parser.add_argument("--detach", action="store_true", help="start the run and print its id")
    parser.add_argument("--until", metavar="PHASE", help="return once the run reaches this phase")
    parser.add_argument("--json", action="store_true", help="print the outcome as JSON")
    args = parser.parse_args()
    if not args.follow and not args.connection:
        parser.error("say which connection, with --connection <id>, or --follow <workflow-id>")

    tracer = telemetry.setup("service-desk")
    client = await Client.connect(aquaflux.WORKFLOW_ENGINE, interceptors=[TracingInterceptor()])

    if args.follow:
        handle = client.get_workflow_handle(args.follow)
        if not args.json and not args.until:
            say(f"following {args.follow}")
    else:
        workflow_id = f"meter-check-{args.connection}-{time.strftime('%Y%m%d-%H%M%S')}"
        with tracer.start_as_current_span(f"request meter_check {args.connection}") as span:
            trace_id = telemetry.trace_id()
            span.set_attribute("aquaflux.connection_id", args.connection)
            span.set_attribute("aquaflux.workflow.id", workflow_id)
            handle = await client.start_workflow(
                "MeterCheck",
                {"connection_id": args.connection, "trace_id": trace_id,
                 "confirm_pause_seconds": args.pause,
                 "approval_timeout_minutes": args.approval_timeout},
                id=workflow_id, task_queue=aquaflux.TASK_QUEUE,
            )
        if args.detach:
            print(json.dumps({"workflow_id": workflow_id, "run_id": handle.result_run_id,
                              "trace_id": trace_id}) if args.json else workflow_id)
            return 0
        if not args.json and not args.until:
            print()
            say(f"started {workflow_id} on the {aquaflux.TASK_QUEUE} queue. Trace {trace_id}.")
            say(f"history: {UI}/namespaces/default/workflows/{workflow_id}")
            if worker_process_alive() is False and await pollers(client) == 0:
                say("no worker is polling. Start one:  labs/stack/start-worker.sh")
            print()

    outcome = await follow(client, handle, args.until, args.json)
    if args.until and not args.json:
        print(json.dumps(outcome))
    return 0 if outcome.get("status", "COMPLETED") == "COMPLETED" or args.until else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
