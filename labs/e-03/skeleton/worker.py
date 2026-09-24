"""The worker: the process that runs the workflow's code and its activities.

The engine holds the state; this process holds nothing it cannot lose. That is the property the
lab kills it to demonstrate. `labs/stack/start-worker.sh` starts it from a tier directory and
`labs/stack/kill-worker.sh` stops it without a graceful drain.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import pathlib
import sys
from datetime import timedelta

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "stack" / "workflow"))

from temporalio.client import Client  # noqa: E402
from temporalio.contrib.opentelemetry import TracingInterceptor  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

import activities  # noqa: E402
import aquaflux  # noqa: E402
import telemetry  # noqa: E402
from workflow import MeterCheck  # noqa: E402


async def main() -> None:
    telemetry.setup("meter-check-worker")
    # The interceptor carries the trace context in the workflow's headers, so an activity that
    # runs on a worker started after the crash still writes onto the trace the request opened.
    client = await Client.connect(aquaflux.WORKFLOW_ENGINE, interceptors=[TracingInterceptor()])
    worker = Worker(
        client,
        task_queue=aquaflux.TASK_QUEUE,
        workflows=[MeterCheck],
        activities=[activities.read_meter_data, activities.propose_action,
                    activities.find_approval, activities.create_work_order,
                    activities.cancel_work_order],
        # Activities here are ordinary blocking functions, so they run on a thread pool.
        activity_executor=concurrent.futures.ThreadPoolExecutor(max_workers=8),
        # The SDK batches heartbeats and sends the latest one at most every so often; its
        # default is most of the heartbeat timeout, which leaves the engine one late packet
        # away from timing out a healthy attempt (measured: an eight second timeout fired at
        # nine). Two seconds keeps the run's narration current and the timeout honest.
        max_heartbeat_throttle_interval=timedelta(seconds=2),
        default_heartbeat_throttle_interval=timedelta(seconds=2),
    )
    print(f"worker polling {aquaflux.TASK_QUEUE} at {aquaflux.WORKFLOW_ENGINE}, "
          f"running {HERE.parent.name}/{HERE.name}"
          + (", exporting spans" if telemetry.exporting() else ", no collector, spans dropped"),
          flush=True)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
