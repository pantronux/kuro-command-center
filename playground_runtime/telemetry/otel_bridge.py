"""
OTel bridge for playground.

--- Header Doc ---
Purpose: Build isolated OTel tracer for project_name='kuro-playground'.
Caller: telemetry collector.
Dependencies: opentelemetry-sdk.
Main Functions: PlaygroundOtelBridge.start_span().
Side Effects: Sends spans to configured OTLP endpoint.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Dict, Generator, Optional

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter


class PlaygroundOtelBridge:
    def __init__(self, endpoint: str, project_name: str, service_name: str):
        resource = Resource(attributes={"project_name": project_name, "service.name": service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        self._tracer = provider.get_tracer("kuro-playground")

    @contextmanager
    def start_span(self, name: str, attributes: Optional[Dict[str, object]] = None) -> Generator:
        attrs = {k: str(v) for k, v in (attributes or {}).items()}
        with self._tracer.start_as_current_span(name, attributes=attrs) as span:
            yield span
