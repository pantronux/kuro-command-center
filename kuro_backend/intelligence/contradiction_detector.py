from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ContradictionResult:
    score: float
    details: list[str]


_NEGATION_RE = re.compile(r"\b(?:not|never|no longer|bukan|tidak|bukan lagi)\b", re.IGNORECASE)


def detect_contradictions(user_input: str, evidence_items: Iterable[object]) -> ContradictionResult:
    details: list[str] = []
    base = (user_input or "").strip().lower()
    if not base:
        return ContradictionResult(score=0.0, details=[])

    evidence = [str(x).strip().lower() for x in (evidence_items or []) if str(x).strip()]
    if not evidence:
        return ContradictionResult(score=0.0, details=[])

    input_neg = bool(_NEGATION_RE.search(base))
    conflicts = 0
    for ev in evidence[:12]:
        ev_neg = bool(_NEGATION_RE.search(ev))
        if input_neg != ev_neg and any(tok in ev for tok in base.split()[:6]):
            conflicts += 1
            details.append(f"Potential contradiction with evidence: {ev[:120]}")

    score = min(1.0, conflicts / max(1, min(6, len(evidence))))
    return ContradictionResult(score=score, details=details)
