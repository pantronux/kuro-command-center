from __future__ import annotations

from kuro_backend.export_engine.export_models import ExportPayload


class TxtExporter:
    format_name = "txt"
    media_type = "text/plain"
    file_extension = ".txt"

    def export(self, payload: ExportPayload) -> bytes:
        lines = [payload.title]
        for key, value in payload.metadata.items():
            lines.append(f"{key}: {value}")
        lines.append("=" * 40)
        lines.append("")

        for item in payload.transcript:
            role_label = item.get("role_label") or item.get("role", "unknown")
            timestamp = item.get("timestamp", "")
            content = item.get("content", "")
            lines.append(f"[{timestamp}] {role_label}")
            lines.append(content)
            attachments = item.get("attachments") or []
            if attachments:
                lines.append("Attachments: " + ", ".join(str(a) for a in attachments))
            lines.append("")
        return "\n".join(lines).encode("utf-8")
