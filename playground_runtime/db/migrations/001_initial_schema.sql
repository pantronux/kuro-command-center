PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS playground_sessions (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at_utc TEXT NOT NULL,
    ended_at_utc TEXT,
    runtime_config_hash TEXT NOT NULL,
    notes TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_playground_sessions_created ON playground_sessions(created_at_utc DESC);

CREATE TABLE IF NOT EXISTS runtime_configs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_runtime_configs_session ON runtime_configs(session_id, created_at_utc DESC);

CREATE TABLE IF NOT EXISTS feature_flag_snapshots (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_feature_flag_snapshots_session ON feature_flag_snapshots(session_id, created_at_utc DESC);

CREATE TABLE IF NOT EXISTS provider_metadata (
    id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    endpoint TEXT,
    capability_hash TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_provider_metadata_provider ON provider_metadata(provider_id, created_at_utc DESC);

CREATE TABLE IF NOT EXISTS model_executions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    request_id TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    dataset_version TEXT,
    latency_ms REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    finish_reason TEXT,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_model_executions_session ON model_executions(session_id, created_at_utc DESC);
CREATE INDEX IF NOT EXISTS idx_model_executions_prompt ON model_executions(prompt_sha256, created_at_utc DESC);

CREATE TABLE IF NOT EXISTS raw_evidence (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    response_schema_version TEXT NOT NULL,
    request_id TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    dataset_version TEXT,
    collected_at_utc TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (execution_id) REFERENCES model_executions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_raw_evidence_execution ON raw_evidence(execution_id);
CREATE INDEX IF NOT EXISTS idx_raw_evidence_prompt ON raw_evidence(prompt_sha256);

CREATE TRIGGER IF NOT EXISTS trg_raw_evidence_no_update
BEFORE UPDATE ON raw_evidence
BEGIN
    SELECT RAISE(ABORT, 'raw_evidence is immutable');
END;

CREATE TRIGGER IF NOT EXISTS trg_raw_evidence_no_delete
BEFORE DELETE ON raw_evidence
BEGIN
    SELECT RAISE(ABORT, 'raw_evidence cannot be deleted directly');
END;

CREATE TABLE IF NOT EXISTS canonical_traces (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    dataset_version TEXT,
    collected_at_utc TEXT NOT NULL,
    response_text TEXT,
    finish_reason TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    latency_ms REAL,
    grounding_chunks_json TEXT NOT NULL DEFAULT '[]',
    citation_objects_json TEXT NOT NULL DEFAULT '[]',
    safety_ratings_json TEXT,
    provider_raw_id TEXT NOT NULL,
    forensic_flags_json TEXT NOT NULL DEFAULT '[]',
    normalization_warnings_json TEXT NOT NULL DEFAULT '[]',
    extra_fields_json TEXT NOT NULL DEFAULT '{}',
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (execution_id) REFERENCES model_executions(id) ON DELETE CASCADE,
    FOREIGN KEY (provider_raw_id) REFERENCES raw_evidence(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_canonical_traces_session ON canonical_traces(session_id, created_at_utc DESC);
CREATE INDEX IF NOT EXISTS idx_canonical_traces_prompt ON canonical_traces(prompt_sha256);

CREATE TABLE IF NOT EXISTS telemetry_events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    execution_id TEXT,
    provider_id TEXT,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    timestamp_utc TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (execution_id) REFERENCES model_executions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_telemetry_events_session ON telemetry_events(session_id, timestamp_utc DESC);

CREATE TABLE IF NOT EXISTS hallucination_records (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    execution_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    risk_score REAL NOT NULL,
    flags_json TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (execution_id) REFERENCES model_executions(id) ON DELETE CASCADE,
    FOREIGN KEY (trace_id) REFERENCES canonical_traces(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_hallucination_records_trace ON hallucination_records(trace_id);

CREATE TABLE IF NOT EXISTS epistemic_diffs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    prompt_sha256 TEXT NOT NULL,
    left_trace_id TEXT NOT NULL,
    right_trace_id TEXT NOT NULL,
    divergence_score REAL NOT NULL,
    diff_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (left_trace_id) REFERENCES canonical_traces(id) ON DELETE CASCADE,
    FOREIGN KEY (right_trace_id) REFERENCES canonical_traces(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_epistemic_diffs_prompt ON epistemic_diffs(prompt_sha256, created_at_utc DESC);

CREATE TABLE IF NOT EXISTS ontology_mappings (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    node_label TEXT NOT NULL,
    edges_json TEXT NOT NULL DEFAULT '[]',
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (trace_id) REFERENCES canonical_traces(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ontology_mappings_trace ON ontology_mappings(trace_id);

CREATE TABLE IF NOT EXISTS ontology_graphs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    graph_version TEXT NOT NULL,
    graph_jsonld TEXT,
    graph_rdf_star TEXT,
    alignment_score REAL,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ontology_graphs_session ON ontology_graphs(session_id, created_at_utc DESC);

CREATE TABLE IF NOT EXISTS reproducibility_records (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    execution_id TEXT,
    prompt_sha256 TEXT NOT NULL,
    dataset_version TEXT,
    seed TEXT,
    execution_fingerprint TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (execution_id) REFERENCES model_executions(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_reproducibility_prompt ON reproducibility_records(prompt_sha256);

CREATE TABLE IF NOT EXISTS forensic_reports (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    report_format TEXT NOT NULL,
    report_body TEXT NOT NULL,
    reproducibility_record_id TEXT,
    artifact_path TEXT,
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES playground_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (reproducibility_record_id) REFERENCES reproducibility_records(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_forensic_reports_session ON forensic_reports(session_id, created_at_utc DESC);
