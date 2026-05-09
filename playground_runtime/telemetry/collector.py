"""
Telemetry collector.

--- Header Doc ---
Purpose: Emit OTel spans and persist telemetry events in KPR DB.
Caller: runtime service.
Dependencies: event_schema, otel_bridge, playground_db.
Main Functions: emit().
Side Effects: Writes telemetry_events table and OTLP spans.
"""

from __future__ import annotations

from datetime import datetime, timezone

from playground_runtime.db.playground_db import PlaygroundDB
from playground_runtime.telemetry.event_schema import TelemetryEvent
from playground_runtime.telemetry.otel_bridge import PlaygroundOtelBridge


class TelemetryCollector:
    def __init__(self, db: PlaygroundDB, otel: PlaygroundOtelBridge):
        self.db = db
        self.otel = otel

    def emit(self, event_type: str, session_id: str, execution_id: str | None, provider_id: str | None, payload: dict) -> str:
        event = TelemetryEvent(
            event_type=event_type,
            session_id=session_id,
            execution_id=execution_id,
            provider_id=provider_id,
            timestamp_utc=datetime.now(timezone.utc),
            payload=payload,
        )
        with self.otel.start_span(
            f"kpr.{event_type}",
            attributes={
                "kpr.session_id": session_id,
                "kpr.execution_id": execution_id or "",
                "kpr.provider_id": provider_id or "",
            },
        ):
            return self.db.insert_telemetry_event(event)
