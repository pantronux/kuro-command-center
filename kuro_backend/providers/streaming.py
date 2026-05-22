"""Provider Registry V2 streaming helpers."""
from __future__ import annotations

from typing import AsyncIterator

from kuro_backend.providers.schemas import ProviderStreamEvent


async def stream_text_once(text: str, *, trace_id: str = "") -> AsyncIterator[ProviderStreamEvent]:
    if text:
        yield ProviderStreamEvent(event_type="token", delta=text, content=text, trace_id=trace_id)
    yield ProviderStreamEvent(event_type="done", done=True, trace_id=trace_id)


async def collect_stream_content(events: AsyncIterator[ProviderStreamEvent]) -> str:
    chunks: list[str] = []
    async for event in events:
        if event.error:
            raise RuntimeError(event.error)
        if event.delta:
            chunks.append(event.delta)
    return "".join(chunks)
