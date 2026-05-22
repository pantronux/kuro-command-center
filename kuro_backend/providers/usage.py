"""Provider usage helpers."""
from __future__ import annotations

from typing import Iterable

from kuro_backend.providers.schemas import ProviderMessage, ProviderUsage


def estimate_tokens_from_text(text: str) -> int:
    return max(0, len((text or "").split()))


def estimate_request_usage(messages: Iterable[ProviderMessage], output_text: str = "") -> ProviderUsage:
    input_tokens = sum(estimate_tokens_from_text(str(message.content)) for message in messages)
    output_tokens = estimate_tokens_from_text(output_text)
    return ProviderUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )
