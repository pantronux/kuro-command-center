"""
Trace indexer.

--- Header Doc ---
Purpose: Build quick lookup indexes for canonical traces by prompt and provider.
Caller: forensic reporting pipeline.
Dependencies: typing.
Main Functions: build_trace_index().
Side Effects: None.
"""

from collections import defaultdict
from typing import Dict, Iterable, List

from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


def build_trace_index(traces: Iterable[CanonicalInferenceTrace]) -> Dict[str, List[CanonicalInferenceTrace]]:
    index: Dict[str, List[CanonicalInferenceTrace]] = defaultdict(list)
    for trace in traces:
        key = f"{trace.prompt_sha256}:{trace.provider_id}"
        index[key].append(trace)
    return dict(index)
