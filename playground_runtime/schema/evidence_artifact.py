"""
Evidence artifact schema.

--- Header Doc ---
Purpose: Immutable raw evidence metadata + payload contract.
Caller: evidence_store and db layer.
Dependencies: dataclasses, datetime.
Main Functions: EvidenceArtifact.
Side Effects: None.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class EvidenceArtifact:
    provider_id: str
    model_version: str
    response_schema_version: str
    request_id: str
    prompt_sha256: str
    dataset_version: Optional[str]
    collected_at_utc: datetime
    raw_json: Dict[str, Any]
