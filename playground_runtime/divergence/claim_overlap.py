"""Claim overlap scoring."""

from __future__ import annotations


def claim_overlap(left_text: str, right_text: str) -> float:
    left_claims = {s.strip().lower() for s in left_text.split(".") if s.strip()}
    right_claims = {s.strip().lower() for s in right_text.split(".") if s.strip()}
    union = left_claims | right_claims
    if not union:
        return 0.0
    return round(len(left_claims & right_claims) / len(union), 6)
