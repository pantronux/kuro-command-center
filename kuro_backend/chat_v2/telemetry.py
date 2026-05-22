"""Lightweight Chat V2 telemetry hooks."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator


logger = logging.getLogger(__name__)


def record_chat_v2_event(event_name: str, **fields: object) -> None:
    logger.info("chat_v2.%s %s", event_name, fields)


@contextmanager
def chat_v2_timer(event_name: str, **fields: object) -> Iterator[dict]:
    start = time.monotonic()
    metrics: dict = {}
    try:
        yield metrics
    finally:
        metrics["latency_ms"] = round((time.monotonic() - start) * 1000, 2)
        record_chat_v2_event(event_name, **fields, **metrics)
