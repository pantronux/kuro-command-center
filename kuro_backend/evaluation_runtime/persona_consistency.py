from __future__ import annotations

from typing import Dict


def compute_persona_consistency(*, persona_mode: str, response_text: str) -> Dict[str, float]:
    base = 0.9 if persona_mode else 0.6
    drift = 0.2 if "i am not sure who i am" in (response_text or "").lower() else 0.0
    return {"persona_consistency": max(0.0, min(1.0, base - drift))}
