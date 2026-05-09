from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from kuro_backend import intelligence_db
from kuro_backend.config import settings
from kuro_backend.export_engine.export_models import ExportFormat, ExportPayload, ExportRequest, ExportTarget
from kuro_backend.export_engine.export_registry import get_exporter
from kuro_backend.export_engine.export_security import (
    sanitize_export_payload,
    validate_compliance_export_permission,
    validate_export_permission,
)
from kuro_backend.export_engine.renderers import (
    render_chat_session,
    render_compliance_report,
    render_intelligence_report,
    render_market_snapshot,
    render_selected_messages,
)

_DEFAULT_WORKDIR = settings.WORKING_DIR or str(Path(__file__).resolve().parents[2])
EXPORT_ROOT = Path(_DEFAULT_WORKDIR).joinpath("exports")


def _render_payload(request: ExportRequest, username: str) -> ExportPayload:
    if request.target == ExportTarget.CHAT_SESSION:
        if not request.chat_id:
            raise HTTPException(status_code=400, detail="chat_id is required")
        validate_export_permission(username, request.chat_id)
        return render_chat_session(request.chat_id, username)
    if request.target == ExportTarget.SELECTED_MESSAGES:
        if not request.chat_id:
            raise HTTPException(status_code=400, detail="chat_id is required")
        validate_export_permission(username, request.chat_id, request.message_ids)
        return render_selected_messages(request.chat_id, request.message_ids, username)
    if request.target == ExportTarget.INTELLIGENCE_REPORT:
        return render_intelligence_report(username, briefing_date=request.briefing_date)
    if request.target == ExportTarget.COMPLIANCE_REPORT:
        validate_compliance_export_permission(username)
        return render_compliance_report(username, standard=request.standard)
    if request.target == ExportTarget.MARKET_SNAPSHOT:
        return render_market_snapshot(username)
    raise HTTPException(status_code=400, detail=f"Unsupported export target: {request.target}")


def build_filename(payload: ExportPayload, export_format: str) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    chat_id = payload.source_chat_id or "unknown"
    if payload.export_type == ExportTarget.SELECTED_MESSAGES.value:
        return f"chat_selection_{chat_id}_{timestamp}.{export_format}"
    return f"chat_{chat_id}_{timestamp}.{export_format}"


def export_sync(request: ExportRequest, username: str) -> tuple[bytes, str, str]:
    payload = sanitize_export_payload(_render_payload(request, username))
    exporter = get_exporter(request.format.value)
    content = exporter.export(payload)
    filename = build_filename(payload, request.format.value)
    intelligence_db.log_export_audit(
        username,
        "export_sync_completed",
        None,
        {
            "target": request.target.value,
            "format": request.format.value,
            "chat_id": request.chat_id,
            "briefing_date": request.briefing_date,
            "standard": request.standard,
            "message_ids": request.message_ids,
            "filename": filename,
        },
    )
    return content, filename, exporter.media_type


def create_async_pdf_job(request: ExportRequest, username: str) -> int:
    if request.format != ExportFormat.PDF:
        raise HTTPException(status_code=400, detail="Async jobs are only supported for pdf")
    if request.target == ExportTarget.CHAT_SESSION:
        if not request.chat_id:
            raise HTTPException(status_code=400, detail="chat_id is required")
        validate_export_permission(username, request.chat_id)
    elif request.target == ExportTarget.SELECTED_MESSAGES:
        if not request.chat_id:
            raise HTTPException(status_code=400, detail="chat_id is required")
        validate_export_permission(username, request.chat_id, request.message_ids)
    elif request.target == ExportTarget.COMPLIANCE_REPORT:
        validate_compliance_export_permission(username)
    return intelligence_db.create_export_job(
        username=username,
        export_type=request.target.value,
        export_format=request.format.value,
        source_chat_id=request.chat_id,
        source_message_ids=request.message_ids,
        briefing_date=request.briefing_date,
        standard=request.standard,
    )


def process_export_job(job_id: int) -> None:
    job = intelligence_db.get_export_job(job_id)
    if not job:
        raise RuntimeError(f"Export job {job_id} not found")

    intelligence_db.mark_export_job_running(job_id)
    try:
        request = ExportRequest(
            target=job["export_type"],
            format=job["export_format"],
            chat_id=job["source_chat_id"],
            message_ids=json.loads(job.get("source_message_ids") or "[]"),
            briefing_date=job.get("briefing_date"),
            standard=job.get("standard"),
        )
        payload = sanitize_export_payload(_render_payload(request, job["username"]))
        exporter = get_exporter(request.format.value)
        content = exporter.export(payload)
        filename = build_filename(payload, request.format.value)
        export_dir = EXPORT_ROOT / job["username"] / request.format.value
        export_dir.mkdir(parents=True, exist_ok=True)
        file_path = export_dir / filename
        file_path.write_bytes(content)
        checksum = hashlib.sha256(content).hexdigest()
        intelligence_db.mark_export_job_completed(
            job_id,
            str(file_path),
            len(content),
            checksum,
        )
        intelligence_db.log_export_audit(
            job["username"],
            "export_async_completed",
            job_id,
            {
                "target": request.target.value,
                "format": request.format.value,
                "chat_id": request.chat_id,
                "briefing_date": request.briefing_date,
                "standard": request.standard,
                "message_ids": request.message_ids,
                "filename": filename,
                "checksum_sha256": checksum,
            },
        )
    except Exception as exc:
        intelligence_db.mark_export_job_failed(job_id, str(exc))
        intelligence_db.log_export_audit(
            job["username"],
            "export_async_failed",
            job_id,
            {
                "error": str(exc),
            },
        )
        raise
