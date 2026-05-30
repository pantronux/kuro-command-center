"""Approved-only search and context assembly for KRC knowledge."""
from __future__ import annotations

from typing import Any, Dict, List

from kuro_backend.knowledge_center.candidates import KnowledgeStore
from kuro_backend.knowledge_center.redaction import redact_public_text


def search_approved_knowledge(
    *,
    store: KnowledgeStore | None = None,
    query: str = "",
    domains: List[str] | None = None,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    active_store = store or KnowledgeStore()
    rows = active_store.search_approved(query=query, domains=domains or [], limit=limit)
    results: List[Dict[str, Any]] = []
    for row in rows:
        public_row = dict(row)
        public_row.pop("content", None)
        results.append(public_row)
    return results


def build_approved_context(
    *,
    store: KnowledgeStore | None = None,
    query: str = "",
    domains: List[str] | None = None,
    limit: int = 10,
    max_chars: int = 4000,
) -> Dict[str, Any]:
    active_store = store or KnowledgeStore()
    rows = active_store.search_approved(query=query, domains=domains or [], limit=limit)
    blocks: List[str] = []
    used = 0
    for row in rows:
        block = (
            f"[{row['knowledge_id']}] {row['title']}\n"
            f"Domain: {row['domain']} | Confidence: {row['confidence']:.2f}\n"
            f"Summary: {row['summary']}\n"
            f"Context: {redact_public_text(row.get('content') or row['summary'], max_chars=800)}"
        )
        if used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block)
    public_results = []
    for row in rows[: len(blocks)]:
        public_row = dict(row)
        public_row.pop("content", None)
        public_results.append(public_row)
    return {
        "context": "\n\n".join(blocks),
        "results": public_results,
    }
