"""
Forensic package.

--- Header Doc ---
Purpose: Forensic utilities for evidence storage, indexing, hallucination, and epistemic diff.
Caller: runtime pipeline and evaluation subsystem.
Dependencies: forensic modules.
Main Functions: EvidenceStore, compute_epistemic_diff.
Side Effects: DB writes via runtime service.
"""

from .evidence_store import EvidenceStore
from .epistemic_diff import compute_epistemic_diff

__all__ = ["EvidenceStore", "compute_epistemic_diff"]
