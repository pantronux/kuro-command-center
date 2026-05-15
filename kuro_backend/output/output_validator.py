"""Structured output validation layer."""

# --- Header Doc ---
# Purpose: Validate LLM response payloads against runtime output contract schemas.
# Caller: langgraph_core.response_node, QA playground.
# Dependencies: schema_registry.py, intelligence_db.py, pydantic.
# Main Functions: validate_output().
# Side Effects: Writes validation audit events.

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from kuro_backend import intelligence_db
from kuro_backend.output.schema_registry import SchemaRegistry

logger = logging.getLogger(__name__)


def _strip_markdown_fence(raw_text: str) -> str:
    cleaned = (raw_text or "").strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.split("\n")
    if not lines:
        return cleaned
    # Drop first line (``` or ```json), and trailing ``` if present.
    body = lines[1:]
    if body and body[-1].strip() == "```":
        body = body[:-1]
    return "\n".join(body).strip()


def validate_output(raw_text: str, contract_id: str) -> tuple[bool, Any, str | None]:
    """
    Parse and validate raw JSON text against contract schema.
    Returns (is_valid, model_instance_or_none, error_message_or_none).
    """
    schema_class = SchemaRegistry.get_schema(contract_id)
    cleaned = _strip_markdown_fence(raw_text)
    try:
        data = json.loads(cleaned)
        model = schema_class(**data)
        intelligence_db.add_audit_trail(
            action="output_validated",
            details=f"contract={contract_id} status=valid",
        )
        return True, model, None
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        error_msg = str(exc)[:300]
        intelligence_db.add_audit_trail(
            action="output_validated",
            details=f"contract={contract_id} status=invalid error={error_msg}",
        )
        return False, None, error_msg
