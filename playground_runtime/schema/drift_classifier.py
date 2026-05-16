"""Drift classification helpers for canonical projection quality."""

from __future__ import annotations

from typing import Iterable


def has_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True


def classify_projection_drift(
    *,
    canonical_fields: dict[str, object],
    source_candidates: dict[str, Iterable[object]],
) -> list[str]:
    """
    Classify whether missing canonical fields indicate mapping drift or schema drift.

    - MAPPING_DRIFT: source value exists but canonical value is missing.
    - SCHEMA_DRIFT: canonical value missing and no source candidate exists.
    """
    warnings: list[str] = []
    for field, candidates in source_candidates.items():
        canonical_missing = not has_value(canonical_fields.get(field))
        if not canonical_missing:
            continue
        source_present = any(has_value(value) for value in candidates)
        if source_present:
            warnings.append(f"MAPPING_DRIFT:{field}")
        else:
            warnings.append(f"SCHEMA_DRIFT:{field}")
    return warnings


def classify_provider_field_preservation(
    *,
    provider_fields: dict[str, object],
    preserved_fields: dict[str, object],
) -> list[str]:
    """
    Flag provider-specific fields that exist but were not preserved in metadata.
    """
    unresolved: list[str] = []
    for field, value in provider_fields.items():
        if not has_value(value):
            continue
        if not has_value(preserved_fields.get(field)):
            unresolved.append(field)
    if not unresolved:
        return []
    return [f"UNMAPPED_PROVIDER_FIELDS:{','.join(sorted(unresolved))}"]
