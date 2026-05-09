from __future__ import annotations

from typing import Iterable


def prevent_memory_mutation(new_summary: str, source_memories: Iterable[object]) -> bool:
    """Return False when summary introduces entities absent from source memories."""
    src = " ".join(str(x).lower() for x in source_memories or [])
    if not src.strip():
        return True
    tokens = [t for t in (new_summary or "").lower().split() if len(t) > 6]
    introduced = [t for t in tokens if t not in src]
    # Allow small abstraction drift; block obvious mutation.
    return len(introduced) <= 6
