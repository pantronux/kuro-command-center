"""
Canonical inference trace schema.

--- Header Doc ---
Purpose: Unified provider-visible forensic trace record.
Caller: mappers, db persistence, reports.
Dependencies: dataclasses, datetime, typing.
Main Functions: CanonicalInferenceTrace.
Side Effects: None.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class CanonicalInferenceTrace:
    trace_id: str
    session_id: str
    execution_id: str
    provider_id: str
    model_id: str
    model_version: str
    schema_version: str
    prompt_sha256: str
    dataset_version: Optional[str]
    collected_at_utc: datetime
    response_text: Optional[str]
    finish_reason: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]
    latency_ms: Optional[float]
    grounding_chunks: List[dict] = field(default_factory=list)
    citation_objects: List[dict] = field(default_factory=list)
    safety_ratings: Optional[dict] = None
    provider_raw_id: str = ""
    forensic_flags: List[str] = field(default_factory=list)
    normalization_warnings: List[str] = field(default_factory=list)
    extra_fields: Dict[str, object] = field(default_factory=dict)
