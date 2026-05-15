"""QA cucumber conversion module."""

# --- Header Doc ---
# Purpose: Generate Gherkin/Cucumber scenarios from parsed requirements.
# Caller: qa_runtime.py.
# Dependencies: provider_router.py.
# Main Functions: generate_gherkin().
# Side Effects: Optional provider API call.

from __future__ import annotations

import json
import logging
from typing import Any

from kuro_backend.provider.provider_interface import ProviderRequest
from kuro_backend.provider.provider_router import ProviderRouter
from kuro_backend.runtime.runtime_context import RuntimeContext

logger = logging.getLogger(__name__)


async def generate_gherkin(
    parsed_requirement: dict[str, Any],
    ctx: RuntimeContext,
) -> str:
    """
    Returns Gherkin text.
    Safe fallback: empty string when provider call fails.
    """
    try:
        prompt = (
            "Convert the following QA requirement into concise Gherkin.\n"
            "Return plain text only. Must include at least one `Scenario:` block.\n\n"
            f"{json.dumps(parsed_requirement, ensure_ascii=False)}"
        )
        router = ProviderRouter(ctx.config)
        response = await router.route(
            ProviderRequest(
                prompt=prompt,
                system_prompt="Return plain gherkin text. No markdown fences.",
                temperature=0.2,
                max_tokens=2048,
            )
        )
        return (response.content or "").strip()
    except Exception as exc:
        logger.error("[QA] generate_gherkin fallback to empty text: %s", exc)
        return ""
