"""
KPR telemetry package.

--- Header Doc ---
Purpose: Emit and store KPR telemetry events with isolated OTel namespace.
Caller: execution pipeline.
Dependencies: event schema and OTel bridge.
Main Functions: TelemetryEvent, PlaygroundOtelBridge.
Side Effects: None at package import.
"""

from .event_schema import TelemetryEvent
from .otel_bridge import PlaygroundOtelBridge

__all__ = ["TelemetryEvent", "PlaygroundOtelBridge"]
