from __future__ import annotations

import os
from typing import Any, Dict, Iterable


def verify_claims_with_openai_model_stub(claims: Iterable[str], *, contradiction_score: float) -> Dict[str, Any]:
    """Deterministic placeholder for OpenAI Model verification (no network call)."""
    claim_list = [str(c).strip() for c in claims or [] if str(c).strip()]
    key_present = bool(os.getenv("OPENAI_API_KEY", "").strip())

    uncertain = []
    contradictions = []
    verified = []
    for c in claim_list:
        if contradiction_score >= 0.45:
            contradictions.append(c)
        elif any(k in c.lower() for k in ("may", "mungkin", "could", "uncertain")):
            uncertain.append(c)
        else:
            verified.append(c)

    return {
        "status": "placeholder",
        "mode": "stub",
        "adapter": "openai_model",
        "api_key_present": key_present,
        "network_call": False,
        "claim_verification": {
            "verified": verified,
            "uncertain": uncertain,
            "contradictions": contradictions,
        },
    }
