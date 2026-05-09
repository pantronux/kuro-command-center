from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from kuro_backend import finance_db
from kuro_backend.export_engine.export_models import ExportPayload, ExportSection, ExportTable


def render_market_snapshot(username: str) -> ExportPayload:
    watched = finance_db.list_watched_symbols(active_only=True, username=username)
    predictions = finance_db.list_prediction_watch(username=username)
    hud = finance_db.get_market_hud_items(username=username)
    brief_parts = finance_db.get_market_brief_parts(username=username)
    brief = (brief_parts.get('brief_text') or '').strip() or (brief_parts.get('last_sentinel_note') or '').strip()

    if not watched and not predictions and not hud and not brief:
        raise HTTPException(status_code=404, detail='Market snapshot not found')

    sections = []
    if brief:
        sections.append(ExportSection(heading='market_brief', body=brief))
    if brief_parts.get('last_sentinel_note'):
        sections.append(ExportSection(heading='last_sentinel_note', body=brief_parts['last_sentinel_note']))

    tables = []
    if watched:
        columns = ['symbol', 'label', 'baseline_price', 'last_price', 'last_pct_change', 'last_refreshed', 'active']
        rows = [[str(item.get(col, '')) for col in columns] for item in watched]
        tables.append(ExportTable(title='watched_symbols', columns=columns, rows=rows))
    if predictions:
        columns = ['slug', 'label', 'last_probability', 'trend', 'updated_at']
        rows = [[str(item.get(col, '')) for col in columns] for item in predictions]
        tables.append(ExportTable(title='prediction_watch', columns=columns, rows=rows))
    if hud:
        columns = ['id', 'label', 'kind', 'prob', 'trend', 'sentiment', 'last_pct_change']
        rows = [[str(item.get(col, '')) for col in columns] for item in hud]
        tables.append(ExportTable(title='market_hud_items', columns=columns, rows=rows))

    transcript = []
    now = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    if brief:
        transcript.append(
            {
                'timestamp': now,
                'role': 'assistant',
                'persona': 'market',
                'role_label': 'Market Brief',
                'content': brief,
                'attachments': [],
                'is_edited': 0,
                'is_bookmarked': 0,
            }
        )
    for row in hud:
        transcript.append(
            {
                'timestamp': now,
                'role': 'assistant',
                'persona': 'market',
                'role_label': f"HUD {row.get('kind', 'item')}",
                'content': f"{row.get('label', '')} | trend={row.get('trend', '')} | sentiment={row.get('sentiment', '')}",
                'attachments': [],
                'is_edited': 0,
                'is_bookmarked': 0,
            }
        )

    return ExportPayload(
        title='Market Snapshot',
        export_type='market_snapshot',
        username=username,
        source_chat_id=None,
        metadata={
            'watched_symbol_count': len(watched),
            'prediction_watch_count': len(predictions),
            'hud_item_count': len(hud),
            'has_brief': str(bool(brief)).lower(),
        },
        sections=sections,
        tables=tables,
        transcript=transcript,
    )
