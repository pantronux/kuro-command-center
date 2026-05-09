"""
Provider adapter contract.

--- Header Doc ---
Purpose: Define provider request/response contract for KPR router.
Caller: provider router and registry.
Dependencies: abc, dataclasses, uuid.
Main Functions: BaseAdapter.invoke().
Side Effects: None in base implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4


@dataclass
class ProviderRequest:
    prompt: str
    model: str
    dataset_version: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderResponse:
    provider_id: str
    model_id: str
    model_version: str
    request_id: str
    raw_json: Dict[str, Any]
    response_text: Optional[str]
    finish_reason: Optional[str]
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]
    latency_ms: float
    collected_at_utc: datetime


class BaseAdapter(ABC):
    provider_id: str

    @abstractmethod
    def invoke(self, req: ProviderRequest) -> ProviderResponse:
        raise NotImplementedError

    @staticmethod
    def build_request_id() -> str:
        return str(uuid4())

    @staticmethod
    def now_utc() -> datetime:
        return datetime.now(timezone.utc)
