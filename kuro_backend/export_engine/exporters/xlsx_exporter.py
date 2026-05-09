from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font

from kuro_backend.export_engine.export_models import ExportPayload


class XlsxExporter:
    format_name = "xlsx"
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    file_extension = ".xlsx"

    def export(self, payload: ExportPayload) -> bytes:
        workbook = Workbook()
        meta_sheet = workbook.active
        meta_sheet.title = "Metadata"
        meta_sheet.append(["Field", "Value"])
        for cell in meta_sheet[1]:
            cell.font = Font(bold=True)
        for key, value in payload.metadata.items():
            meta_sheet.append([key, value])

        transcript_sheet = workbook.create_sheet("Transcript")
        headers = [
            "id",
            "timestamp",
            "role",
            "persona",
            "role_label",
            "content",
            "attachments",
            "is_edited",
            "is_bookmarked",
        ]
        transcript_sheet.append(headers)
        for cell in transcript_sheet[1]:
            cell.font = Font(bold=True)

        for item in payload.transcript:
            transcript_sheet.append([
                item.get("id", ""),
                item.get("timestamp", ""),
                item.get("role", ""),
                item.get("persona", ""),
                item.get("role_label", ""),
                item.get("content", ""),
                "\n".join(item.get("attachments") or []),
                item.get("is_edited", 0),
                item.get("is_bookmarked", 0),
            ])

        buffer = BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()
