from __future__ import annotations

from typing import Iterable


def validate_memory_relevance(query: str, memories: Iterable[object]) -> list[str]:
    q = {t for t in (query or "").lower().split() if len(t) > 2}
    if not q:
        return [str(m) for m in memories or []]
    filtered: list[str] = []
    for m in memories or []:
        s = str(m)
        low = s.lower()
        if any(tok in low for tok in q):
            filtered.append(s)
    return filtered
