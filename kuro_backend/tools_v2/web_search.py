"""Web Search V2 adapter using the existing Serper tool when configured."""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

from kuro_backend.tools_v2.audit import utc_now_iso
from kuro_backend.tools_v2.schemas import NormalizedSource


SerperCallable = Callable[[str, str, int], Dict[str, Any]]


class WebSearchV2:
    def __init__(self, search_callable: Optional[SerperCallable] = None) -> None:
        self.search_callable = search_callable

    def search(
        self,
        *,
        query: str,
        search_type: str = "search",
        max_results: int = 5,
    ) -> Dict[str, Any]:
        query = str(query or "").strip()
        search_type = str(search_type or "search").strip().lower()
        max_results = max(1, min(int(max_results or 5), 20))
        if not query:
            return {"ok": False, "error": "query_required", "sources": []}
        if search_type not in {"search", "news", "scholar"}:
            return {"ok": False, "error": "unsupported_search_type", "sources": []}

        search_callable = self.search_callable
        if search_callable is None:
            if not os.getenv("SERPER_API_KEY", "").strip():
                return {"ok": False, "error": "serper_not_configured", "sources": []}
            from kuro_backend.serper_tool import serper_search

            search_callable = serper_search

        raw = search_callable(query, search_type, max_results)
        if not isinstance(raw, dict):
            return {"ok": False, "error": "invalid_search_response", "sources": []}
        if raw.get("error"):
            return {"ok": False, "error": str(raw.get("error")), "sources": []}

        items = raw.get("organic_results")
        if items is None:
            items = raw.get("results") or []
        sources = self._normalize_sources(items, search_type=search_type)
        return {
            "ok": True,
            "query": query,
            "search_type": search_type,
            "sources": [source.model_dump() for source in sources[:max_results]],
            "total_results": len(sources),
        }

    def _normalize_sources(self, items: Any, *, search_type: str) -> List[NormalizedSource]:
        if not isinstance(items, list):
            return []
        retrieved_at = utc_now_iso()
        sources: List[NormalizedSource] = []
        seen_urls: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            url = str(item.get("link") or item.get("url") or "").strip()
            title = str(item.get("title") or "").strip()
            if not url and not title:
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            sources.append(
                NormalizedSource(
                    title=title,
                    url=url,
                    snippet=str(item.get("snippet") or item.get("summary") or "").strip(),
                    source_type="news" if search_type == "news" else ("scholar" if search_type == "scholar" else "web"),
                    published_at=str(item.get("date") or item.get("published_at") or "") or None,
                    retrieved_at=retrieved_at,
                    confidence=0.76 if url else 0.55,
                )
            )
        return sources
