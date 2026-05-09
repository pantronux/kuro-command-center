from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class ProvenanceRecord:
    claim_text: str
    source_type: str
    evidence_refs: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds"))


def build_record(claim_text: str, source_type: str, evidence_refs: list[str] | None = None) -> ProvenanceRecord:
    return ProvenanceRecord(
        claim_text=claim_text.strip(),
        source_type=source_type.strip() or "unknown",
        evidence_refs=evidence_refs or [],
    )
