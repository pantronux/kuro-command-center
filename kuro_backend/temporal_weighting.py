from __future__ import annotations

from datetime import datetime
from typing import Iterable


def apply_temporal_decay_weighting(memories: Iterable[object]) -> list[dict[str, object]]:
    weighted: list[dict[str, object]] = []
    now_year = datetime.utcnow().year
    for item in memories or []:
        text = str(item)
        score = 0.5
        if str(now_year) in text:
            score = 0.95
        elif str(now_year - 1) in text:
            score = 0.75
        elif any(k in text.lower() for k in ("today", "latest", "recent", "baru")):
            score = 0.90
        weighted.append({"text": text, "temporal_weight": score})
    return weighted
