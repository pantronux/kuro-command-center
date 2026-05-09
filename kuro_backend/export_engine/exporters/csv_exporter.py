from __future__ import annotations

import csv
from io import StringIO

from kuro_backend.export_engine.export_models import ExportPayload


class CsvExporter:
    format_name = "csv"
    media_type = "text/csv"
    file_extension = ".csv"

    def export(self, payload: ExportPayload) -> bytes:
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id",
            "timestamp",
            "role",
            "persona",
            "role_label",
            "content",
            "attachments",
            "is_edited",
            "is_bookmarked",
        ])
        for item in payload.transcript:
            writer.writerow([
                item.get("id", ""),
                item.get("timestamp", ""),
                item.get("role", ""),
                item.get("persona", ""),
                item.get("role_label", ""),
                item.get("content", ""),
                "; ".join(item.get("attachments") or []),
                item.get("is_edited", 0),
                item.get("is_bookmarked", 0),
            ])
        return output.getvalue().encode("utf-8")
