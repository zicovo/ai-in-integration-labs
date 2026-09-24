#!/usr/bin/env bash
# Start the profiles one module needs and check the preconditions its handout promises.
#
# This is the only command a handout tells a learner to run before the task starts. Setup is never
# a lab objective (.ai/PEDAGOGY.md), so if this fails, that is the stack's problem and not theirs.
#
# Usage: labs/stack/smoke.sh <module-id>
#
# The module-to-profile map is in labs/README.md and must agree with this file.

set -euo pipefail

STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$STACK_DIR/../.." && pwd)"
COMPOSE=(docker compose -f "$STACK_DIR/docker-compose.yml")

ok()   { printf '  \033[32mok\033[0m    %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAILED=1; }
note() { printf '  \033[33m..\033[0m    %s\n' "$*"; }
head_() { printf '\n\033[1m%s\033[0m\n' "$*"; }

FAILED=0

# Which profiles each module needs. Keep in step with labs/README.md.
profiles_for() {
  case "$1" in
    a-02) echo "core model" ;;
    b-01|b-02) echo "model retrieval" ;;
    c-02) echo "core model identity tools" ;;
    d-02) echo "core identity tools" ;;
    d-03) echo "core identity tools policy" ;;
    d-04) echo "core model identity tools policy telemetry" ;;
    e-03) echo "core model identity tools policy telemetry workflow" ;;
    f-01) echo "core model identity tools policy" ;;
    *) return 1 ;;
  esac
}

# Profiles that exist in docker-compose.yml today. The rest are reserved in labs/README.md and
# are built in the order HANDOFF-LAB.md sets.
BUILT_PROFILES="core model identity tools policy telemetry retrieval workflow"

usage() {
  cat >&2 <<'USAGE'
usage: labs/stack/smoke.sh <module-id>

  a-02  b-01  b-02  c-02  d-02  d-03  d-04  e-03  f-01
USAGE
  exit 2
}

[ $# -eq 1 ] || usage
MODULE="$1"
WANTED="$(profiles_for "$MODULE")" || usage

# ---------------------------------------------------------------- bring the stack up

READY=""
MISSING=""
for p in $WANTED; do
  case " $BUILT_PROFILES " in
    *" $p "*) READY="$READY $p" ;;
    *) MISSING="$MISSING $p" ;;
  esac
done

head_ "Starting the stack for $MODULE"
printf '  profiles:%s\n' "$WANTED"

# Start the services in those profiles by name, never the profiles themselves. `workspace` has no
# profile, because the editor could not start it otherwise, so every `--profile ... up` would
# include it and recreate the container this script is running inside. Ask Compose which services
# the profiles name, drop the workspace, start the rest.
args=()
for p in $READY; do args+=(--profile "$p"); done
services="$("${COMPOSE[@]}" "${args[@]}" config --services | grep -vx workspace | tr '\n' ' ')"

if [ -z "${services// /}" ]; then
  bad "no services found for profiles:$READY"
else
  # shellcheck disable=SC2086
  "${COMPOSE[@]}" up -d --wait --quiet-pull $services
  ok "profiles up:$READY"
fi

if [ -n "$MISSING" ]; then
  note "not built yet:$MISSING (HANDOFF-LAB.md has the build order)"
fi

# ------------------------------------------------------------------- the checks

json() { curl -fsS --max-time 10 "$@"; }

# Every Aquaflux address is served over TLS by the ingress, from one certificate signed by the
# lab's own authority. Trusting that authority is setup, and setup is never the task, so it
# happens here rather than in a handout. Idempotent: it only works when something has changed.
#
# The ROOT goes in the trust store, never the certificate the servers present. An earlier version
# generated a single self-signed certificate that was its own authority and served that; every
# command line client accepted it and both browsers refused it, which is how the stack came to
# have a "Not Secure" chip nobody could remove.
trust_lab_certificate_authority() {
  local src=/etc/aquaflux/tls/ca.crt
  local dst=/usr/local/share/ca-certificates/aquaflux-ca.crt
  [ -s "$src" ] || return 0
  if [ -s "$dst" ] && cmp -s "$src" "$dst"; then
    return 0
  fi
  sudo cp "$src" "$dst" && sudo update-ca-certificates >/dev/null 2>&1
  ok "the lab certificate authority is trusted, so https needs no --insecure"
}

check_identity() {
  head_ "Identity provider"

  if json "https://idp.aquaflux.internal/realms/aquaflux/.well-known/openid-configuration" >/dev/null; then
    ok "the aquaflux realm answers at idp.aquaflux.internal over TLS"
  else
    bad "the identity provider is not answering at idp.aquaflux.internal"
    return
  fi

  local token
  token="$(curl -fsS --max-time 10 -X POST \
    https://idp.aquaflux.internal/realms/aquaflux/protocol/openid-connect/token \
    -d grant_type=password -d client_id=service-desk \
    -d username=nadia -d password="${LAB_NADIA_PASSWORD:-nadia}" | jq -r '.access_token // empty')"
  if [ -n "$token" ]; then
    ok "Nadia can sign in and the token decodes"
  else
    bad "Nadia cannot sign in"
    return
  fi

  head_ "Delegation"
  note "checking the exchange d-02 turns on, and which claim carries the actor"
  if python3 "$STACK_DIR/check_delegation.py"; then
    ok "Nadia's authority reaches the work order API through the agent"
  else
    bad "the delegation chain is broken (see above)"
  fi
}

check_core() {
  head_ "Aquaflux systems of record"

  # Put the seeded work orders back before anything is checked. c-02 and e-03 clear connection
  # 4471 at the end of their own smoke test, and 88213 lives there, so without this a d-04
  # session that follows a c-02 session starts with its worked tier missing.
  curl -fsS -X POST https://wom.aquaflux.internal/v4/_reset >/dev/null 2>&1 || true

  if json https://mdm.aquaflux.internal/health >/dev/null; then
    ok "meter data management answers at mdm.aquaflux.internal"
  else
    bad "meter data management is not answering"
  fi

  if json https://cis.aquaflux.internal/health >/dev/null; then
    ok "customer information system answers at cis.aquaflux.internal"
  else
    bad "customer information system is not answering"
  fi

  if json https://wom.aquaflux.internal/health >/dev/null; then
    ok "work order management answers at wom.aquaflux.internal"
  else
    bad "work order management is not answering"
  fi

  local n
  n="$(json 'https://mdm.aquaflux.internal/readings?connection_id=4471&from=2026-01-01&to=2026-06-30' | jq 'length')"
  if [ "$n" = "6" ]; then
    ok "connection 4471 has six monthly readings for the first half of 2026"
  else
    bad "connection 4471 returned $n readings, expected 6"
  fi

  local jan mar
  jan="$(json 'https://mdm.aquaflux.internal/readings?connection_id=4471' | jq '.[0].volume_m3')"
  mar="$(json 'https://mdm.aquaflux.internal/readings?connection_id=4471' | jq '.[2].volume_m3')"
  if [ "$(( mar > jan * 3 / 2 ? 1 : 0 ))" = "1" ]; then
    ok "connection 4471 consumption rises in March ($jan to $mar cubic metres)"
  else
    bad "connection 4471 does not rise in March ($jan to $mar), which a-02's worked example needs"
  fi

  if json https://mdm.aquaflux.internal/readings?connection_id=4417 >/dev/null; then
    ok "connection 4417 exists, so a-02's transposition has somewhere to land"
  else
    bad "connection 4417 is missing"
  fi
}

check_model() {
  head_ "Model gateway"

  local models
  if ! models="$(json https://models.aquaflux.internal:4000/v1/models -H "Authorization: Bearer ${LAB_GATEWAY_KEY:-sk-aquaflux-lab}")"; then
    bad "the model gateway is not answering at models.aquaflux.internal:4000"
    return
  fi
  ok "model gateway answers at models.aquaflux.internal:4000"

  for name in aquaflux-default aquaflux-alt; do
    if echo "$models" | jq -e --arg n "$name" '.data[]? | select(.id == $n)' >/dev/null; then
      ok "the gateway serves $name"
    else
      bad "the gateway does not serve $name"
    fi
  done

  # With no key in labs/stack/.env the gateway falls back to the model runtime in the container,
  # and on a machine that has never run the stack that runtime holds no model. Pull it once here,
  # the way the embedding model is pulled for b-01, rather than let a-02 fail on a missing model.
  local provider local_model
  provider="$("${COMPOSE[@]}" exec -T models cat /tmp/aquaflux-provider 2>/dev/null)"
  local_model="$("${COMPOSE[@]}" exec -T models printenv AQUAFLUX_MODEL 2>/dev/null)"
  local_model="${local_model:-qwen2.5:3b-instruct}"
  case "$provider" in
    "the model runtime in the container"*)
      if ! "${COMPOSE[@]}" exec -T ollama ollama list 2>/dev/null | grep -q "^${local_model}"; then
        note "no key in labs/stack/.env, so the labs run on the local model; pulling $local_model once (about 2 GB)"
        if "${COMPOSE[@]}" exec -T ollama ollama pull "$local_model" >/dev/null 2>&1; then
          ok "$local_model is pulled into the model runtime"
        else
          bad "could not pull $local_model into the model runtime; is there internet access?"
        fi
      fi ;;
  esac

  head_ "What the model can actually do"
  note "checking tool calling and strict JSON output, which a-02 requires of whatever model is behind the gateway"
  if python3 "$STACK_DIR/check_model.py"; then
    ok "tool calling and strict JSON output both work"
  else
    bad "the model behind the gateway cannot do what a-02 needs (see above)"
  fi
}

check_tools() {
  head_ "Tool gateway"

  local version
  if ! version="$(json https://tools.aquaflux.internal:4444/version)"; then
    bad "the tool gateway is not answering at tools.aquaflux.internal:4444"
    return
  fi
  ok "tool gateway $(echo "$version" | jq -r .version) answers at tools.aquaflux.internal:4444"

  # Which policy is loaded is setup, and setup is never the task. c-02 starts on the rule that
  # can only name the generic operation; d-02 and e-03 start on the one that reads the token; the
  # modules with a policy engine are switched onto it in check_policy, below.
  local policy="wo-tools-1"
  case "$MODULE" in
    d-02) policy="wo-tools-4" ;;
    e-03) policy="wo-tools-5" ;;
    d-03|d-04|f-01) policy="" ;;
  esac
  if [ -n "$policy" ]; then
    if curl -fsS -X PUT "https://tools.aquaflux.internal:4444/policy/$policy" >/dev/null; then
      ok "policy $policy is active"
    else
      bad "the gateway would not activate $policy"
    fi
  fi

  # A catalogue left over from somebody else's run is the most confusing state a lab can start
  # in: the tools are listed and the process behind them is gone.
  local servers
  servers="$(json https://tools.aquaflux.internal:4444/servers | jq 'length')"
  case "$MODULE" in
    d-03|d-04|f-01) ;;  # check_policy replaces the catalogue with the collections tools
    e-03) ;;            # check_workflow registers the curated server
    d-02)
      # d-02's step five calls create_meter_check_work_order by hand. The server behind it is a
      # process in this container, and a container that has been restarted since c-02 has none,
      # so register it here rather than leave the learner to find a 404 at the central moment.
      head_ "The tool behind the gateway"
      if "$STACK_DIR/register-tool-server.sh" labs/c-02/curated 8850 --policy "$policy" >/dev/null 2>&1; then
        ok "create_meter_check_work_order is registered at the gateway, policy $policy"
      else
        bad "the curated work order server did not register"
      fi ;;
    *)
      if [ "$servers" = "0" ]; then
        ok "the catalogue is empty, which is where c-02 starts"
      else
        note "$servers MCP server(s) are still registered from an earlier run"
        note "clear them with: labs/stack/register-tool-server.sh --stop"
      fi ;;
  esac
}

check_policy() {
  head_ "Policy engine"

  local health
  if ! health="$(json https://policy.aquaflux.internal:8181/health)"; then
    bad "the policy engine is not answering at policy.aquaflux.internal:8181"
    return
  fi
  if [ "$health" = "{}" ]; then
    ok "the policy engine answers at policy.aquaflux.internal:8181 (an empty object, as the handout says)"
  else
    bad "the policy engine's health answer is $health, and the handout promises an empty object"
  fi

  if json https://approvals.aquaflux.internal/health >/dev/null; then
    ok "the approval service answers at approvals.aquaflux.internal"
  else
    bad "the approval service is not answering"
  fi
  # An approval from an earlier session would quietly turn a refusal into a success.
  curl -fsS -X DELETE https://approvals.aquaflux.internal/approvals >/dev/null 2>&1 \
    && ok "no approvals are carried over from an earlier session" \
    || bad "could not clear the approvals"

  if [ "$MODULE" = "d-04" ]; then
    head_ "The reading assistant's catalogue"
    # d-04 runs the reading assistant against c-02's curated server, behind the gateway, with
    # the policy engine deciding: the setup the handout describes. The server is a process in
    # this container, like c-02's, started and registered here.
    if "$STACK_DIR/register-tool-server.sh" labs/c-02/curated 8850 >/dev/null 2>&1; then
      ok "the curated work order server is registered: create_meter_check_work_order and get_work_order_status"
    else
      bad "the curated work order server did not register"
    fi
  else
  head_ "The collections agent's catalogue"
  # Replace whatever is behind the gateway with the collections tools. c-02's servers are
  # processes in this container and are stopped; the collections tools are a container in the
  # policy profile and are registered by service name.
  "$STACK_DIR/register-tool-server.sh" --stop >/dev/null 2>&1 || true
  local registered
  registered="$(curl -sS -X POST https://tools.aquaflux.internal:4444/servers -H 'content-type: application/json' \
    -d '{"name":"collections","url":"http://collections-tools:8852/mcp"}' | jq -r '.tools | length' 2>/dev/null || echo 0)"
  if [ "${registered:-0}" -ge 6 ]; then
    ok "the collections tools are registered: $registered tools"
  else
    bad "the collections tools did not register (is the collections-tools container healthy?)"
  fi
  local tools
  tools="$(json https://tools.aquaflux.internal:4444/tools | jq -r '.[].name' | tr '\n' ' ')"
  case "$tools" in
    *create_disconnection_work_order*create_work_order*|*create_work_order*create_disconnection_work_order*)
      ok "the catalogue holds both create_disconnection_work_order and the generic create_work_order" ;;
    *) bad "the catalogue is missing the specific or the generic tool: $tools" ;;
  esac
  fi

  head_ "The starting policy"
  # The module's own policy directory, loaded as it stands. Never overwritten: if a learner has
  # edited it, what they edited is what is enforced, which is the point. d-04 has no policy of
  # its own: it runs the reading assistant against d-03's rule and register, which already
  # names the reading assistant and its two curated tools.
  local dir="$REPO_DIR/labs/$MODULE/policy"
  case "$MODULE" in d-04) dir="$REPO_DIR/labs/d-03/policy" ;; esac
  if [ -d "$dir" ]; then
    if out="$("$STACK_DIR/bin/aqx" policy apply "$dir" 2>&1)"; then
      ok "$(echo "$out" | tail -1 | sed 's/^ *//')"
    else
      bad "the policy in $dir would not load:"; echo "$out" | sed 's/^/        /'
    fi
  else
    bad "no policy directory at $dir"
  fi
  if command -v opa >/dev/null 2>&1; then
    ok "opa $(opa version | head -1 | sed 's/Version: //') is on the path, for opa test policy/"
  else
    bad "opa is not on the path; rebuild the dev container (HANDOFF-STACK.md says how)"
  fi

  head_ "Dunning cases"
  curl -fsS -X POST https://cis.aquaflux.internal/dunning/_reset >/dev/null 2>&1 \
    && ok "dunning cases reset, case 4471 carries note-variant-a" \
    || bad "could not reset the dunning cases"
  if [ "$(json https://cis.aquaflux.internal/dunning/4471 | jq -r '.notes | length')" = "1" ]; then
    ok "case 4471 is overdue with one customer note attached"
  else
    bad "case 4471 has no note, which f-01 depends on"
  fi
  if [ "$(curl -s -o /dev/null -w '%{http_code}' https://cis.aquaflux.internal/dunning/4472)" = "404" ]; then
    ok "connection 4472 is not in arrears, so d-03's reuse test has somewhere to fail"
  else
    bad "connection 4472 has a dunning case and should not"
  fi
}

check_wom_module() {
  head_ "Work orders"
  if json https://wom.aquaflux.internal/v4/work-orders/88213 >/dev/null; then
    ok "work order 88213 exists for d-04's worked tier"
  else
    bad "work order 88213 is missing"
  fi
}

check_retrieval() {
  head_ "Retrieval stores"
  local pgv
  pgv="$(psql "${AQUAFLUX_DB:-postgres://aquaflux:aquaflux@db.aquaflux.internal:5432/aquaflux}" -tAc "select default_version from pg_available_extensions where name = 'vector'" 2>/dev/null | tr -d ' ')"
  if [ -n "$pgv" ]; then
    ok "PostgreSQL answers at db.aquaflux.internal with pgvector $pgv available"
  else
    bad "PostgreSQL is not answering, or pgvector is not installed"
  fi
  if json https://vectors.aquaflux.internal:6333/healthz >/dev/null; then
    local points
    points="$(json https://vectors.aquaflux.internal:6333/collections | jq '.result.collections | length')"
    if [ "$points" = "0" ]; then
      ok "the vector engine answers at vectors.aquaflux.internal:6333 and is empty, as the handout says"
    else
      note "the vector engine holds $points collection(s) from an earlier run; the open tier starts from empty"
    fi
  else
    bad "the vector engine is not answering at vectors.aquaflux.internal:6333"
  fi

  head_ "Embeddings"
  # The gateway chose the embedding provider at startup and wrote it down. The handout tells the
  # learner to read the model name and the vector length from here and to use those.
  local provider embed
  embed="$(json https://models.aquaflux.internal:4000/v1/embeddings -H "Authorization: Bearer ${LAB_GATEWAY_KEY:-sk-aquaflux-lab}" \
    -H 'content-type: application/json' -d '{"model":"aquaflux-embed","input":"gate valve spindle"}' 2>/dev/null)"
  local dims
  dims="$(echo "$embed" | jq '.data[0].embedding | length' 2>/dev/null || echo 0)"
  provider="$("${COMPOSE[@]}" exec -T models cat /tmp/aquaflux-embedding 2>/dev/null || echo "unknown")"
  if [ "${dims:-0}" -gt 0 ] 2>/dev/null; then
    ok "aquaflux-embed answers: $provider, $dims dimensions. Use vector($dims) in your schema."
  else
    bad "aquaflux-embed did not return a vector: $(echo "$embed" | jq -r '.error.message // .' 2>/dev/null | cut -c1-120)"
    case "$provider" in
      *"model runtime"*)
        note "the local embedding model may not be pulled yet; pulling nomic-embed-text into the runtime"
        "${COMPOSE[@]}" exec -T ollama ollama pull nomic-embed-text >/dev/null 2>&1 \
          && ok "nomic-embed-text is pulled; run this smoke test again" \
          || bad "could not pull nomic-embed-text into the runtime" ;;
    esac
  fi

  head_ "The corpus"
  local docs
  docs="$(ls "$REPO_DIR"/labs/corpus/b-01/documents/*.md 2>/dev/null | wc -l | tr -d ' ')"
  if [ "$docs" = "20" ]; then
    ok "twenty documents under labs/corpus/b-01/documents, with two scanned pages and one superseded page beside them"
  else
    bad "labs/corpus/b-01/documents holds $docs documents, expected twenty"
  fi
  if [ "$MODULE" = "b-01" ]; then
    # b-01's worked tier creates the table itself. One left over from an earlier session makes
    # step one fail on "already exists" and would let step two add a second copy of every chunk;
    # say so here, with the one line that clears it, rather than let the learner meet both.
    local rows
    rows="$(psql "${AQUAFLUX_DB:-postgres://aquaflux:aquaflux@db.aquaflux.internal:5432/aquaflux}" -tAc "select count(*) from chunks" 2>/dev/null | tr -d ' ')"
    if [ -n "$rows" ]; then
      note "a chunks table is already there with $rows rows, from an earlier run of this lab or of b-02"
      note "to start the worked tier from nothing:  psql \"\$AQUAFLUX_DB\" -c 'drop table chunks'"
    else
      ok "no chunks table yet: step one of the worked tier creates it"
    fi
  fi
  if [ "$MODULE" = "b-02" ]; then
    # b-02 continues from b-01's index. If it is not there, load the reference one.
    local rows
    rows="$(psql "${AQUAFLUX_DB:-postgres://aquaflux:aquaflux@db.aquaflux.internal:5432/aquaflux}" -tAc "select count(*) from chunks" 2>/dev/null | tr -d ' ')"
    if [ -n "$rows" ] && [ "$rows" -gt 0 ] 2>/dev/null; then
      ok "the chunks table from b-01 is there with $rows rows"
    else
      note "no chunks table from b-01; loading the reference index (about a minute)"
      if (cd "$REPO_DIR/labs/b-01" && python3 index.py --replace >/dev/null 2>&1); then
        ok "the reference index is loaded: $(psql "${AQUAFLUX_DB:-postgres://aquaflux:aquaflux@db.aquaflux.internal:5432/aquaflux}" -tAc 'select count(*) from chunks' | tr -d ' ') rows"
      else
        bad "the reference index would not load; run labs/b-01/index.py by hand and read the error"
      fi
    fi
  fi
}

check_telemetry() {
  head_ "Telemetry"
  # The audit store is append-only, so a stack that has been through d-04 once holds the fixed
  # state in it. Empty it and let the seed put the history back, so the lab starts as the
  # handout describes it whoever ran it last.
  if "$STACK_DIR/bin/aqx" telemetry reset >/dev/null 2>&1; then
    ok "the audit store is empty and the trace store holds the seeded history"
  else
    bad "aqx telemetry reset failed (docker compose logs telemetry-seed)"
  fi
  # The collector runs whatever labs/d-04/collector.yaml says, as the policy engine runs the
  # learner's policy/. Applying it is setup; what is in the file is never overwritten.
  if out="$("$STACK_DIR/bin/aqx" collector apply "$REPO_DIR/labs/d-04/collector.yaml" 2>&1)"; then
    ok "$(echo "$out" | tail -1 | sed 's/^ *//')"
  else
    bad "the collector would not start from labs/d-04/collector.yaml:"; echo "$out" | sed 's/^/        /'
  fi
  if [ "$(curl -s --max-time 10 https://collector.aquaflux.internal:13133/healthz | jq -r '.status // empty' 2>/dev/null)" = "Server available" ] \
     || curl -fsS --max-time 10 https://collector.aquaflux.internal:13133/healthz >/dev/null 2>&1; then
    ok "the collector answers at collector.aquaflux.internal:13133/healthz"
  else
    bad "the collector is not answering at collector.aquaflux.internal:13133"
  fi
  # The history takes a few seconds to arrive after a cold start; wait for it rather than fail.
  # The trace store is Jaeger 2, whose query API is /api/v3 only (labs/README.md, conventions).
  local services="" i
  for i in $(seq 1 30); do
    services="$(curl -s --max-time 10 https://traces.aquaflux.internal:16686/api/v3/services | jq -r '.services[]?' 2>/dev/null | tr '\n' ' ' || true)"
    case "$services" in *reading-assistant*tool-gateway*|*tool-gateway*reading-assistant*) break ;; esac
    sleep 2
  done
  case "$services" in
    *reading-assistant*tool-gateway*|*tool-gateway*reading-assistant*)
      ok "the trace store lists reading-assistant and tool-gateway, so the history is seeded" ;;
    *) bad "the trace store does not list reading-assistant and tool-gateway (services: ${services:-none})" ;;
  esac
  local spans
  spans="$(curl -s --max-time 10 https://traces.aquaflux.internal:16686/api/v3/traces/0af7651916cd43dd8448eb211c80319c | jq '.result.resourceSpans | length' 2>/dev/null || echo 0)"
  if [ "${spans:-0}" -ge 1 ] 2>/dev/null; then
    ok "the run that created work order 88213 is in the trace store"
  else
    bad "the seeded run for work order 88213 is not in the trace store"
  fi
  if curl -fsS --max-time 10 https://collector.aquaflux.internal:13133/audit/audit.jsonl -o /dev/null; then
    ok "the audit store is readable at collector.aquaflux.internal:13133/audit/audit.jsonl"
  else
    bad "the audit store is not readable through the ingress"
  fi
}

check_workflow() {
  head_ "Workflow engine"
  # The engine is reached by service name from here (gRPC, never leaves the network); its web
  # interface is the public address the handout prints. Both are checked, because the second is
  # the part of the lab that cannot be done from the terminal.
  local version
  if version="$(python3 "$STACK_DIR/workflow/check.py" version 2>/dev/null)"; then
    ok "workflow engine answers: Temporal server $version, development mode"
  else
    bad "the workflow engine is not answering at workflow:7233"
    return
  fi
  if [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 https://workflow.aquaflux.internal:8233/api/v1/namespaces)" = "200" ]; then
    ok "its web interface answers at workflow.aquaflux.internal:8233"
  else
    bad "the web interface is not answering at workflow.aquaflux.internal:8233"
  fi

  head_ "The tool behind the gateway"
  # e-03 runs the meter check through c-02's curated tool, behind the gateway under the policy
  # that reads the token. The server is a process in this container, like c-02's own.
  if "$STACK_DIR/register-tool-server.sh" labs/c-02/curated 8850 --policy wo-tools-5 >/dev/null 2>&1; then
    ok "create_meter_check_work_order is registered at the gateway, policy wo-tools-5"
  else
    bad "the curated work order server did not register"
  fi
  curl -fsS -X DELETE https://approvals.aquaflux.internal/approvals >/dev/null 2>&1 \
    && ok "no approvals are carried over from an earlier session" \
    || bad "could not clear the approvals"

  head_ "The worker"
  # A worker has to be polling before the handout's first command, and the handout starts on the
  # broken tier. If one is already running (a learner re-running the smoke test mid-lab, from
  # whichever directory they are on), it is left alone: their edits are what should be running.
  if python3 "$STACK_DIR/workflow/check.py" pollers >/dev/null 2>&1 && [ -f "$STACK_DIR/.worker/pid" ] \
     && kill -0 "$(cat "$STACK_DIR/.worker/pid")" 2>/dev/null; then
    local running; running="$(cat "$STACK_DIR/.worker/dir" 2>/dev/null)"
    ok "a worker is already polling aquaflux-meter-check, running $running"
    if [ "$running" != "labs/e-03/broken" ]; then
      note "the handout starts on broken/. For a fresh start: labs/stack/start-worker.sh labs/e-03/broken"
    fi
  elif out="$("$STACK_DIR/start-worker.sh" labs/e-03/broken 2>&1)"; then
    ok "$(echo "$out" | tail -1 | sed 's/\x1b\[[0-9;]*m//g; s/^ *ok *//')"
  else
    bad "the worker did not start:"; echo "$out" | sed 's/^/        /'
  fi

  head_ "Telemetry"
  # The acceptance check asks for the correlation id in the trace, so the collector and the trace
  # store are up for e-03 too. Nothing of d-04's state is reset here: this only makes sure the
  # collector has a configuration to run with, the learner's own if d-04 has been done.
  if [ ! -f "$STACK_DIR/collector/collector.yaml" ]; then
    "$STACK_DIR/bin/aqx" collector apply "$REPO_DIR/labs/d-04/collector.yaml" >/dev/null 2>&1 || true
  fi
  if curl -fsS --max-time 10 https://collector.aquaflux.internal:13133/healthz >/dev/null 2>&1; then
    ok "the collector answers, so the run's spans reach the trace store at traces.aquaflux.internal:16686"
  else
    note "the collector is not answering; the run works without it, and aqx trace will find nothing"
  fi
}

trust_lab_certificate_authority

case "$MODULE" in
  a-02) check_core; check_model ;;
  c-02) check_core; check_model; check_identity; check_wom_module; check_tools ;;
  e-03) check_core; check_model; check_identity; check_tools; check_workflow ;;
  f-01) check_core; check_model; check_identity; check_wom_module; check_tools; check_policy ;;
  d-02) check_core; check_identity; check_wom_module; check_tools ;;
  d-03) check_core; check_identity; check_wom_module; check_tools; check_policy ;;
  d-04) check_core; check_model; check_identity; check_wom_module; check_tools; check_policy; check_telemetry ;;
  b-01|b-02) check_model; check_retrieval ;;
esac

# c-02 and e-03 both start from a clean connection 4471.
#
# c-02 needs it because work order 88213 is seeded on that connection for d-04, and an agent
# asked to check the meter finds it, says a meter check has already been proposed, and stops.
# Measured, five runs out of five: the lab never reaches its own deliberate failure. e-03 needs
# it because it runs the failure more than once.
# d-03 and f-01 create disconnection work orders on 4471 as they run, and the second run of the
# attack should look like the first.
if [ "$MODULE" = "e-03" ] || [ "$MODULE" = "c-02" ] || [ "$MODULE" = "d-03" ] || [ "$MODULE" = "f-01" ]; then
  head_ "Reset"
  curl -fsS -X DELETE 'https://wom.aquaflux.internal/v4/work-orders?connection_id=4471' >/dev/null \
    && ok "work orders for connection 4471 cleared" \
    || bad "could not clear work orders for connection 4471"
fi

echo
if [ "$FAILED" = "0" ] && [ -z "$MISSING" ]; then
  printf '\033[32mSmoke test passed for %s.\033[0m You can start the task.\n' "$MODULE"
elif [ "$FAILED" = "0" ]; then
  printf '\033[33mEverything that is built passed for %s,\033[0m but%s is not built yet.\n' "$MODULE" "$MISSING"
  exit 1
else
  printf '\033[31mSmoke test failed for %s.\033[0m Ask the instructor; this is not your task.\n' "$MODULE"
  exit 1
fi
