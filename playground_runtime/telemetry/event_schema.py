"""
Telemetry event schema.

--- Header Doc ---
Purpose: Define normalized telemetry event payload structure.
Caller: telemetry collector and persistence layer.
Dependencies: dataclasses.
Main Functions: TelemetryEvent.
Side Effects: None.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional


@dataclass
class TelemetryEvent:
    event_type: str
    session_id: str
    execution_id: Optional[str]
    provider_id: Optional[str]
    timestamp_utc: datetime
    payload: Dict[str, object] = field(default_factory=dict)
