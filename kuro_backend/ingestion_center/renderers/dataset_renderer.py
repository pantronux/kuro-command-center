from __future__ import annotations

import json
from typing import Any, Dict


def render_dataset_row(dataset: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(dataset)
    row["tags"] = json.loads(dataset.get("tags_json") or "[]")
    row["metadata"] = json.loads(dataset.get("metadata_json") or "{}")
    return row
