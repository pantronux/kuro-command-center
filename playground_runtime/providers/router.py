"""
Provider router.

--- Header Doc ---
Purpose: Dispatch single or comparative requests through registered providers.
Caller: KPR service and API endpoints.
Dependencies: registry, adapter contracts.
Main Functions: invoke_single(), invoke_comparative().
Side Effects: Calls external providers.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from typing import Dict, List

from playground_runtime.errors import ProviderExecutionError
from playground_runtime.providers.adapters.base_adapter import ProviderRequest, ProviderResponse
from playground_runtime.providers.registry import ProviderRegistry


@dataclass
class ComparativeResult:
    prompt_sha256: str
    responses: Dict[str, ProviderResponse]


class ProviderRouter:
    def __init__(self, registry: ProviderRegistry, max_concurrent: int = 2):
        self.registry = registry
        self.max_concurrent = max(1, max_concurrent)

    def invoke_single(self, provider_id: str, req: ProviderRequest) -> ProviderResponse:
        if not self.registry.health_monitor.is_available(provider_id):
            raise ProviderExecutionError(f"provider '{provider_id}' is temporarily unavailable")
        adapter = self.registry.get(provider_id)
        try:
            resp = adapter.invoke(req)
            self.registry.health_monitor.record_success(provider_id)
            return resp
        except Exception:
            self.registry.health_monitor.record_failure(provider_id)
            raise

    def invoke_comparative(self, provider_ids: List[str], req: ProviderRequest) -> ComparativeResult:
        if len(provider_ids) < 2:
            raise ProviderExecutionError("comparative mode requires at least 2 providers")

        responses: Dict[str, ProviderResponse] = {}
        with ThreadPoolExecutor(max_workers=min(self.max_concurrent, len(provider_ids))) as exe:
            futures = {pid: exe.submit(self.invoke_single, pid, req) for pid in provider_ids}
            for pid, fut in futures.items():
                responses[pid] = fut.result()

        return ComparativeResult(prompt_sha256=sha256(req.prompt.encode("utf-8")).hexdigest(), responses=responses)
