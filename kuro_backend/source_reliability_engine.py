from __future__ import annotations

from typing import Any, Dict, List


def score_sources(sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(sources or [])
    if not rows:
        return {
            "credibility_score": 0.0,
            "citation_density": 0.0,
            "freshness": 0.0,
            "peer_review_status": "unknown",
            "contradiction_rate": 0.0,
            "retrieval_trustworthiness": 0.0,
        }

    citation_sum = sum(float(r.get("cited_by", 0) or 0) for r in rows)
    scholar_count = sum(1 for r in rows if str(r.get("source_type", "")).lower() == "scholar")
    credibility = min(1.0, 0.3 + (scholar_count * 0.15) + min(0.35, citation_sum / 200.0))
    freshness = 0.8 if any(r.get("date") for r in rows) else 0.6
    contradiction_rate = 0.1

    return {
        "credibility_score": credibility,
        "citation_density": min(1.0, citation_sum / max(1.0, len(rows) * 50.0)),
        "freshness": freshness,
        "peer_review_status": "mixed" if scholar_count and scholar_count < len(rows) else ("peer_reviewed" if scholar_count else "unknown"),
        "contradiction_rate": contradiction_rate,
        "retrieval_trustworthiness": max(0.0, min(1.0, (credibility * 0.7) + (freshness * 0.3) - (contradiction_rate * 0.2))),
    }
