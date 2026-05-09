from __future__ import annotations

import re
from typing import Iterable


_CLAIM_RE = re.compile(
    r"\b\d+(?:\.\d+)?\b|\b(?:ISO\s*\d+|NIST|CVE-\d{4}-\d+)\b|\b[\w\-/]+\.(?:py|md|json|yaml|db|txt|csv|pdf)\b",
    re.IGNORECASE,
)


def extract_claims(text: str) -> list[str]:
    if not text:
        return []
    return [m.group(0) for m in _CLAIM_RE.finditer(text)]


def calculate_evidence_density(text: str, evidence_count: int) -> float:
    claims = max(1, len(extract_claims(text)))
    return min(1.0, float(evidence_count) / float(claims))


def freshness_score(memories: Iterable[object]) -> float:
    items = list(memories or [])
    if not items:
        return 0.0
    fresh_like = 0
    for item in items:
        s = str(item).lower()
        if any(k in s for k in ("2026", "2025", "today", "latest", "recent", "baru")):
            fresh_like += 1
    return fresh_like / max(1, len(items))
