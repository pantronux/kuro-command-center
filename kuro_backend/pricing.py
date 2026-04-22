"""
Static USD estimates per 1K tokens for Gemini models (Chancellor / observability).

Rates are approximate; update when Google publishes new list prices.
Unknown models log a warning and return 0.0 cost.

--- Header Doc ---
Purpose: Deterministic cost estimator for observability + fiscal sentinel.
Caller: observability.track_token_usage, dreaming_worker._run_fiscal_sentinel.
Dependencies: stdlib (logging, re).
Main Functions: estimate_cost_usd(model, prompt_tokens, completion_tokens), rates_for(model).
Side Effects: None (pure lookup + log on unknown model).
"""
from __future__ import annotations

import logging
import re
from typing import Dict, Final, Tuple

logger = logging.getLogger(__name__)

# USD per 1K tokens (input / output), approximate list pricing.
_GEMINI_USD_PER_1K: Final[Dict[str, Tuple[float, float]]] = {
    # Primary fleet (V6 Sovereign defaults)
    "gemini-3-flash-preview": (0.00035, 0.00105),
    "gemini-2.5-flash": (0.00030, 0.00090),
    "gemini-2.5-flash-preview": (0.00030, 0.00090),
    "gemini-2.5-pro": (0.00125, 0.00500),
    "gemini-2.5-pro-preview": (0.00125, 0.00500),
    "gemini-2.0-flash": (0.00010, 0.00040),
    "gemini-2.0-flash-001": (0.00010, 0.00040),
    "gemini-1.5-flash": (0.000075, 0.00030),
    "gemini-1.5-pro": (0.00125, 0.00500),
}


def _normalize_model(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip().lower())


def estimate_cost_usd(
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Return estimated USD spend for this completion (incremental)."""
    key = _normalize_model(model_name)
    rates = _GEMINI_USD_PER_1K.get(key)
    if rates is None:
        # Prefix match (e.g. gemini-2.5-flash-2025-03-25)
        for k, v in _GEMINI_USD_PER_1K.items():
            if key.startswith(k):
                rates = v
                break
    if rates is None:
        logger.warning(
            "[PRICING] unknown model %r — cost recorded as 0.0; extend pricing.py",
            model_name,
        )
        return 0.0
    inp_per_1k, out_per_1k = rates
    pt = max(0, int(prompt_tokens or 0))
    ct = max(0, int(completion_tokens or 0))
    return (pt / 1000.0) * inp_per_1k + (ct / 1000.0) * out_per_1k


__all__ = ["estimate_cost_usd", "_GEMINI_USD_PER_1K"]
