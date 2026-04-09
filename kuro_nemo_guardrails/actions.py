"""Custom NeMo actions for Sniper rails (loaded from config directory)."""
from __future__ import annotations

import logging
from typing import Optional

from nemoguardrails.actions import action

from kuro_backend.guardrails.jailbreak_precheck import jailbreak_triggered
from kuro_backend.guardrails.sniper_context import should_fact_check_heuristic
from kuro_backend.memory_manager import query_memory

log = logging.getLogger(__name__)


@action(is_system_action=True)
async def sniper_jailbreak_heuristic(context: Optional[dict] = None, **kwargs) -> bool:
    """
    Returns True if the message should be blocked (jailbreak/heuristic hit).
    Mirrors kuro_backend.guardrails.jailbreak_precheck.jailbreak_triggered.
    """
    if not context:
        return False
    text = context.get("user_message") or ""
    return jailbreak_triggered(text)


@action(is_system_action=True)
async def sniper_memory_grounding_check(context: Optional[dict] = None, **kwargs) -> bool:
    """
    Returns True if response is sufficiently grounded in Tier-2 (Chroma) or compliance RAG text.
    If should_fact_check is False in context, always returns True.
    """
    if not context:
        return True
    user_message = context.get("user_message") or ""
    if not should_fact_check_heuristic(user_message):
        # Python pipeline should set $should_fact_check; double-check here.
        if context.get("should_fact_check") is not True:
            return True

    try:
        mem = query_memory(user_message, recent_messages=None)
    except Exception as e:
        log.warning("[SNIPER] memory query failed in grounding check: %s", e)
        return False

    lt = (mem.get("long_term") or "").strip()
    comp = (mem.get("compliance") or "").strip()
    ok = len(lt) >= 40 or len(comp) >= 40
    if not ok:
        log.info("[SNIPER] Grounding check failed (insufficient long_term/compliance)")
    return ok
