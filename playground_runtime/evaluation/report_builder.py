"""
Report builder.

--- Header Doc ---
Purpose: Assemble forensic report payload from session artifacts.
Caller: export/report exporter.
Dependencies: evaluator, epistemic diff, ontology exporter.
Main Functions: build_report().
Side Effects: None.
"""

from __future__ import annotations

from hashlib import sha256
from typing import List

from playground_runtime.evaluation.evaluator import evaluate_traces
from playground_runtime.forensic.epistemic_diff import compute_epistemic_diff
from playground_runtime.ontology.concept_graph import ConceptGraph
from playground_runtime.ontology.graph_exporter import export_jsonld
from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def build_report(
    session_id: str,
    mode: str,
    traces: List[CanonicalInferenceTrace],
    runtime_config: dict,
    providers: list[dict],
    raw_evidence_rows: list[dict],
    ontology_graph: ConceptGraph | None,
) -> dict:
    eval_summary = evaluate_traces(traces)
    diffs = compute_epistemic_diff(traces)
    raw_hashes = [sha256(r["raw_json"].encode("utf-8")).hexdigest() for r in raw_evidence_rows]
    return {
        "session_metadata": {
            "session_id": session_id,
            "mode": mode,
            "runtime_config_hash": sha256(str(runtime_config).encode("utf-8")).hexdigest(),
        },
        "provider_manifest": providers,
        "execution_summary": [
            {
                "execution_id": t.execution_id,
                "provider_id": t.provider_id,
                "latency_ms": t.latency_ms,
                "token_usage": {
                    "input": t.input_tokens,
                    "output": t.output_tokens,
                    "total": t.total_tokens,
                },
                "finish_reason": t.finish_reason,
                "forensic_flags": t.forensic_flags,
            }
            for t in traces
        ],
        "canonical_trace_index": [t.trace_id for t in traces],
        "epistemic_diff_summary": diffs,
        "ontology_graph": export_jsonld(ontology_graph) if ontology_graph else None,
        "reproducibility_record": runtime_config,
        "evidence_integrity": raw_hashes,
        "evaluation": eval_summary,
    }
