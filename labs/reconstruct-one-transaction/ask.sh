#!/usr/bin/env bash
# reconstruct-one-transaction's handout has you work from labs/reconstruct-one-transaction/ and run the reading assistant from there. The agent
# lives with the rest of the stack, in labs/stack/, which labs/README.md lists as the only place a
# handout may call scripts from. Found relative to this file first, and through aqx on the path if
# this directory was copied.
here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
if [ -x "$here/../stack/ask.sh" ]; then exec "$here/../stack/ask.sh" "$@"; fi
exec "$(dirname "$(readlink -f "$(command -v aqx)")")/../ask.sh" "$@"
