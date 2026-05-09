"""
Report exporter.

--- Header Doc ---
Purpose: Dispatch forensic report payload to json/rdf/csv renderers.
Caller: api routes and report pipeline.
Dependencies: format exporters.
Main Functions: ReportExporter.export().
Side Effects: Optional file writes.
"""

from __future__ import annotations

from pathlib import Path

from playground_runtime.export.formats.csv_exporter import export_csv
from playground_runtime.export.formats.json_exporter import export_json
from playground_runtime.export.formats.rdf_exporter import export_rdf


class ReportExporter:
    def export(self, report: dict, fmt: str, output_path: str | None = None) -> str:
        fmt = fmt.lower().strip()
        if fmt == "json":
            rendered = export_json(report)
        elif fmt == "rdf":
            rendered = export_rdf(report)
        elif fmt == "csv":
            rendered = export_csv(report)
        else:
            raise ValueError(f"Unsupported export format '{fmt}'")

        if output_path:
            Path(output_path).write_text(rendered, encoding="utf-8")
        return rendered
