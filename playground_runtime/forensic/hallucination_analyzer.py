"""
Hallucination analyzer.

--- Header Doc ---
Purpose: Detect lightweight hallucination indicators from canonical traces.
Caller: execution pipeline and evaluator.
Dependencies: canonical trace schema.
Main Functions: analyze_trace().
Side Effects: None.
"""

from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def analyze_trace(trace: CanonicalInferenceTrace) -> dict:
    reasons = []
    if not trace.grounding_chunks:
        reasons.append("GROUNDING_ABSENT")
    if trace.finish_reason and trace.finish_reason.lower() not in {"stop", "end_turn", "completed"}:
        reasons.append("FINISH_REASON_ABNORMAL")
    risk_score = min(1.0, 0.5 * len(reasons))
    return {
        "trace_id": trace.trace_id,
        "risk_score": risk_score,
        "flags": reasons,
        "is_hallucination_risk": bool(reasons),
    }
