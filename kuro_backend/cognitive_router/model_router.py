from __future__ import annotations

from typing import Any, Dict

from .routing_policy import select_role, build_router_note
from .openai_model_adapter import verify_claims_with_openai_model_stub


def choose_route(
    *,
    user_input: str,
    confidence_score: float,
    contradiction_score: float,
    openai_model_placeholder_enabled: bool = False,
) -> Dict[str, Any]:
    role = select_role(contradiction_score=contradiction_score, confidence_score=confidence_score)
    payload: Dict[str, Any] = {
        "selected_role": role,
        "router_note": build_router_note(role),
    }
    if openai_model_placeholder_enabled:
        claims = [tok for tok in (user_input or "").split(".") if tok.strip()][:5]
        payload["verification"] = verify_claims_with_openai_model_stub(
            claims, contradiction_score=contradiction_score
        )
    return payload
