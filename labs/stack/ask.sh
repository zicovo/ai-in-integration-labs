#!/usr/bin/env bash
# Run the reading assistant against whatever the tool gateway currently publishes.
#
#   labs/stack/ask.sh "the customer on 4471 says their bill doubled, can someone check the meter"
#   labs/stack/ask.sh --dump-tools
#   labs/stack/ask.sh --token         the exchanged token, for one call made by hand
#
# c-02 calls this by name. The agent itself is labs/stack/agent/ask.py, which is short and worth
# reading; this wrapper exists so a handout can say one thing and so the agent's own
# configuration stays beside it rather than in a shell variable.

set -euo pipefail
STACK_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
exec python3 "$STACK_DIR/agent/ask.py" "$@"
