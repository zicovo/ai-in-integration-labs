#!/usr/bin/env bash
# Start one meter check run and follow it from the engine's side.
#
#   labs/stack/run-workflow.sh --connection 4471
#   labs/stack/run-workflow.sh --follow <workflow-id>
#
# e-03 calls this by name. What it prints is read from the engine, not from the worker, so it
# keeps narrating after the worker is killed. labs/stack/workflow/run.py is the script; read it.

set -euo pipefail
STACK_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
exec python3 "$STACK_DIR/workflow/run.py" "$@"
