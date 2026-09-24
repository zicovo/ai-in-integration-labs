#!/usr/bin/env bash
# Start one MCP server and put it behind the tool gateway.
#
#   labs/stack/register-tool-server.sh <directory> <port> [--policy <id>]
#
# c-02 calls this by name and never sees the registration call underneath, which is the point:
# the gateway is a release candidate, its admin API moves between versions, and a handout that
# spelled the call out would be wrong by the next delivery. What the handout promises is the
# behaviour, and this file keeps that promise however the gateway changes.
#
# What it does, in order: stop every server it started earlier and empty the gateway's registry,
# start `server.py` from the directory, wait for it to answer, register it under the directory's
# name, activate the policy if one was named, and print the catalogue.
#
# It **replaces** the catalogue rather than adding to it, and that is deliberate. c-02 runs the
# generated catalogue and then the curated one, and the two runs are supposed to differ only in
# what is published. Adding the second to the first leaves twenty-five tools behind the gateway
# and the comparison the whole lab rests on quietly stops being a comparison. Pass `--add` if
# you really do want to federate two servers at once, which is what a gateway is for and what
# no tier of c-02 asks for.
#
# The server runs as a process in this dev container, not as a container of its own. That is
# deliberate. The learner edits `server.py` and runs this again, and a rebuild between those two
# would make the loop too slow to iterate in.

set -euo pipefail

STACK_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
REPO="$(cd "$STACK_DIR/../.." && pwd)"
GATEWAY="${AQUAFLUX_TOOLS:-https://tools.aquaflux.internal:4444}"
RUN_DIR="${TMPDIR:-/tmp}/aquaflux-tool-servers"

ok()  { printf '  \033[32mok\033[0m    %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m  %s\n' "$*" >&2; }

usage() {
  cat >&2 <<'USAGE'
usage: labs/stack/register-tool-server.sh <directory> <port> [--policy <id>]

  directory   a directory holding server.py, for example labs/c-02/curated
  port        the port to serve it on. c-02 uses 8850 for curated and 8851 for generated
  --policy    the gateway policy to activate, for example wo-tools-1

  --add       keep whatever is already registered instead of replacing it
  labs/stack/register-tool-server.sh --stop           stop every server this script started
USAGE
  exit 2
}

stop_all() {
  mkdir -p "$RUN_DIR"
  local stopped=0
  for pidfile in "$RUN_DIR"/*.pid; do
    [ -e "$pidfile" ] || continue
    local pid; pid="$(cat "$pidfile")"
    if kill "$pid" 2>/dev/null; then stopped=$((stopped + 1)); fi
    rm -f "$pidfile"
  done
  # Deregister everything the gateway knows about, so a stale catalogue does not outlive the
  # process behind it. A tool that is listed and unreachable is the most confusing state here.
  if curl -fsS --max-time 5 "$GATEWAY/servers" >/dev/null 2>&1; then
    for name in $(curl -fsS "$GATEWAY/servers" | python3 -c \
      'import json,sys;print(" ".join(s["name"] for s in json.load(sys.stdin)))'); do
      curl -fsS -X DELETE "$GATEWAY/servers/$name" >/dev/null || true
    done
  fi
  ok "stopped $stopped server(s) and emptied the gateway registry"
}

[ $# -ge 1 ] || usage
if [ "$1" = "--stop" ]; then stop_all; exit 0; fi
[ $# -ge 2 ] || usage

DIR="$1"; PORT="$2"; shift 2
POLICY=""
REPLACE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --policy) POLICY="${2:-}"; shift 2 ;;
    --add) REPLACE=0; shift ;;
    *) usage ;;
  esac
done

# The handout says `labs/c-02/generated`; a learner standing in that directory says `.`. Both
# work, and the name the gateway registers is the directory's own name either way.
DIR="$(cd "$REPO" 2>/dev/null && cd "$DIR" 2>/dev/null && pwd || (cd "$DIR" && pwd))"
NAME="$(basename "$DIR")"
[ -f "$DIR/server.py" ] || { bad "no server.py in $DIR"; exit 1; }

mkdir -p "$RUN_DIR"
PIDFILE="$RUN_DIR/$PORT.pid"
LOGFILE="$RUN_DIR/$PORT.log"

if [ "$REPLACE" = "1" ]; then
  stop_all >/dev/null
else
  if [ -f "$PIDFILE" ]; then
    kill "$(cat "$PIDFILE")" 2>/dev/null || true
    rm -f "$PIDFILE"
    sleep 1
  fi
fi

# The old server on this port was sent a plain termination above and takes a moment to let go
# of the port. Starting the new one before it does fails the bind, and the failure reads like a
# gateway problem. Wait for the port first.
for _ in $(seq 1 40); do
  if ! curl -s -o /dev/null --max-time 1 "http://localhost:$PORT/mcp"; then break; fi
  sleep 0.25
done

# The server imports `wom` from beside it, so it runs with its own directory as the working
# directory rather than the repository root.
( cd "$DIR" && exec python3 server.py ) >"$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"

for _ in $(seq 1 40); do
  if curl -s -o /dev/null --max-time 2 "http://localhost:$PORT/mcp"; then break; fi
  sleep 0.5
done

if ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  bad "$NAME did not start. Its output:"
  sed 's/^/        /' "$LOGFILE" >&2
  exit 1
fi
ok "$NAME is serving on port $PORT (log: $LOGFILE)"

response="$(curl -sS -X POST "$GATEWAY/servers" -H 'content-type: application/json' \
  -d "{\"name\":\"$NAME\",\"url\":\"http://workspace.aquaflux.internal:$PORT/mcp\"}")"

if ! echo "$response" | python3 -c 'import json,sys;sys.exit(0 if "tools" in json.load(sys.stdin) else 1)' 2>/dev/null; then
  bad "the gateway refused the registration:"
  echo "$response" | sed 's/^/        /' >&2
  exit 1
fi

count="$(echo "$response" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["tools"]))')"
ok "registered with the tool gateway: $count tool(s)"

if [ -n "$POLICY" ]; then
  applied="$(curl -sS -X PUT "$GATEWAY/policy/$POLICY")"
  if echo "$applied" | grep -q '"active"'; then
    ok "policy $POLICY is active ($(echo "$applied" | python3 -c 'import json,sys;print("version "+json.load(sys.stdin)["version"])'))"
  else
    bad "the gateway would not activate $POLICY:"
    echo "$applied" | sed 's/^/        /' >&2
    exit 1
  fi

  orphans="$(curl -fsS "$GATEWAY/policy" | python3 -c \
    'import json,sys;print(", ".join(json.load(sys.stdin)["rules_without_a_tool"]))')"
  if [ -n "$orphans" ]; then
    printf '  \033[33m..\033[0m    %s\n' "$POLICY has a rule for $orphans, which nothing publishes"
  fi
fi

echo
echo "  The catalogue behind $GATEWAY now holds:"
curl -fsS "$GATEWAY/tools" | python3 -c '
import json, sys
for tool in json.load(sys.stdin):
    name = tool["name"]
    first = (tool["description"] or "").strip().splitlines()
    first = first[0] if first else ""
    print("    " + name.ljust(38) + " " + first[:60])
'
