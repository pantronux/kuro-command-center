"""Structured output repair layer with safe fallback contract."""

# --- Header Doc ---
# Purpose: Attempt to repair invalid structured output with a second LLM pass.
# Caller: langgraph_core.response_node after validation failure.
# Dependencies: output_validator.py, schema_registry.py, llm_utils.py.
# Main Functions: attempt_repair().
# Side Effects: Optional additional LLM call.

from __future__ import annotations

import json
import logging
from typing import Any

from kuro_backend.output.output_validator import validate_output
from kuro_backend.output.schema_registry import SchemaRegistry

logger = logging.getLogger(__name__)


async def attempt_repair(
    raw_text: str,
    contract_id: str,
    error_message: str,
    trace_id: str = "",
) -> tuple[bool, Any, str | None]:
    """
    Attempt schema-repair using the configured LLM helper.
    Never raises; always returns a safe tuple.
    """
    try:
        schema_class = SchemaRegistry.get_schema(contract_id)
        schema_json = json.dumps(schema_class.model_json_schema(), indent=2)
        repair_prompt = (
            "The following output failed schema validation.\n"
            f"Error: {error_message}\n\n"
            f"Required schema:\n{schema_json}\n\n"
            f"Invalid output:\n{raw_text}\n\n"
            "Return ONLY a corrected JSON object matching the schema. "
            "No explanation, no markdown backticks."
        )
        repaired_text = await _call_repair_llm(repair_prompt)
        if repaired_text is None:
            return False, None, "Repair LLM unavailable"
        return validate_output(repaired_text, contract_id, trace_id=trace_id)
    except Exception as exc:
        logger.error("attempt_repair failed contract=%s: %s", contract_id, exc)
        return False, None, f"Repair exception: {str(exc)[:200]}"


async def _call_repair_llm(prompt: str) -> str | None:
    """
    Call existing LLM helper if available. Returns None on failure/unavailable.
    """
    try:
        from kuro_backend import llm_utils

        if hasattr(llm_utils, "generate_text"):
            return await llm_utils.generate_text(
                prompt,
                temperature=0.1,
                max_tokens=2000,
            )
        logger.warning("No llm_utils.generate_text found; structured repair unavailable")
        return None
    except Exception as exc:
        logger.error("_call_repair_llm failed: %s", exc)
        return None
