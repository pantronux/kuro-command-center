from __future__ import annotations

from typing import Iterable

from kuro_backend.intelligence.contradiction_detector import detect_contradictions


def contradiction_score(query: str, memories: Iterable[object]) -> float:
    return detect_contradictions(query, memories).score
