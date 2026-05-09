"""
Evaluation package.

--- Header Doc ---
Purpose: Evaluate forensic quality metrics and build reports.
Caller: runtime report generation.
Dependencies: metrics modules, report builder.
Main Functions: evaluate_traces().
Side Effects: None.
"""

from .evaluator import evaluate_traces

__all__ = ["evaluate_traces"]
