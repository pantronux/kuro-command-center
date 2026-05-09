"""
Mode profile schema.

--- Header Doc ---
Purpose: Structured policy profile for playground runtime modes.
Caller: mode resolvers and runtime execution service.
Dependencies: dataclasses, typing.
Main Functions: ModeProfile.
Side Effects: None.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class ModeProfile:
    name: str
    memory_policy: str
    grounding_strictness: str
    hallucination_tolerance: str
    reproducibility_level: str
    telemetry_policy: str
    multi_provider_allowed: bool
    raw_evidence_retention: str
    export_formats_allowed: List[str] = field(default_factory=lambda: ["json"])
