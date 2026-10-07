#!/usr/bin/env bash
# block-the-call's handout says ./approve.sh. The script lives with the rest of the stack's scripts, in
# labs/stack/, which labs/README.md lists as the only place a handout may call scripts from.
# Found relative to this file first, and through aqx on the path if this directory was copied.
here="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
if [ -x "$here/../stack/approve.sh" ]; then exec "$here/../stack/approve.sh" "$@"; fi
exec "$(dirname "$(readlink -f "$(command -v aqx)")")/../approve.sh" "$@"
