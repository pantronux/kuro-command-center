"""Per-request cognition trace event model and writer."""

# --- Header Doc ---
# Purpose: Capture runtime cognition traces for observability.
# Caller: langgraph_core.py request processing path.
# Dependencies: intelligence_db.py.
# Main Functions: CognitionTrace.record_node(), finish().
# Side Effects: Persists trace rows into `cognition_traces`.

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from kuro_backend import intelligence_db

logger = logging.getLogger(__name__)


@dataclass
class CognitionTrace:
    trace_id: str
    runtime_id: str
    username: str
    chat_id: str
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    finished_at: str = ""
    latency_ms: float = 0.0
    node_sequence: list[str] = field(default_factory=list)
    memory_namespaces: list[str] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    error: str = ""
    _started_perf: float = field(default_factory=time.perf_counter, repr=False)

    @staticmethod
    def start(trace_id: str, runtime_id: str, username: str, chat_id: str) -> "CognitionTrace":
        return CognitionTrace(
            trace_id=trace_id,
            runtime_id=runtime_id,
            username=username,
            chat_id=chat_id,
        )

    def record_node(self, name: str) -> None:
        try:
            label = str(name or "").strip()
            if label:
                self.node_sequence.append(label)
        except Exception as exc:
            logger.debug("record_node skipped: %s", exc)

    def record_memory_access(self, namespace: str) -> None:
        try:
            ns = str(namespace or "").strip()
            if ns and ns not in self.memory_namespaces:
                self.memory_namespaces.append(ns)
        except Exception as exc:
            logger.debug("record_memory_access skipped: %s", exc)

    def record_tool_call(self, tool_name: str) -> None:
        try:
            tool = str(tool_name or "").strip()
            if tool:
                self.tool_calls.append(tool)
        except Exception as exc:
            logger.debug("record_tool_call skipped: %s", exc)

    def finish(self, error: str = "") -> None:
        self.finished_at = datetime.utcnow().isoformat()
        self.latency_ms = max(0.0, (time.perf_counter() - self._started_perf) * 1000.0)
        self.error = str(error or "")
        try:
            intelligence_db.log_cognition_trace(self)
        except Exception as exc:
            logger.warning("cognition trace persistence skipped: %s", exc)
