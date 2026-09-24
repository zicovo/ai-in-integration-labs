#!/bin/sh
# Choose a model provider, then start the gateway.
#
# dec:OD-025 made a hosted model the default and kept the local runtime as a fallback, because
# c-02 asks a model to choose a generic tool and infer `disconnection` from a catalogue of
# twenty-three, and a small model on a laptop CPU may not do that reliably. The order is:
#
#   1. Azure OpenAI, if a key and an endpoint are configured and the endpoint answers.
#   2. a model runtime on the learner's own machine, if one answers. Fast on both platforms, and
#      the documented way for a learner on a slow laptop to speed the labs up.
#   3. the runtime in the container. Always there. Slower, and enough.
#
# Two and three are the fallback dec:OD-025 kept, so a delivery with no internet, an expired key
# or a blocked endpoint still runs. The lab text never changes: it names `aquaflux-default` and
# `aquaflux-alt` and never a model, a runtime or a provider.
#
# Probing once at startup rather than per call keeps the cost off every request, and the line it
# logs tells an instructor which provider a room is on before anyone asks why it is slow, or why
# a tool call went somewhere unexpected.

set -eu

MODEL="${AQUAFLUX_MODEL:-qwen2.5:3b-instruct}"
EMBED_MODEL="${AQUAFLUX_EMBED_MODEL:-nomic-embed-text}"
HOST_RUNTIME="${AQUAFLUX_HOST_RUNTIME:-http://host.docker.internal:11434}"
CONTAINER_RUNTIME="${AQUAFLUX_CONTAINER_RUNTIME:-http://ollama.aquaflux.internal:11434}"
AZURE_DEPLOYMENT="${AQUAFLUX_AZURE_DEPLOYMENT:-}"
AZURE_EMBED_DEPLOYMENT="${AQUAFLUX_AZURE_EMBED_DEPLOYMENT:-}"

# Probed with Python, not curl: this image has no curl, and a probe that cannot run is worse
# than no probe. It would fail silently, always choose the container runtime, and leave a learner
# who had started a runtime on their own machine wondering why nothing got faster.
answers() {
  python3 - "$1" <<'PROBE' >/dev/null 2>&1
import sys, urllib.request
urllib.request.urlopen(sys.argv[1] + "/api/tags", timeout=2).read()
PROBE
}

# Azure is reachable if the endpoint resolves and answers anything at all. A 401 or a 404 counts:
# it proves the endpoint is there and the network allows it, which is what this probe is for. The
# key is checked by the first real call, where a wrong one produces an error a learner can read,
# rather than here, where it would produce a silent fallback to a different model. A room quietly
# running on a different model from the one the instructor prepared is the failure to avoid.
azure_answers() {
  python3 - "$1" <<'PROBE' >/dev/null 2>&1
import sys, urllib.error, urllib.request
try:
    urllib.request.urlopen(sys.argv[1], timeout=4).read()
except urllib.error.HTTPError:
    pass
PROBE
}

MODELS=""

if [ -n "${AZURE_API_KEY:-}" ] && [ -n "${AZURE_API_BASE:-}" ] && [ -n "$AZURE_DEPLOYMENT" ]; then
  if azure_answers "$AZURE_API_BASE"; then
    # Two dialects hide behind one product name. A classic Azure OpenAI resource at
    # *.openai.azure.com puts the deployment in the URL, authenticates with an `api-key` header
    # and needs an api-version. Azure AI Foundry's v1 endpoint is plain OpenAI: model in the
    # body, bearer token, no api-version. Guessing wrong gives a 404 that reads like a missing
    # deployment rather than a wrong dialect, so the endpoint decides rather than the operator.
    case "$AZURE_API_BASE" in
      *.openai.azure.com*)
        MODELS=/etc/litellm/models.azure.yaml
        DIALECT="Azure OpenAI" ;;
      *)
        MODELS=/etc/litellm/models.hosted.yaml
        DIALECT="an OpenAI-compatible endpoint" ;;
    esac
    RUNTIME_DESCRIPTION="$DIALECT ($AZURE_API_BASE, deployment $AZURE_DEPLOYMENT)"
    echo "model gateway: using $DIALECT ($AZURE_API_BASE, deployment $AZURE_DEPLOYMENT)."
    echo "model gateway: the labs cost money on this path. The spend log is at /spend/logs."
  else
    echo "model gateway: Azure OpenAI is configured but $AZURE_API_BASE did not answer."
    echo "model gateway: falling back to a local runtime, which is slower and free."
  fi
elif [ -n "${AZURE_API_KEY:-}" ] || [ -n "${AZURE_API_BASE:-}" ]; then
  # Half-configured is worth saying out loud. Silence here is how a room ends up on the fallback
  # model without anyone noticing until a lab behaves differently from the instructor's run.
  echo "model gateway: Azure OpenAI is only half configured, so it is not being used."
  echo "model gateway: it needs AZURE_API_KEY, AZURE_API_BASE and AQUAFLUX_AZURE_DEPLOYMENT."
  echo "model gateway: labs/stack/.env.example lists all of them."
fi

if [ -z "$MODELS" ]; then
  MODELS=/etc/litellm/models.local.yaml
  if answers "$HOST_RUNTIME"; then
    RUNTIME="$HOST_RUNTIME"
    RUNTIME_DESCRIPTION="the model runtime on your own machine ($HOST_RUNTIME)"
    echo "model gateway: using the model runtime on your own machine ($HOST_RUNTIME)."
  else
    RUNTIME="$CONTAINER_RUNTIME"
    RUNTIME_DESCRIPTION="the model runtime in the container ($CONTAINER_RUNTIME)"
    echo "model gateway: using the model runtime in the container ($CONTAINER_RUNTIME)."
    echo "model gateway: no runtime answered on your own machine. That is fine, and it is the"
    echo "model gateway: fallback. If the labs feel slow, labs/README.md says how to run one there."
  fi
else
  RUNTIME="$CONTAINER_RUNTIME"
fi

# Embeddings are chosen separately from the chat model, because a hosted resource often has a
# chat deployment and no embedding one, and b-01 needs vectors either way. The hosted embedding
# is used only if one real request for it succeeds; otherwise the local runtime embeds, on the
# learner's machine if a runtime answers there and in the container if not. Said out loud, and
# written to /tmp/aquaflux-embedding, because the smoke test prints the model name and the vector
# length and the handout tells the learner to use those rather than the ones it prints.
hosted_embedding_answers() {
  python3 - "$1" "$2" "$3" "$4" <<'PROBE' >/dev/null 2>&1
import json, sys, urllib.request
base, key, deployment, dialect = sys.argv[1:5]
if dialect == "azure":
    url = f"{base.rstrip('/')}/openai/deployments/{deployment}/embeddings?api-version=2024-10-21"
    headers = {"api-key": key, "Content-Type": "application/json"}
else:
    url = f"{base.rstrip('/')}/embeddings"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
body = json.dumps({"model": deployment, "input": "probe"}).encode()
with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=15) as response:
    data = json.load(response)
assert data["data"][0]["embedding"]
PROBE
}

EMBED=/etc/litellm/embed.local.yaml
if answers "$HOST_RUNTIME"; then EMBED_RUNTIME="$HOST_RUNTIME"; else EMBED_RUNTIME="$CONTAINER_RUNTIME"; fi
EMBED_DESCRIPTION="$EMBED_MODEL on the model runtime ($EMBED_RUNTIME)"
if [ "$MODELS" != /etc/litellm/models.local.yaml ] && [ -n "$AZURE_EMBED_DEPLOYMENT" ]; then
  case "$MODELS" in *azure.yaml) EMBED_DIALECT=azure ;; *) EMBED_DIALECT=openai ;; esac
  if hosted_embedding_answers "$AZURE_API_BASE" "$AZURE_API_KEY" "$AZURE_EMBED_DEPLOYMENT" "$EMBED_DIALECT"; then
    EMBED=/etc/litellm/embed.$EMBED_DIALECT.yaml
    EMBED_DESCRIPTION="the hosted embedding deployment $AZURE_EMBED_DEPLOYMENT"
  else
    echo "model gateway: the hosted embedding deployment $AZURE_EMBED_DEPLOYMENT did not answer;"
    echo "model gateway: embeddings come from $EMBED_MODEL on the local runtime instead."
  fi
fi
echo "model gateway: embeddings by $EMBED_DESCRIPTION."
printf '%s\n' "$EMBED_DESCRIPTION" > /tmp/aquaflux-embedding

CONFIG=/tmp/config.yaml
cat "$MODELS" "$EMBED" /etc/litellm/config.yaml \
  | sed -e "s|AQUAFLUX_RUNTIME_BASE|$RUNTIME|g" \
        -e "s|AQUAFLUX_EMBED_RUNTIME_BASE|$EMBED_RUNTIME|g" \
        -e "s|AQUAFLUX_AZURE_EMBED_DEPLOYMENT|$AZURE_EMBED_DEPLOYMENT|g" \
        -e "s|AQUAFLUX_AZURE_DEPLOYMENT|$AZURE_DEPLOYMENT|g" \
        -e "s|AQUAFLUX_EMBED_MODEL|$EMBED_MODEL|g" \
        -e "s|AQUAFLUX_MODEL|$MODEL|g" \
  > "$CONFIG"

echo "model gateway: serving aquaflux-default, aquaflux-alt and aquaflux-embed."

# Also written down, not only said. The startup lines are the only record of which provider a
# room is on, and a container that has been up for a while buries them under health checks, so
# `verify.sh` could not find them and reported that nobody could tell. Now it can read this.
printf '%s\n' "$RUNTIME_DESCRIPTION" > /tmp/aquaflux-provider

exec litellm --config "$CONFIG" --host 0.0.0.0 --port 4000
