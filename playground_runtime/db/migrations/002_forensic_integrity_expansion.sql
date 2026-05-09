PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS artifact_integrity (
    id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    provider TEXT,
    schema_version TEXT,
    acquisition_session TEXT NOT NULL,
    verification_status TEXT NOT NULL DEFAULT 'unverified'
);
CREATE INDEX IF NOT EXISTS idx_artifact_integrity_session ON artifact_integrity(acquisition_session, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_artifact_integrity_artifact ON artifact_integrity(artifact_id, artifact_type);

CREATE TABLE IF NOT EXISTS transformation_manifest (
    id TEXT PRIMARY KEY,
    manifest_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    source_artifact_id TEXT NOT NULL,
    target_artifact_id TEXT NOT NULL,
    source_hash TEXT NOT NULL,
    target_hash TEXT NOT NULL,
    transformer_version TEXT NOT NULL,
    mapping_confidence REAL NOT NULL,
    semantic_loss_flags_json TEXT NOT NULL DEFAULT '[]',
    schema_drift_flags_json TEXT NOT NULL DEFAULT '[]',
    canonical_candidates_json TEXT NOT NULL DEFAULT '[]',
    provider_alias_mapping_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (execution_id) REFERENCES model_executions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_transformation_manifest_execution ON transformation_manifest(session_id, execution_id, created_at DESC);

CREATE TABLE IF NOT EXISTS chain_of_custody (
    id TEXT PRIMARY KEY,
    custody_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    previous_hash TEXT,
    new_hash TEXT,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_chain_of_custody_artifact ON chain_of_custody(artifact_id, created_at DESC);

CREATE TABLE IF NOT EXISTS evidence_snapshots (
    id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    execution_id TEXT,
    snapshot_hash TEXT NOT NULL,
    snapshot_bundle_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    verification_status TEXT NOT NULL DEFAULT 'unverified',
    verified_at TEXT,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (execution_id) REFERENCES model_executions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_snapshots_session ON evidence_snapshots(session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS provider_capabilities (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    capability_json TEXT NOT NULL,
    capability_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_provider_capabilities_session ON provider_capabilities(session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS semantic_divergence (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    left_trace_id TEXT NOT NULL,
    right_trace_id TEXT NOT NULL,
    semantic_overlap REAL NOT NULL,
    claim_overlap REAL NOT NULL,
    grounding_delta REAL NOT NULL,
    citation_density_delta REAL NOT NULL,
    hallucination_delta REAL NOT NULL,
    contradiction_flags_json TEXT NOT NULL DEFAULT '[]',
    provider_variance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (left_trace_id) REFERENCES canonical_traces(id) ON DELETE CASCADE,
    FOREIGN KEY (right_trace_id) REFERENCES canonical_traces(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_semantic_divergence_session ON semantic_divergence(session_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ontology_entities (
    id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    label TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (graph_id) REFERENCES ontology_graphs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ontology_entities_graph ON ontology_entities(graph_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ontology_relationships (
    id TEXT PRIMARY KEY,
    graph_id TEXT NOT NULL,
    source_entity_id TEXT NOT NULL,
    target_entity_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    weight REAL NOT NULL,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (graph_id) REFERENCES ontology_graphs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ontology_relationships_graph ON ontology_relationships(graph_id, created_at DESC);

CREATE TABLE IF NOT EXISTS dataset_executions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    dataset_hash TEXT NOT NULL,
    dataset_version TEXT,
    provider_set_json TEXT NOT NULL,
    execution_config_hash TEXT NOT NULL,
    item_count INTEGER NOT NULL,
    status TEXT NOT NULL,
    result_summary_json TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_dataset_executions_session ON dataset_executions(session_id, created_at DESC);
