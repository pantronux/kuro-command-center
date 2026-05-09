from __future__ import annotations

from kuro_backend.export_engine.export_models import ExportPayload


class MarkdownExporter:
    format_name = "md"
    media_type = "text/markdown"
    file_extension = ".md"

    def export(self, payload: ExportPayload) -> bytes:
        lines = [f"# {payload.title}", ""]
        if payload.metadata:
            for key, value in payload.metadata.items():
                lines.append(f"- **{key}**: {value}")
            lines.append("")
        lines.append("---")
        lines.append("")

        for item in payload.transcript:
            role_label = item.get("role_label") or item.get("role", "unknown")
            timestamp = item.get("timestamp", "")
            content = item.get("content", "")
            lines.append(f"**[{timestamp}] {role_label}**")
            lines.append("")
            lines.append(content)
            attachments = item.get("attachments") or []
            if attachments:
                lines.append("")
                lines.append("Attachments:")
                for attachment in attachments:
                    lines.append(f"- {attachment}")
            lines.append("")
        return "\n".join(lines).encode("utf-8")
