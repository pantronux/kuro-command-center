"""Chat V2 SSE envelope, replay, and deterministic termination helpers."""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from typing import Any, AsyncIterator, Awaitable, Callable, Deque, Dict, Iterable, Optional

from starlette.requests import Request

from kuro_backend.chat_v2.schemas import StreamingEnvelope
from kuro_backend.chat_v2.telemetry import record_chat_v2_event


OnComplete = Callable[[str], Awaitable[None] | None]


class SSEReplayBuffer:
    def __init__(self, maxlen: int = 100) -> None:
        self.maxlen = int(maxlen)
        self._buffers: Dict[str, Deque[StreamingEnvelope]] = defaultdict(
            lambda: deque(maxlen=self.maxlen)
        )
        self._counters: Dict[str, int] = defaultdict(int)

    def next_seq(self, chat_id: str) -> int:
        self._counters[chat_id] += 1
        return self._counters[chat_id]

    def append(self, envelope: StreamingEnvelope) -> None:
        self._buffers[envelope.chat_id].append(envelope)
        self._counters[envelope.chat_id] = max(
            self._counters[envelope.chat_id],
            int(envelope.event_seq),
        )

    def replay_after(self, chat_id: str, last_event_id: Optional[int]) -> list[StreamingEnvelope]:
        if last_event_id is None:
            return []
        return [
            envelope
            for envelope in list(self._buffers.get(chat_id, ()))
            if int(envelope.event_seq) > int(last_event_id)
        ]

    def has_replay_after(self, chat_id: str, last_event_id: Optional[int]) -> bool:
        return bool(self.replay_after(chat_id, last_event_id))

    def reset(self) -> None:
        self._buffers.clear()
        self._counters.clear()


chat_v2_replay_buffer = SSEReplayBuffer()


def format_sse(envelope: StreamingEnvelope) -> str:
    payload = envelope.model_dump()
    return (
        f"id: {envelope.event_seq}\n"
        f"event: {envelope.event}\n"
        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    )


async def _maybe_await(value: Awaitable[None] | None) -> None:
    if value is not None and hasattr(value, "__await__"):
        await value


async def stream_chat_v2_envelopes(
    *,
    chat_id: str,
    trace_id: str,
    token_source: Callable[[], AsyncIterator[str]],
    last_event_id: Optional[int] = None,
    request: Optional[Request] = None,
    replay_buffer: SSEReplayBuffer = chat_v2_replay_buffer,
    on_complete: Optional[OnComplete] = None,
    structured_outputs: Optional[Iterable[Dict[str, Any]]] = None,
) -> AsyncIterator[str]:
    """Yield Chat V2 SSE frames with replay, error, and done semantics."""
    replayed = replay_buffer.replay_after(chat_id, last_event_id)
    replayed_done = False
    for envelope in replayed:
        replayed_done = replayed_done or envelope.event == "done"
        yield format_sse(envelope)
    if replayed_done:
        record_chat_v2_event("stream_replayed", chat_id=chat_id, trace_id=trace_id, events=len(replayed))
        return

    collected: list[str] = []

    def emit(event: str, data: Dict[str, Any]) -> StreamingEnvelope:
        envelope = StreamingEnvelope(
            event=event,  # type: ignore[arg-type]
            event_seq=replay_buffer.next_seq(chat_id),
            trace_id=trace_id,
            chat_id=chat_id,
            data=data,
        )
        replay_buffer.append(envelope)
        return envelope

    yield format_sse(emit("trace", {"phase": "started"}))
    try:
        async for chunk in token_source():
            if request is not None and await request.is_disconnected():
                record_chat_v2_event("stream_client_disconnected", chat_id=chat_id, trace_id=trace_id)
                return
            text = str(chunk or "")
            if not text:
                continue
            collected.append(text)
            yield format_sse(emit("token", {"text": text}))
        for structured_output in structured_outputs or []:
            yield format_sse(emit("structured_output", structured_output))
        if on_complete is not None:
            await _maybe_await(on_complete("".join(collected)))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        record_chat_v2_event("stream_error", chat_id=chat_id, trace_id=trace_id, error=str(exc)[:200])
        yield format_sse(emit("error", {"message": str(exc)}))
    finally:
        if request is None or not await request.is_disconnected():
            yield format_sse(emit("done", {"ok": True}))
