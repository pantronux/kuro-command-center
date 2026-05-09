from __future__ import annotations

from typing import Any, Dict, List


def resolve_priorities(goals: List[Dict[str, Any]], user_input: str) -> List[Dict[str, Any]]:
    """Sort goals by strategic relevance and keyword overlap."""
    text = (user_input or "").lower()
    out: List[Dict[str, Any]] = []
    for g in goals:
        score = float(g.get("priority", 0.5))
        title = str(g.get("title", "")).lower()
        if title and any(tok in text for tok in title.split()[:3]):
            score += 0.05
        item = dict(g)
        item["resolved_priority"] = min(1.0, score)
        out.append(item)
    out.sort(key=lambda x: x.get("resolved_priority", 0.0), reverse=True)
    return out
