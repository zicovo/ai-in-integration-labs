#!/usr/bin/env bash
# Kill the workflow worker. No graceful drain, on purpose.
#
#   labs/stack/kill-worker.sh
#
# e-03 calls this by name, inside the pause window the run prints. SIGKILL and nothing else: a
# graceful stop lets the worker finish the activity it is in, the engine records the write as
# confirmed, and the lesson never happens. What this stands in for is a process that dies, a
# node that is drained by force, a deploy that does not wait.

set -euo pipefail

STACK_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
RUN_DIR="$STACK_DIR/.worker"

ok()  { printf '  \033[32mok\033[0m    %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m  %s\n' "$*" >&2; }

pid="$(cat "$RUN_DIR/pid" 2>/dev/null || true)"
if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
  bad "no worker is running (start one with labs/stack/start-worker.sh)"
  exit 1
fi
kill -9 "$pid"
for _ in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
ok "worker $pid killed with SIGKILL, no drain. The engine holds the run; bring a worker back with labs/stack/start-worker.sh"
