"""HTTP client helper for Kuro Stack <-> Kuro Knowledge integration."""
from __future__ import annotations

import os
from typing import Any, Dict, List

import requests


class KuroStackKnowledgeClient:
    """Small HTTP-only client; it never reads KRC/Kuro Knowledge DB files."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None, timeout: float = 10.0) -> None:
        self.base_url = (base_url or os.getenv("KURO_STACK_KNOWLEDGE_GATEWAY_URL") or "http://127.0.0.1:8088").rstrip("/")
        self.api_key = api_key or os.getenv("KURO_KNOWLEDGE_API_KEY", "")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Kuro-Knowledge-Key"] = self.api_key
        return headers

    def search_approved(self, *, query: str, domains: List[str] | None = None, limit: int = 10) -> Dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/api/knowledge/search-approved",
            json={"query": query, "domains": domains or [], "limit": limit},
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def context_approved(
        self,
        *,
        query: str,
        domains: List[str] | None = None,
        limit: int = 10,
        max_chars: int = 4000,
    ) -> Dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/api/knowledge/context-approved",
            json={
                "query": query,
                "domains": domains or [],
                "limit": limit,
                "max_chars": max_chars,
            },
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def submit_ingest(
        self,
        *,
        source_app: str,
        domain: str,
        source_type: str,
        title: str,
        content: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/api/knowledge/ingest",
            json={
                "source_app": source_app,
                "domain": domain,
                "source_type": source_type,
                "title": title,
                "content": content,
                "metadata": metadata or {},
            },
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def list_ingest_jobs(self, *, limit: int = 50) -> Dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/api/knowledge/ingest/jobs",
            params={"limit": limit},
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def retry_ingest_job(self, *, job_id: str) -> Dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/api/knowledge/ingest/jobs/{job_id}/retry",
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def submit_candidate(self, *, title: str, content: str, domain: str = "stack.daily_candidate", reason: str = "") -> Dict[str, Any]:
        response = requests.post(
            f"{self.base_url}/api/knowledge/candidates",
            json={
                "source_app": "kuro_stack",
                "domain": domain,
                "title": title,
                "content": content,
                "reason": reason,
            },
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()
