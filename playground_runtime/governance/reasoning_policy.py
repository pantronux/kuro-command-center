"""
Reasoning exposure policy.

--- Header Doc ---
Purpose: Enforce no-hidden-reasoning projection into canonical traces.
Caller: normalization mappers.
Dependencies: typing.
Main Functions: split_hidden_reasoning_fields().
Side Effects: None.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Tuple

# Provider-visible metadata is allowed. Hidden-CoT style fields are stripped
# from the canonical projection and surfaced as normalization warnings.
HIDDEN_REASONING_FIELDS = {
    "reasoning",
    "reasoning_content",
    "chain_of_thought",
    "cot",
    "thought_process",
    "internal_reasoning",
    "deliberation",
    "scratchpad",
    "_reasoning",
    "__cot__",
    "_thought",
}


def split_hidden_reasoning_fields(raw_record: Dict[str, Any]) -> Tuple[Dict[str, Any], list[str]]:
    sanitized = dict(raw_record)
    removed = []
    for key in list(sanitized.keys()):
        if key.lower() in HIDDEN_REASONING_FIELDS:
            removed.append(key)
            sanitized.pop(key, None)
    warnings = []
    if removed:
        warnings.append("HIDDEN_REASONING_FIELDS_STRIPPED:" + ",".join(sorted(removed)))
    return sanitized, warnings


def _strip_hidden_fields_in_place(
    obj: Dict[str, Any],
    warnings: list[str],
    path_prefix: str,
    depth: int,
    max_depth: int,
) -> None:
    for key in list(obj.keys()):
        value = obj[key]
        key_l = key.lower()
        key_path = f"{path_prefix}.{key}" if path_prefix else key
        if key_l in HIDDEN_REASONING_FIELDS:
            obj.pop(key, None)
            warnings.append(f"HIDDEN_REASONING_FIELDS_STRIPPED_NESTED:{key_path}")
            continue
        if depth >= max_depth:
            continue
        if isinstance(value, dict):
            _strip_hidden_fields_in_place(value, warnings, key_path, depth + 1, max_depth)
            continue
        if isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, dict):
                    list_path = f"{key_path}[{idx}]"
                    _strip_hidden_fields_in_place(item, warnings, list_path, depth + 1, max_depth)


def split_hidden_reasoning_fields_deep(
    raw_record: Dict[str, Any],
    _depth: int = 0,
    _max_depth: int = 3,
) -> Tuple[Dict[str, Any], list[str]]:
    """
    Recursively strip hidden reasoning fields up to max depth.
    Entry point always performs deep copy to preserve raw evidence immutability.
    """
    sanitized = deepcopy(raw_record)
    warnings: list[str] = []
    _strip_hidden_fields_in_place(
        obj=sanitized,
        warnings=warnings,
        path_prefix="",
        depth=_depth,
        max_depth=_max_depth,
    )
    return sanitized, warnings
