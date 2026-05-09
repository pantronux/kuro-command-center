from __future__ import annotations

import hashlib
import re
from typing import Dict, List

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150
MAX_CHUNK_PERSIST = 4000


def clean_text(text: str) -> str:
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    raw = re.sub(r"[ \t]+", " ", raw)
    return raw.strip()


def _extract_entities(text: str) -> List[str]:
    seen = []
    for match in re.findall(r"\b[A-Z][A-Za-z0-9_-]{2,}\b", text or ""):
        if match not in seen:
            seen.append(match)
        if len(seen) >= 8:
            break
    return seen


def semantic_chunk(text: str, dataset_uuid: str) -> List[Dict]:
    cleaned = clean_text(text)
    if not cleaned:
        return []
    chunks: List[Dict] = []
    start = 0
    index = 0
    while start < len(cleaned):
        end = min(start + CHUNK_SIZE, len(cleaned))
        window = cleaned[start:end]
        if end < len(cleaned):
            last_break = max(window.rfind("\n\n"), window.rfind(". "), window.rfind(" "))
            if last_break > CHUNK_SIZE // 2:
                window = window[:last_break].strip()
                end = start + last_break
        window = window.strip()
        if window:
            persisted = window[:MAX_CHUNK_PERSIST]
            entities = _extract_entities(persisted)
            chunks.append(
                {
                    "dataset_uuid": dataset_uuid,
                    "chunk_index": index,
                    "chunk_text": persisted,
                    "chunk_hash": hashlib.sha256(f"{dataset_uuid}:{index}:{persisted}".encode("utf-8")).hexdigest(),
                    "token_count": max(1, len(persisted.split())),
                    "embedding_status": "queued",
                    "metadata": {"start_offset": start, "end_offset": end},
                    "preview_text": persisted[:220],
                    "entities": entities,
                    "is_orphan": 0,
                }
            )
            index += 1
        if end >= len(cleaned):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks
