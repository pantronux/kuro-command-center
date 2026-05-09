PRAGMA foreign_keys = ON;

ALTER TABLE playground_sessions ADD COLUMN session_integrity_hash TEXT;
ALTER TABLE playground_sessions ADD COLUMN session_integrity_status TEXT;
ALTER TABLE playground_sessions ADD COLUMN session_integrity_verified_at TEXT;

CREATE INDEX IF NOT EXISTS idx_playground_sessions_integrity_status ON playground_sessions(session_integrity_status, created_at_utc DESC);
CREATE INDEX IF NOT EXISTS idx_chain_of_custody_action ON chain_of_custody(action_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_artifact_integrity_type_status ON artifact_integrity(artifact_type, verification_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_snapshots_status ON evidence_snapshots(verification_status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_transformation_manifest_source_target ON transformation_manifest(source_artifact_id, target_artifact_id, created_at DESC);
