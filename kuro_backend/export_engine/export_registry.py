from __future__ import annotations

from fastapi import HTTPException

from kuro_backend.export_engine.exporters import (
    CsvExporter,
    DocxExporter,
    JsonExporter,
    MarkdownExporter,
    PdfExporter,
    TxtExporter,
    XlsxExporter,
)

EXPORTER_REGISTRY = {
    "md": MarkdownExporter(),
    "txt": TxtExporter(),
    "json": JsonExporter(),
    "pdf": PdfExporter(),
    "csv": CsvExporter(),
    "xlsx": XlsxExporter(),
    "docx": DocxExporter(),
}


def get_exporter(fmt: str):
    exporter = EXPORTER_REGISTRY.get(fmt)
    if not exporter:
        raise HTTPException(status_code=400, detail=f"Unsupported export format: {fmt}")
    return exporter
