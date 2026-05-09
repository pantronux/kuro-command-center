from __future__ import annotations

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from kuro_backend.export_engine.export_models import ExportPayload


class PdfExporter:
    format_name = "pdf"
    media_type = "application/pdf"
    file_extension = ".pdf"

    def export(self, payload: ExportPayload) -> bytes:
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=0.6 * inch,
            leftMargin=0.6 * inch,
            topMargin=0.6 * inch,
            bottomMargin=0.6 * inch,
        )
        styles = getSampleStyleSheet()
        story = [Paragraph(payload.title, styles["Title"]), Spacer(1, 12)]

        for key, value in payload.metadata.items():
            story.append(Paragraph(f"<b>{key}</b>: {value}", styles["BodyText"]))
        story.append(Spacer(1, 12))

        for item in payload.transcript:
            role_label = item.get("role_label") or item.get("role", "unknown")
            timestamp = item.get("timestamp", "")
            content = (item.get("content", "") or "").replace("\n", "<br/>")
            story.append(Paragraph(f"<b>[{timestamp}] {role_label}</b>", styles["Heading4"]))
            story.append(Paragraph(content, styles["BodyText"]))
            attachments = item.get("attachments") or []
            if attachments:
                story.append(Paragraph("Attachments: " + ", ".join(str(a) for a in attachments), styles["Italic"]))
            story.append(Spacer(1, 10))

        doc.build(story)
        return buffer.getvalue()
