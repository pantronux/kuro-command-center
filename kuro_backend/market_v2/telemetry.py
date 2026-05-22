"""Telemetry helpers for Market Sentinel V2."""
from __future__ import annotations

import logging
from typing import Optional

from kuro_backend.config import settings
from kuro_backend.market_v2.schemas import MarketSentinelReport


logger = logging.getLogger(__name__)


def record_market_v2_event(event_name: str, *, symbol: str = "", username: str = "", detail: str = "") -> None:
    logger.info("[MARKET_V2] %s symbol=%s user=%s %s", event_name, symbol, username, detail)


def write_market_signal_memory(report: MarketSentinelReport, *, chat_id: str = "market_v2") -> Optional[str]:
    if not bool(getattr(settings, "KURO_MEMORY_V3_ENABLED", False)):
        return None
    try:
        from kuro_backend.memory_v3.schemas import MemoryWriteRequest
        from kuro_backend.memory_v3.writer import MemoryWriter

        result = MemoryWriter().write(
            MemoryWriteRequest(
                workspace_id=report.workspace_id,
                username=report.username,
                runtime_id="sovereign",
                persona_scope="chancellor",
                chat_id=chat_id,
                source_type="market",
                source_id=report.report_id,
                content=(
                    f"Market signal for {report.symbol}: {report.signal.direction}; "
                    f"confidence={report.confidence:.2f}; summary={report.summary}"
                ),
                memory_type="market_signal_memory",
                canonical_key=f"market_signal_memory:{report.username}:{report.symbol}:{report.report_id}",
                confidence_score=report.confidence,
                importance_score=0.35,
                sensitivity_level="low",
                metadata={"report_id": report.report_id, "symbol": report.symbol},
            ),
            actor_username=report.username,
        )
        return result.memory_id
    except Exception as exc:
        logger.warning("[MARKET_V2] memory write skipped: %s", exc)
        return None
