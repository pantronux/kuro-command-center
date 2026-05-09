"""
Schema package.

--- Header Doc ---
Purpose: Canonical trace and normalization contracts.
Caller: mappers, execution pipeline, report builder.
Dependencies: schema modules.
Main Functions: CanonicalInferenceTrace.
Side Effects: None.
"""

from .canonical_trace import CanonicalInferenceTrace

__all__ = ["CanonicalInferenceTrace"]
