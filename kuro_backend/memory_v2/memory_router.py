"""Memory routing policy between memory tiers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MemoryBackend = Literal["short_term_sqlite", "memory_v2_sqlite", "mem0", "chroma"]


@dataclass(frozen=True)
class MemoryRoute:
    memory_type: str
    backend: MemoryBackend
    requires_runtime_scope: bool = True


_ROUTES: dict[str, MemoryRoute] = {
    "short_term": MemoryRoute("short_term", "short_term_sqlite"),
    "working": MemoryRoute("working", "memory_v2_sqlite"),
    "episodic": MemoryRoute("episodic", "memory_v2_sqlite"),
    "semantic": MemoryRoute("semantic", "mem0"),
    "operational": MemoryRoute("operational", "memory_v2_sqlite"),
    "reflective": MemoryRoute("reflective", "memory_v2_sqlite"),
}


def route_memory_type(memory_type: str) -> MemoryRoute:
    key = str(memory_type or "short_term").strip().lower()
    return _ROUTES.get(key, _ROUTES["short_term"])


def route_document_memory() -> MemoryRoute:
    return MemoryRoute("document", "chroma")


__all__ = ["MemoryBackend", "MemoryRoute", "route_document_memory", "route_memory_type"]
