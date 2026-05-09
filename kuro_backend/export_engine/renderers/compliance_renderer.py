from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from kuro_backend import compliance_db
from kuro_backend.export_engine.export_models import ExportPayload, ExportSection, ExportTable


def render_compliance_report(username: str, standard: str | None = None) -> ExportPayload:
    evidence = compliance_db.get_evidence_matrix(standard=standard)
    audit_trail = compliance_db.get_audit_trail(limit=50)
    progress = compliance_db.get_compliance_progress(standard) if standard else None

    if not evidence and not audit_trail:
        raise HTTPException(status_code=404, detail='Compliance data not found')

    tables = []
    if evidence:
        columns = [
            'id', 'file_name', 'category', 'standard', 'clause_id', 'status',
            'finding', 'recommendation', 'analyzed_at', 'created_at'
        ]
        rows = [[str(item.get(col, '')) for col in columns] for item in evidence]
        tables.append(ExportTable(title='evidence_matrix', columns=columns, rows=rows))
    if audit_trail:
        columns = ['id', 'action', 'user', 'details', 'standard', 'timestamp']
        rows = [[str(item.get(col, '')) for col in columns] for item in audit_trail]
        tables.append(ExportTable(title='audit_trail', columns=columns, rows=rows))

    sections = []
    if progress:
        sections.append(
            ExportSection(
                heading='progress_summary',
                body=(
                    f"standard={progress['standard']} total={progress['total_evidence']} "
                    f"compliant={progress['compliant']} non_compliant={progress['non_compliant']} "
                    f"pending={progress['pending']} percentage={progress['percentage']}"
                ),
            )
        )

    transcript = []
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    if progress:
        transcript.append(
            {
                'timestamp': now,
                'role': 'assistant',
                'persona': 'compliance',
                'role_label': 'Compliance Progress',
                'content': sections[0].body,
                'attachments': [],
                'is_edited': 0,
                'is_bookmarked': 0,
            }
        )
    for row in evidence[:25]:
        transcript.append(
            {
                'timestamp': row.get('created_at') or now,
                'role': 'assistant',
                'persona': 'compliance',
                'role_label': f"Evidence {row.get('standard') or 'general'}",
                'content': f"{row.get('file_name', '')} | {row.get('status', '')} | {row.get('finding', '')}",
                'attachments': [row.get('file_path')] if row.get('file_path') else [],
                'is_edited': 0,
                'is_bookmarked': 0,
            }
        )

    return ExportPayload(
        title=f"Compliance Report {standard or 'all'}",
        export_type='compliance_report',
        username=username,
        source_chat_id=None,
        metadata={
            'standard': standard or 'all',
            'evidence_count': len(evidence),
            'audit_trail_count': len(audit_trail),
            'admin_scope': 'true',
        },
        sections=sections,
        tables=tables,
        transcript=transcript,
    )
