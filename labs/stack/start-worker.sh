#!/usr/bin/env bash
# Start the workflow worker from a tier directory, replacing the one that is running.
#
#   labs/stack/start-worker.sh [labs/e-03/broken]     the directory holding worker.py
#   labs/stack/start-worker.sh                        the directory it was last started from
#
# e-03 calls this by name. The worker is a process in this dev container, not a container of its
# own, for the same reason c-02's MCP servers are: the learner edits activities.py and restarts
# the worker, and an image rebuild in that loop would be setup in the middle of the task. It is
# the process `labs/stack/kill-worker.sh` kills. Its output goes to labs/stack/.worker/worker.log.

set -euo pipefail

STACK_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
REPO="$(cd "$STACK_DIR/../.." && pwd)"
RUN_DIR="$STACK_DIR/.worker"
mkdir -p "$RUN_DIR"

ok()  { printf '  \033[32mok\033[0m    %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m  %s\n' "$*" >&2; }

DIR="${1:-}"
if [ -z "$DIR" ]; then
  DIR="$(cat "$RUN_DIR/dir" 2>/dev/null || echo labs/e-03/broken)"
fi
DIR="$(cd "$REPO" 2>/dev/null && cd "$DIR" 2>/dev/null && pwd || (cd "$DIR" && pwd))"
[ -f "$DIR/worker.py" ] || { bad "no worker.py in $DIR"; exit 1; }
REL="${DIR#"$REPO"/}"

# Replace whatever is running. This stop is not the lab's kill: it is a plain termination, used
# when nothing is in flight, and kill-worker.sh is the one that must not drain.
if [ -f "$RUN_DIR/pid" ]; then
  old="$(cat "$RUN_DIR/pid")"
  if kill -0 "$old" 2>/dev/null; then
    kill "$old" 2>/dev/null || true
    for _ in $(seq 1 20); do kill -0 "$old" 2>/dev/null || break; sleep 0.25; done
    kill -9 "$old" 2>/dev/null || true
  fi
  rm -f "$RUN_DIR/pid"
fi

( cd "$DIR" && exec python3 worker.py ) >>"$RUN_DIR/worker.log" 2>&1 &
echo $! > "$RUN_DIR/pid"
echo "$REL" > "$RUN_DIR/dir"

# Wait for the engine to see it polling, so the caller can start a run straight away.
for _ in $(seq 1 40); do
  if ! kill -0 "$(cat "$RUN_DIR/pid")" 2>/dev/null; then
    bad "the worker exited. Its output:"; tail -20 "$RUN_DIR/worker.log" | sed 's/^/        /' >&2; exit 1
  fi
  if python3 "$STACK_DIR/workflow/check.py" pollers >/dev/null 2>&1; then
    ok "worker $(cat "$RUN_DIR/pid") is polling aquaflux-meter-check, running $REL (log: labs/stack/.worker/worker.log)"
    exit 0
  fi
  sleep 0.5
done
bad "the worker started but the engine does not see it polling. Its output:"
tail -20 "$RUN_DIR/worker.log" | sed 's/^/        /' >&2
exit 1
