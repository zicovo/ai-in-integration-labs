"""Telemetry for the lab agents: spans, one trace per run, exported to the collector when it is up.

reconstruct-one-transaction is the lab about this, and everything here is what that lab reads. The other labs run the
same agents with the telemetry profile down, so the one rule this module keeps is that nothing
here may make an agent slower or noisier when there is no collector: the exporter is installed
only after a half-second probe finds one, and otherwise spans are created and dropped.

What gets written, and by whom:

    invoke_agent <name>     one per run, the root. Agent, person, prompt version, content flag
    chat <model>            one per model call. Requested model, the model that answered, tokens
    execute_tool <tool>     one per tool call. Tool name, argument hash, the gateway's call id

The `traceparent` header goes out on every call to the model gateway and the tool gateway, so
their spans join this trace (W3C Trace Context). Content, meaning messages, arguments and results,
is captured only when AQUAFLUX_CAPTURE_CONTENT is on, which it is by default in this stack and is
not in any framework's default; the generative AI semantic conventions say capture "SHOULD be
gated by an explicit user opt-in", and this flag is that opt-in.

Attribute names: the `gen_ai.*` names follow the OpenTelemetry generative AI semantic conventions
(Development status; they move), the `aquaflux.*` names are the audit schema in
labs/reconstruct-one-transaction/audit-schema.md, which the collector normalises into and which does not move.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import logging
import os
import socket
import urllib.parse
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

COLLECTOR = os.environ.get("AQUAFLUX_OTLP", "http://collector:4318")
CAPTURE_CONTENT = os.environ.get("AQUAFLUX_CAPTURE_CONTENT", "true").lower() in ("1", "true", "yes", "on")
CONTENT_LIMIT = 4000

_provider: TracerProvider | None = None
_exporting = False


def collector_reachable(endpoint: str = COLLECTOR, timeout: float = 0.5) -> bool:
    """A TCP probe, not an HTTP call: the question is only whether anything is listening."""
    url = urllib.parse.urlparse(endpoint)
    try:
        with socket.create_connection((url.hostname, url.port or 4318), timeout=timeout):
            return True
    except OSError:
        return False


def setup(service_name: str) -> trace.Tracer:
    """Install the tracer provider once per process and return a tracer.

    Exports over OTLP/HTTP when the collector answers; otherwise spans are created, propagated
    and dropped, so a run in a lab without the telemetry profile behaves exactly as before.
    """
    global _provider, _exporting
    if _provider is None:
        resource = Resource.create({
            "service.name": service_name,
            "service.namespace": "aquaflux",
            "deployment.environment.name": "lab",
        })
        _provider = TracerProvider(resource=resource)
        if collector_reachable():
            # Short timeout, no long retry: a collector that has just gone away must not hold
            # a one-shot agent process open at exit.
            logging.getLogger("opentelemetry").setLevel(logging.CRITICAL)
            exporter = OTLPSpanExporter(endpoint=f"{COLLECTOR}/v1/traces", timeout=3)
            _provider.add_span_processor(BatchSpanProcessor(exporter, export_timeout_millis=3000))
            _exporting = True
        trace.set_tracer_provider(_provider)
        atexit.register(_provider.shutdown)
    return trace.get_tracer(service_name)


def exporting() -> bool:
    return _exporting


def headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The outbound headers for one HTTP call: whatever was passed, plus `traceparent`."""
    carrier: dict[str, str] = dict(extra or {})
    inject(carrier)
    return carrier


def trace_id() -> str | None:
    """The current trace id as 32 hex characters, or None outside a span."""
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x")


def sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def prompt_version(agent: str, system_prompt: str) -> str:
    """A version for the instructions, derived from their text: `<agent>/<8 hex>`.

    A real deployment takes this from its configuration store. Deriving it from the text is the
    same promise in one line: change a word and the version changes, and a trace says which one
    was in force.
    """
    return f"{agent}/{hashlib.sha256(system_prompt.encode()).hexdigest()[:8]}"


def content(value: Any) -> str:
    """Content for a span attribute when capture is on: JSON, trimmed to a sane size."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= CONTENT_LIMIT else text[:CONTENT_LIMIT] + "...[truncated]"


def start_run(tracer: trace.Tracer, agent: str, person: str | None, system_prompt: str,
              question: str | None = None, **attributes: Any):
    """Open the root span of one run. Use as a context manager."""
    span = tracer.start_as_current_span(f"invoke_agent {agent}")
    return _RunSpan(span, agent, person, system_prompt, question, attributes)


class _RunSpan:
    def __init__(self, cm, agent, person, system_prompt, question, attributes):
        self._cm = cm
        self._fields = (agent, person, system_prompt, question, attributes)

    def __enter__(self):
        span = self._cm.__enter__()
        agent, person, system_prompt, question, attributes = self._fields
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        span.set_attribute("gen_ai.agent.name", agent)
        span.set_attribute("aquaflux.agent", agent)
        if person:
            span.set_attribute("aquaflux.person", person)
        span.set_attribute("aquaflux.prompt.version", prompt_version(agent, system_prompt))
        span.set_attribute("aquaflux.content.captured", CAPTURE_CONTENT)
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        if question is not None and CAPTURE_CONTENT:
            span.set_attribute("gen_ai.input.messages", content([{"role": "user", "content": question}]))
        return span

    def __exit__(self, *exc):
        return self._cm.__exit__(*exc)


def record_model_call(span: trace.Span, requested: str, messages: list[dict], response: dict,
                      response_headers: dict | None = None) -> None:
    """Fill a `chat` span from the model gateway's answer."""
    span.set_attribute("gen_ai.operation.name", "chat")
    span.set_attribute("gen_ai.provider.name", "aquaflux-model-gateway")
    span.set_attribute("gen_ai.request.model", requested)
    span.set_attribute("aquaflux.model.requested", requested)
    answered = response.get("model")
    if answered:
        # The model name the gateway reports. Behind a gateway that routes, the gateway answers
        # with the virtual name it was asked for, so the deployment that actually answered is in
        # its response headers: the deployment id, which joins to the gateway's own call log,
        # and the upstream it went to. Artefact three of the eight is these three together.
        span.set_attribute("gen_ai.response.model", answered)
        span.set_attribute("aquaflux.model.answered", answered)
    headers = {k.lower(): v for k, v in (response_headers or {}).items()}
    if headers.get("x-litellm-model-id"):
        span.set_attribute("aquaflux.model.deployment_id", headers["x-litellm-model-id"][:16])
    if headers.get("x-litellm-model-api-base"):
        span.set_attribute("aquaflux.model.api_base", headers["x-litellm-model-api-base"])
    if headers.get("x-litellm-call-id"):
        span.set_attribute("aquaflux.model.gateway_call_id", headers["x-litellm-call-id"])
    usage = response.get("usage") or {}
    if usage.get("prompt_tokens") is not None:
        span.set_attribute("gen_ai.usage.input_tokens", int(usage["prompt_tokens"]))
    if usage.get("completion_tokens") is not None:
        span.set_attribute("gen_ai.usage.output_tokens", int(usage["completion_tokens"]))
    choice = (response.get("choices") or [{}])[0].get("message") or {}
    if CAPTURE_CONTENT:
        span.set_attribute("gen_ai.input.messages", content(messages))
        span.set_attribute("gen_ai.output.messages", content([choice]))
    if choice.get("tool_calls"):
        span.set_attribute("gen_ai.response.finish_reasons", ["tool_calls"])


def record_tool_call(span: trace.Span, name: str, arguments: dict, call_id: str | None) -> None:
    """Fill an `execute_tool` span with what the agent knows before the call returns."""
    span.set_attribute("gen_ai.operation.name", "execute_tool")
    span.set_attribute("gen_ai.tool.name", name)
    span.set_attribute("aquaflux.tool", name)
    if call_id:
        span.set_attribute("gen_ai.tool.call.id", call_id)
    # The hash is always written; the arguments themselves only when content capture is on.
    # The gateway writes the same hash on its decision record, and the two are the join.
    span.set_attribute("aquaflux.arguments_sha256", sha256(arguments))
    if CAPTURE_CONTENT:
        span.set_attribute("gen_ai.tool.call.arguments", content(arguments))


def record_tool_result(span: trace.Span, result: dict, status: int) -> None:
    """Fill an `execute_tool` span with what came back through the gateway."""
    span.set_attribute("aquaflux.gateway.status", status)
    gateway = (result.get("result") or {}).get("_gateway") or {}
    if gateway.get("call_id"):
        span.set_attribute("aquaflux.gateway.call_id", gateway["call_id"])
    error = result.get("error")
    if error:
        span.set_status(trace.StatusCode.ERROR, str(error.get("message"))[:200])
    if CAPTURE_CONTENT:
        span.set_attribute("gen_ai.tool.call.result", content(result.get("result") or error or result))
