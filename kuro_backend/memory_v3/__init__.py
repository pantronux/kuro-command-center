"""Memory V3 core architecture.

Memory V3 is additive and remains disabled by default through
KURO_MEMORY_V3_ENABLED=false.
"""
from __future__ import annotations

from .health import get_memory_v3_health, get_memory_v3_public_status
from .reader import MemoryV3Reader
from .schemas import (
    MemoryAssertion,
    MemoryConflict,
    MemoryEvent,
    MemoryItem,
    MemoryPolicy,
    MemoryReadRequest,
    MemoryReadResult,
    MemoryWriteRequest,
    MemoryWriteResult,
)
from .store import MemoryV3Store
from .writer import MemoryWriter

__all__ = [
    "MemoryAssertion",
    "MemoryConflict",
    "MemoryEvent",
    "MemoryItem",
    "MemoryPolicy",
    "MemoryReadRequest",
    "MemoryReadResult",
    "MemoryV3Reader",
    "MemoryV3Store",
    "MemoryWriteRequest",
    "MemoryWriteResult",
    "MemoryWriter",
    "get_memory_v3_health",
    "get_memory_v3_public_status",
]
