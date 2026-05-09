from __future__ import annotations

import json
from datetime import datetime

from fastapi import HTTPException

from kuro_backend import intelligence_db
from kuro_backend.export_engine.export_models import ExportPayload, ExportSection, ExportTable


def render_intelligence_report(username: str, briefing_date: str | None = None) -> ExportPayload:
    briefing = None
    if briefing_date:
        briefing = intelligence_db.get_briefing_by_date(briefing_date, username=username)
    else:
        rows = intelligence_db.get_briefings(limit=1, username=username)
        briefing = rows[0] if rows else None
    if not briefing:
        raise HTTPException(status_code=404, detail='Intelligence briefing not found')

    raw = briefing.get('raw_json_data') or {}
    signals = briefing.get('experimental_signals') or []
    stocks = briefing.get('stock_recommendations') or []
    sources = intelligence_db.get_research_sources(username=username, since_hours=168)

    sections = []
    for key, value in raw.items():
        if isinstance(value, (dict, list)):
            body = json.dumps(value, ensure_ascii=False, indent=2)
        else:
            body = str(value)
        sections.append(ExportSection(heading=str(key), body=body))
    if briefing.get('summary_text'):
        sections.insert(0, ExportSection(heading='summary_text', body=str(briefing['summary_text'])))

    tables = []
    if stocks:
        columns = sorted({str(key) for item in stocks for key in item.keys()})
        rows = [[str(item.get(col, '')) for col in columns] for item in stocks]
        tables.append(ExportTable(title='stock_recommendations', columns=columns, rows=rows))
    if sources:
        columns = ['session_id', 'chat_id', 'query', 'source_type', 'title', 'link', 'retrieved_at']
        rows = [[str(item.get(col, '')) for col in columns] for item in sources]
        tables.append(ExportTable(title='research_sources', columns=columns, rows=rows))

    transcript = []
    for section in sections:
        transcript.append(
            {
                'timestamp': briefing.get('created_at') or datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                'role': 'assistant',
                'persona': 'intelligence',
                'role_label': f"Intelligence: {section.heading}",
                'content': section.body,
                'attachments': [],
                'is_edited': 0,
                'is_bookmarked': 0,
            }
        )

    return ExportPayload(
        title=f"Intelligence Briefing {briefing.get('date', 'latest')}",
        export_type='intelligence_report',
        username=username,
        source_chat_id=None,
        metadata={
            'briefing_date': briefing.get('date', ''),
            'created_at': briefing.get('created_at', ''),
            'signal_count': len(signals),
            'stock_recommendation_count': len(stocks),
            'research_source_count': len(sources),
        },
        sections=sections,
        tables=tables,
        transcript=transcript,
    )
