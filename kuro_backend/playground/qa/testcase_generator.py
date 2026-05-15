"""QA testcase generation module."""

# --- Header Doc ---
# Purpose: Generate test cases from parsed requirements.
# Caller: qa_runtime.py.
# Dependencies: provider_router.py, schema_registry.py.
# Main Functions: generate_testcases().
# Side Effects: Optional provider API call.

from __future__ import annotations

import json
import logging
from typing import Any

from kuro_backend.provider.provider_interface import ProviderRequest
from kuro_backend.provider.provider_router import ProviderRouter
from kuro_backend.runtime.runtime_context import RuntimeContext

logger = logging.getLogger(__name__)


def _strip_fence(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        body = lines[1:]
        if body and body[-1].strip() == "```":
            body = body[:-1]
        return "\n".join(body).strip()
    return cleaned


async def generate_testcases(
    parsed_requirement: dict[str, Any],
    ctx: RuntimeContext,
) -> list[dict[str, Any]]:
    """
    Returns list of testcase dicts.
    Safe fallback: [] when parsing or provider call fails.
    """
    try:
        prompt = (
            "Generate QA test cases in JSON.\n"
            "Return either:\n"
            "1) {\"test_cases\": [...]} or\n"
            "2) a JSON array of test cases.\n"
            "Each testcase fields: id, title, precondition, steps, expected_result, priority, type.\n"
            "Each step fields: step_number, action, expected_result.\n\n"
            f"Parsed requirement:\n{json.dumps(parsed_requirement, ensure_ascii=False)}"
        )
        router = ProviderRouter(ctx.config)
        response = await router.route(
            ProviderRequest(
                prompt=prompt,
                system_prompt="Return strict JSON only. No markdown.",
                temperature=0.2,
                max_tokens=4096,
            )
        )
        raw = _strip_fence(response.content or "")
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            cases = parsed.get("test_cases")
            if isinstance(cases, list):
                return [c for c in cases if isinstance(c, dict)]
            return []
        if isinstance(parsed, list):
            return [c for c in parsed if isinstance(c, dict)]
        return []
    except Exception as exc:
        logger.error("[QA] generate_testcases fallback to []: %s", exc)
        return []
