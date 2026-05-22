"""Lightweight telemetry helpers for Memory V3 core."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)


def record_memory_v3_event(event_name: str, **fields: object) -> None:
    logger.info("memory_v3.%s %s", event_name, fields)


@contextmanager
def memory_v3_timer(event_name: str, **fields: object) -> Iterator[dict]:
    start = time.monotonic()
    metrics: dict = {}
    try:
        yield metrics
    finally:
        metrics["latency_ms"] = round((time.monotonic() - start) * 1000, 2)
        record_memory_v3_event(event_name, **fields, **metrics)
