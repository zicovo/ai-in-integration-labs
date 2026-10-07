"""The gateway's spans, and the trace ids its decision records carry.

One span per `tools/call`, a child of whatever `traceparent` the caller sent, exported to the
collector over OTLP/HTTP. The span says that a call went through this door and which tool it
named. It does not say what was decided: the decision, the rule and its version go to the
gateway's own decision log, `GET /logs` and the file behind it, because a gateway wants its
decisions durable even when the telemetry pipeline is down. Whether that file reaches the
collector is reconstruct-one-transaction's question, and the answer is in the collector's configuration and not here.

The exporter probes for the collector before every batch and drops the batch quietly when
nothing is listening, so the `tools` profile runs unchanged without the `telemetry` one.
"""

from __future__ import annotations

import logging
import os
import socket
import urllib.parse
from typing import Sequence

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

COLLECTOR = os.environ.get("AQUAFLUX_OTLP", "")


class _QuietExporter(SpanExporter):
    """Export when the collector answers a TCP probe; otherwise drop, silently and at once."""

    def __init__(self, endpoint: str) -> None:
        self._inner = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", timeout=3)
        url = urllib.parse.urlparse(endpoint)
        self._host, self._port = url.hostname, url.port or 4318

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            with socket.create_connection((self._host, self._port), timeout=0.3):
                pass
        except OSError:
            return SpanExportResult.FAILURE
        try:
            return self._inner.export(spans)
        except Exception:  # noqa: BLE001
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def setup() -> trace.Tracer:
    provider = TracerProvider(resource=Resource.create({
        "service.name": "tool-gateway",
        "service.namespace": "aquaflux",
        "deployment.environment.name": "lab",
    }))
    if COLLECTOR:
        logging.getLogger("opentelemetry").setLevel(logging.CRITICAL)
        provider.add_span_processor(BatchSpanProcessor(_QuietExporter(COLLECTOR),
                                                       export_timeout_millis=3000))
    trace.set_tracer_provider(provider)
    return trace.get_tracer("tool-gateway")


def parent(headers) -> trace.Context:
    """The caller's trace context, read from `traceparent` the W3C way."""
    return extract({k.lower(): v for k, v in headers.items()})


def ids() -> tuple[str | None, str | None]:
    """The current trace id and span id as hex, or (None, None) outside a span."""
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None, None
    return format(context.trace_id, "032x"), format(context.span_id, "016x")
