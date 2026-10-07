#!/usr/bin/env bash
# Record an approval, as a named person, at the approval service.
#
#   labs/stack/approve.sh --approver sam --connection 4471 [--action disconnection] [--note "..."]
#   labs/stack/approve.sh --as sam                        survive-the-crash's spelling: approve the meter check
#                                                         the workflow is waiting for, on 4471
#   labs/stack/approve.sh --revoke apr-xxxxxxxx           withdraw one (the completion tier's
#                                                         "Sam then refuses")
#   labs/stack/approve.sh --list                          the approvals currently active
#   labs/stack/approve.sh --clear                         forget them all (instructor)
#
# `--as` is the survive-the-crash handout's spelling, and it carries that lab's defaults: the action is
# `meter_check` and the connection is 4471 unless --action or --connection say otherwise, because
# the handout prints `approve.sh --as sam` and nothing more. `--approver` keeps block-the-call's default,
# `disconnection`, and insists on a connection.
#
# block-the-call and survive-the-crash call this by name. What it does, in order: sign the approver in at the identity
# provider with their password, which is the step-up the study text asks for (an approval is a
# decision taken now, not a session opened this morning); ask for a token addressed to the
# approval service and nothing else; and post the approval with the action and the connection it
# is for. The service records who approved, which roles the identity provider says they hold,
# and a hash of exactly those arguments.
#
# It does not check that the approver may approve. Els can approve her own case here, and the
# record will say so. Whether that counts is the policy's decision, which is the point of block-the-call's
# step five; a fixture that refused it would make that step impossible.

set -euo pipefail

IDP="${AQUAFLUX_IDP:-https://idp.aquaflux.internal/realms/aquaflux}"
APPROVALS="${AQUAFLUX_APPROVALS:-https://approvals.aquaflux.internal}"

ok()  { printf '  \033[32mok\033[0m    %s\n' "$*"; }
bad() { printf '  \033[31mFAIL\033[0m  %s\n' "$*" >&2; }

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

APPROVER=""; CONNECTION=""; ACTION=""; NOTE=""; PASSWORD=""; SPELLING="approver"
while [ $# -gt 0 ]; do
  case "$1" in
    --approver) APPROVER="${2:-}"; shift 2 ;;
    --as) APPROVER="${2:-}"; SPELLING="as"; shift 2 ;;
    --connection) CONNECTION="${2:-}"; shift 2 ;;
    --action) ACTION="${2:-}"; shift 2 ;;
    --note) NOTE="${2:-}"; shift 2 ;;
    --password) PASSWORD="${2:-}"; shift 2 ;;
    --list) curl -fsS "$APPROVALS/approvals?active=true" | jq .; exit 0 ;;
    --revoke) curl -fsS -X DELETE "$APPROVALS/approvals/${2:-}" | jq -c .; exit 0 ;;
    --clear) curl -fsS -X DELETE "$APPROVALS/approvals" | jq -c .; exit 0 ;;
    -h|--help) usage ;;
    *) echo "approve.sh: unknown option $1" >&2; usage ;;
  esac
done
[ -n "$APPROVER" ] || { echo "approve.sh: say who is approving, with --approver <username>" >&2; usage; }
if [ "$SPELLING" = "as" ]; then
  : "${ACTION:=meter_check}"
  : "${CONNECTION:=4471}"
else
  : "${ACTION:=disconnection}"
fi
[ -n "$CONNECTION" ] || { echo "approve.sh: say which connection, with --connection <id>" >&2; usage; }

# The lab passwords are the usernames, apart from the two the stack sets in the environment.
if [ -z "$PASSWORD" ]; then
  case "$APPROVER" in
    sam) PASSWORD="${LAB_SAM_PASSWORD:-sam}" ;;
    els) PASSWORD="${LAB_ELS_PASSWORD:-els}" ;;
    nadia) PASSWORD="${LAB_NADIA_PASSWORD:-nadia}" ;;
    *) PASSWORD="$APPROVER" ;;
  esac
fi

# Step up: a fresh sign-in, for a token cut for the approval service. `approval:decide` is the
# scope that carries that audience; the token has no other and reaches no other door.
response="$(curl -sS -X POST "$IDP/protocol/openid-connect/token" \
  -d grant_type=password -d client_id=service-desk \
  -d "username=$APPROVER" -d "password=$PASSWORD" -d "scope=openid approval:decide")"
token="$(echo "$response" | jq -r '.access_token // empty')"
if [ -z "$token" ]; then
  bad "$APPROVER could not sign in: $(echo "$response" | jq -r '.error_description // .error // .')"
  exit 1
fi
ok "$APPROVER signed in and holds a token addressed to the approval service"

body="$(jq -nc --arg a "$ACTION" --arg c "$CONNECTION" --arg n "$NOTE" \
  '{action: $a, connection_id: $c} + (if $n == "" then {} else {note: $n} end)')"
record="$(curl -sS -X POST "$APPROVALS/approvals" -H "Authorization: Bearer $token" \
  -H 'content-type: application/json' -d "$body")"
if ! echo "$record" | jq -e '.approval_id' >/dev/null 2>&1; then
  bad "the approval service refused: $(echo "$record" | jq -r '.detail // .')"
  exit 1
fi

ok "recorded $(echo "$record" | jq -r .approval_id): $ACTION of connection $CONNECTION, approved by $(echo "$record" | jq -r '.approver') as $(echo "$record" | jq -r '.approver_role')"
echo "$record" | jq '{approval_id, action, connection_id, approver, approver_role, approver_roles, arguments_sha256, expires_at}'
