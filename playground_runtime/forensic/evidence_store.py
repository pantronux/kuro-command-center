"""
Evidence store helper.

--- Header Doc ---
Purpose: Persist immutable raw provider evidence before normalization.
Caller: runtime execution service.
Dependencies: db layer, evidence_artifact schema.
Main Functions: persist_raw_evidence().
Side Effects: Inserts into raw_evidence table.
"""

from playground_runtime.db.playground_db import PlaygroundDB
from playground_runtime.schema.evidence_artifact import EvidenceArtifact


class EvidenceStore:
    def __init__(self, db: PlaygroundDB):
        self.db = db

    def persist_raw_evidence(self, session_id: str, execution_id: str, artifact: EvidenceArtifact) -> str:
        return self.db.insert_raw_evidence(session_id=session_id, execution_id=execution_id, artifact=artifact)
