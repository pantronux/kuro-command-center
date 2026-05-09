"""
Epistemic difference engine.

--- Header Doc ---
Purpose: Compute divergence records between provider traces on same prompt.
Caller: comparative mode pipeline.
Dependencies: itertools, canonical trace schema.
Main Functions: compute_epistemic_diff().
Side Effects: None.
"""

from itertools import combinations
from typing import Dict, Iterable, List

from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def _token_set(text: str) -> set[str]:
    return {t.lower() for t in text.split() if t.strip()}


def compute_epistemic_diff(traces: Iterable[CanonicalInferenceTrace]) -> List[Dict[str, object]]:
    rows = []
    trace_list = list(traces)
    for left, right in combinations(trace_list, 2):
        lt = _token_set(left.response_text or "")
        rt = _token_set(right.response_text or "")
        union = lt | rt
        jaccard = 0.0 if not union else 1.0 - (len(lt & rt) / len(union))
        rows.append(
            {
                "left_trace_id": left.trace_id,
                "right_trace_id": right.trace_id,
                "prompt_sha256": left.prompt_sha256,
                "divergence_score": round(jaccard, 6),
                "left_provider": left.provider_id,
                "right_provider": right.provider_id,
            }
        )
    return rows
