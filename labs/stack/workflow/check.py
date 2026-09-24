#!/usr/bin/env python3
"""What smoke.sh and verify.sh ask the workflow engine: its version, and who is polling.

    python3 labs/stack/workflow/check.py version     the server version the engine reports
    python3 labs/stack/workflow/check.py pollers     how many workers polled the task queue in
                                                     the last minute; exit 1 when none did
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from temporalio.api.enums.v1 import TaskQueueType  # noqa: E402
from temporalio.api.taskqueue.v1 import TaskQueue  # noqa: E402
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest, GetSystemInfoRequest  # noqa: E402
from temporalio.client import Client  # noqa: E402

import aquaflux  # noqa: E402


async def main() -> int:
    what = sys.argv[1] if len(sys.argv) > 1 else "version"
    client = await Client.connect(aquaflux.WORKFLOW_ENGINE)
    if what == "version":
        info = await client.workflow_service.get_system_info(GetSystemInfoRequest())
        print(info.server_version)
        return 0
    if what == "pollers":
        live = set()
        for kind in (TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY, TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW):
            reply = await client.workflow_service.describe_task_queue(DescribeTaskQueueRequest(
                namespace=client.namespace, task_queue=TaskQueue(name=aquaflux.TASK_QUEUE),
                task_queue_type=kind))
            for poller in reply.pollers:
                if time.time() - poller.last_access_time.ToSeconds() < 70:
                    live.add(poller.identity)
        print(len(live))
        return 0 if live else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
