#!/usr/bin/env bash
# Replay the calls d-03's policy must refuse, as the collections agent acting for a person.
#
#   labs/stack/attack.sh --agent collections-agent --on-behalf-of els --connection 4471
#
# What it does, in order. If there is a policy/ directory where you are standing, it loads it
# into the policy engine first and prints the version, so the rule you just edited is the rule
# being enforced; there is no hidden step between saving the file and running the attack. Then it
# signs the person in, exchanges their token for one the agent holds while acting for them, and
# makes the obvious call: `create_disconnection_work_order` on the connection. If that is refused,
# it makes a second call to the generic `create_work_order` with `work_order_type` set to
# `disconnection`, which is the call the tests you were given do not contain.
#
# Both decisions are printed with the rule and the policy version, and both are in the gateway's
# log at https://tools.aquaflux.internal:4444/logs. Read the log, not this script's output, when
# you fill in the acceptance check; the log is the artefact.
#
# This is defensive work against a fictional utility's sandbox. Nothing here is a technique for
# attacking a real system: it is two ordinary tool calls, and the lab is about what refuses them.

set -uo pipefail

IDP="${AQUAFLUX_IDP:-https://idp.aquaflux.internal/realms/aquaflux}"
TOOLS="${AQUAFLUX_TOOLS:-https://tools.aquaflux.internal:4444}"
STACK_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

AGENT="collections-agent"; PERSON="els"; CONNECTION="4471"; REASON="arrears, dunning procedure complete"
NO_APPLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --agent) AGENT="${2:-}"; shift 2 ;;
    --on-behalf-of) PERSON="${2:-}"; shift 2 ;;
    --connection) CONNECTION="${2:-}"; shift 2 ;;
    --reason) REASON="${2:-}"; shift 2 ;;
    --no-apply) NO_APPLY=1; shift ;;
    -h|--help) sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2 ;;
    *) echo "attack.sh: unknown option $1" >&2; exit 2 ;;
  esac
done

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
dim()  { printf '  \033[2m%s\033[0m\n' "$*"; }

# The policy you are standing next to is the policy being enforced.
if [ "$NO_APPLY" = "0" ] && [ -d policy ]; then
  "$STACK_DIR/bin/aqx" policy apply policy 2>&1 | sed 's/^/  /'
fi

case "$PERSON" in
  sam) PASSWORD="${LAB_SAM_PASSWORD:-sam}" ;;
  els) PASSWORD="${LAB_ELS_PASSWORD:-els}" ;;
  nadia) PASSWORD="${LAB_NADIA_PASSWORD:-nadia}" ;;
  *) PASSWORD="$PERSON" ;;
esac
case "$AGENT" in
  collections-agent) SECRET="${LAB_COLLECTIONS_AGENT_SECRET:-collections-agent-secret}" ;;
  reading-assistant) SECRET="${LAB_AGENT_SECRET:-reading-assistant-secret}" ;;
  *) SECRET="${AGENT}-secret" ;;
esac

bold "Acting for $PERSON as $AGENT"
person_token="$(curl -sS -X POST "$IDP/protocol/openid-connect/token" -d grant_type=password \
  -d client_id=service-desk -d "username=$PERSON" -d "password=$PASSWORD" \
  -d "scope=openid workorder:create workorder:read" | jq -r '.access_token // empty')"
[ -n "$person_token" ] || { echo "  $PERSON could not sign in" >&2; exit 1; }
agent_token="$(curl -sS -X POST "$IDP/protocol/openid-connect/token" -d grant_type=client_credentials \
  -d "client_id=$AGENT" -d "client_secret=$SECRET" | jq -r '.access_token // empty')"
[ -n "$agent_token" ] || { echo "  $AGENT could not authenticate; is it a client in the realm?" >&2; exit 1; }
exchange="$(curl -sS -X POST "$IDP/protocol/openid-connect/token" \
  -d grant_type=urn:ietf:params:oauth:grant-type:token-exchange \
  -d "client_id=$AGENT" -d "client_secret=$SECRET" \
  -d "subject_token=$person_token" -d subject_token_type=urn:ietf:params:oauth:token-type:access_token \
  -d "actor_token=$agent_token" -d actor_token_type=urn:ietf:params:oauth:token-type:access_token \
  -d audience=wom-api -d "scope=workorder:create")"
TOKEN="$(echo "$exchange" | jq -r '.access_token // empty')"
[ -n "$TOKEN" ] || { echo "  the exchange failed: $(echo "$exchange" | jq -r '.error_description // .')" >&2; exit 1; }
dim "token: subject $PERSON, actor $AGENT, audience wom-api, scope workorder:create"

call() { # call <tool> <arguments-json>
  curl -s -o /tmp/attack-response.json -w '%{http_code}' --max-time 120 -X POST "$TOOLS/mcp" \
    -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/call\",\"params\":{\"name\":\"$1\",\"arguments\":$2}}"
}

report() { # report <tool> <http status>
  local tool="$1" status="$2" decision rule version reason wo
  decision="$(jq -r '.result._gateway.decision // .error.data.decision // "?"' /tmp/attack-response.json)"
  rule="$(jq -r '.result._gateway.rule // .error.data.rule // "?"' /tmp/attack-response.json)"
  version="$(jq -r '.result._gateway.policy_version // .error.data.policy_version // "?"' /tmp/attack-response.json)"
  reason="$(jq -r '.error.message // empty' /tmp/attack-response.json)"
  wo="$(jq -r '.result.structuredContent.work_order_id // .result.structured_content.work_order_id // empty' /tmp/attack-response.json)"
  case "$decision" in
    allow) printf '  \033[31m%-7s\033[0m %-34s %s  rule %s  policy version %s%s\n' "ALLOW" "$tool" "$status" "$rule" "$version" "${wo:+  created work order $wo}" ;;
    deny)  printf '  \033[32m%-7s\033[0m %-34s %s  rule %s  policy version %s\n' "DENY" "$tool" "$status" "$rule" "$version" ;;
    hold)  printf '  \033[33m%-7s\033[0m %-34s %s  rule %s  policy version %s\n' "HOLD" "$tool" "$status" "$rule" "$version" ;;
    *)     printf '  %-7s %-34s %s  %s\n' "$decision" "$tool" "$status" "$(head -c 200 /tmp/attack-response.json)" ;;
  esac
  [ -n "$reason" ] && dim "$reason"
  LAST_DECISION="$decision"
}

bold "Call one: the obvious tool"
status="$(call create_disconnection_work_order \
  "{\"connection_id\":\"$CONNECTION\",\"reason\":\"$REASON\",\"request_id\":\"$(uuidgen 2>/dev/null || python3 -c 'import uuid;print(uuid.uuid4())')\"}")"
report create_disconnection_work_order "$status"

if [ "$LAST_DECISION" = "allow" ]; then
  echo
  echo "  The disconnection was created. Whether that is right depends on whether an approval"
  echo "  bound to connection $CONNECTION exists; the log line says which one was used."
else
  bold "Call two: the same outcome, through the generic tool"
  status="$(call create_work_order \
    "{\"connection_id\":\"$CONNECTION\",\"work_order_type\":\"disconnection\",\"reason\":\"$REASON\",\"request_id\":\"$(uuidgen 2>/dev/null || python3 -c 'import uuid;print(uuid.uuid4())')\"}")"
  report create_work_order "$status"
  if [ "$LAST_DECISION" = "allow" ]; then
    echo
    echo "  A disconnection work order exists for connection $CONNECTION and nothing refused it."
    echo "  There was no error and no red text on the way. Find both decisions in the log and"
    echo "  read which rule allowed the second one."
  fi
fi

echo
echo "  The log:  curl -s $TOOLS/logs?limit=2 | jq ."
echo "  Or:       aqx log --last 2"
