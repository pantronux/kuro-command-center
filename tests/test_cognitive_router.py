from __future__ import annotations

from kuro_backend.cognitive_router.model_router import choose_route
from kuro_backend.cognitive_router.routing_policy import select_role
from kuro_backend.cognitive_router.fallback_strategy import safe_fallback


def test_cognitive_router_selects_validation_role_on_low_confidence() -> None:
    role = select_role(contradiction_score=0.20, confidence_score=0.50)
    assert role == "openai_model_placeholder"


def test_cognitive_router_returns_router_note_and_optional_verification() -> None:
    payload_off = choose_route(
        user_input="uji routing model",
        confidence_score=0.82,
        contradiction_score=0.10,
        openai_model_placeholder_enabled=False,
    )
    assert "selected_role" in payload_off
    assert "router_note" in payload_off
    assert "verification" not in payload_off

    payload_on = choose_route(
        user_input="claim A. claim B.",
        confidence_score=0.82,
        contradiction_score=0.10,
        openai_model_placeholder_enabled=True,
    )
    assert payload_on["verification"]["status"] == "placeholder"
    assert payload_on["verification"]["network_call"] is False


def test_cognitive_router_fallback_shape() -> None:
    fb = safe_fallback("test")
    assert fb["selected_role"] == "fallback"
    assert fb["status"] == "degraded"
