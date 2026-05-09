"""
Base mapper.

--- Header Doc ---
Purpose: Define provider mapper interface and shared warnings/flags behavior.
Caller: normalization registry.
Dependencies: abc, canonical_trace.
Main Functions: BaseMapper.map_to_canonical().
Side Effects: None.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Tuple

from playground_runtime.schema.canonical_trace import CanonicalInferenceTrace


class BaseMapper(ABC):
    schema_version: str = "1.0.0"

    @abstractmethod
    def map_to_canonical(
        self,
        session_id: str,
        execution_id: str,
        provider_raw_id: str,
        raw_record: Dict[str, Any],
    ) -> CanonicalInferenceTrace:
        raise NotImplementedError

    def collect_unknown_fields(self, raw_record: Dict[str, Any], known_fields: set[str]) -> Tuple[Dict[str, Any], list[str]]:
        extras = {k: v for k, v in raw_record.items() if k not in known_fields}
        warnings = []
        if extras:
            warnings.append(f"SCHEMA_DRIFT:{','.join(sorted(extras.keys()))}")
        return extras, warnings
