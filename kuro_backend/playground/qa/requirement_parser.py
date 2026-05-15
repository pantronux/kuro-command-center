"""QA requirement parser module."""

# --- Header Doc ---
# Purpose: Parse free-text QA requirements into structured requirement metadata.
# Caller: qa_runtime.py.
# Dependencies: provider_router.py, provider_interface.py.
# Main Functions: parse_requirements().
# Side Effects: Optional provider API call.

from __future__ import annotations

import json
import logging
from typing import Any

from kuro_backend.provider.provider_interface import ProviderRequest
from kuro_backend.provider.provider_router import ProviderRouter
from kuro_backend.runtime.runtime_context import RuntimeContext

logger = logging.getLogger(__name__)


def _safe_default(requirement: str = "") -> dict[str, Any]:
    return {
        "main_functionality": requirement.strip(),
        "acceptance_criteria": [],
        "constraints": [],
        "edge_cases": [],
        "raw_requirement": requirement.strip(),
    }


def _extract_json(text: str) -> dict[str, Any] | None:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        body = lines[1:]
        if body and body[-1].strip() == "```":
            body = body[:-1]
        cleaned = "\n".join(body).strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
        return None
    except Exception:
        return None


async def parse_requirements(requirement: str, ctx: RuntimeContext) -> dict[str, Any]:
    """
    Returns parsed requirement dict.
    Safe fallback: always returns default dict, never raises.
    """
    default_payload = _safe_default(requirement)
    req = (requirement or "").strip()
    if not req:
        return default_payload
    try:
        prompt = (
            "You are a QA analyst. Parse the user requirement into JSON with keys:\n"
            "main_functionality (string), acceptance_criteria (array), "
            "constraints (array), edge_cases (array), raw_requirement (string).\n"
            "Return JSON only.\n\n"
            f"Requirement:\n{req}"
        )
        router = ProviderRouter(ctx.config)
        response = await router.route(
            ProviderRequest(
                prompt=prompt,
                system_prompt="Respond in strict JSON only.",
                temperature=0.1,
                max_tokens=1024,
            )
        )
        parsed = _extract_json(response.content or "")
        if isinstance(parsed, dict):
            payload = dict(default_payload)
            payload.update(parsed)
            return payload
        logger.warning("[QA] parse_requirements received non-JSON output")
        return default_payload
    except Exception as exc:
        logger.warning("[QA] parse_requirements fallback: %s", exc)
        return default_payload
