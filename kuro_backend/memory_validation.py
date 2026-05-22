from __future__ import annotations

from typing import Iterable


def validate_memory_relevance(query: str, memories: Iterable[object]) -> list[object]:
    q = {t for t in (query or "").lower().split() if len(t) > 2}
    if not q:
        return list(memories or [])
    filtered: list[object] = []
    for m in memories or []:
        s = str(m)
        low = s.lower()
        if any(tok in low for tok in q):
            filtered.append(m)
    return filtered
