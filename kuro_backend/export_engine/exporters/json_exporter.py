from __future__ import annotations

import json

from kuro_backend.export_engine.export_models import ExportPayload


class JsonExporter:
    format_name = "json"
    media_type = "application/json"
    file_extension = ".json"

    def export(self, payload: ExportPayload) -> bytes:
        return json.dumps(payload.model_dump(), ensure_ascii=False, indent=2).encode("utf-8")
