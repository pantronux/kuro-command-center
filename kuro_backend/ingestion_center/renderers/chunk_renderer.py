from __future__ import annotations

import json
from typing import Any, Dict


def render_chunk_row(chunk: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(chunk)
    row["metadata"] = json.loads(chunk.get("metadata_json") or "{}")
    row["entities"] = json.loads(chunk.get("entity_json") or "[]")
    return row
