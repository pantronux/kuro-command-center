from __future__ import annotations

from typing import Protocol

from kuro_backend.export_engine.export_models import ExportPayload


class BaseExporter(Protocol):
    format_name: str
    media_type: str
    file_extension: str

    def export(self, payload: ExportPayload) -> bytes:
        ...
