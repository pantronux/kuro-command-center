"""
Sniper guardrails orchestration.

NeMo `RailsConfig` + YAML prompts live in / `kuro_nemo_guardrails` (folder must not be named
`guardrails` — that collides with Colang's `import guardrails`).

The production hot path uses Python + `google.genai` for self-checks so we avoid Colang 2.x
`LLMRails.generate()` pulling in dialog / user-intent LLM calls after input rails (broken with
Gemini list responses in NeMo 0.21). Colang files remain for documentation / future NeMo server use.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types

from kuro_backend.config import PRIMARY_MODEL, settings
from kuro_backend.guardrails import sniper_context as sniper_ctx
from kuro_backend.guardrails.jailbreak_precheck import precheck_jailbreak

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_DIR = "kuro_nemo_guardrails"
_NEMO_IMPORT_OK: Optional[bool] = None
_NEMO_MISSING_LOGGED = False


def _nemoguardrails_available() -> bool:
    """True if nemoguardrails is installed (cached). YAML self-check prompts require it."""
    global _NEMO_IMPORT_OK
    if _NEMO_IMPORT_OK is None:
        try:
            import nemoguardrails  # noqa: F401

            _NEMO_IMPORT_OK = True
        except ImportError:
            _NEMO_IMPORT_OK = False
    return _NEMO_IMPORT_OK


def _warn_nemoguardrails_missing_once() -> None:
    global _NEMO_MISSING_LOGGED
    if _NEMO_MISSING_LOGGED:
        return
    _NEMO_MISSING_LOGGED = True
    logger.warning(
        "[SNIPER] nemoguardrails is not installed; input/output YAML self-checks are skipped. "
        "Install: pip install 'nemoguardrails>=0.21.0,<0.22'"
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def guardrails_config_path() -> Path:
    return _repo_root() / os.environ.get("KURO_NEMO_GUARDRAILS_DIR", _DEFAULT_CONFIG_DIR)


@lru_cache(maxsize=1)
def _rails_config():
    if not _nemoguardrails_available():
        raise ModuleNotFoundError("nemoguardrails")
    from nemoguardrails.rails.llm.config import RailsConfig

    return RailsConfig.from_path(str(guardrails_config_path()))


@lru_cache(maxsize=1)
def _task_manager():
    if not _nemoguardrails_available():
        raise ModuleNotFoundError("nemoguardrails")
    from nemoguardrails.llm.taskmanager import LLMTaskManager

    return LLMTaskManager(_rails_config())


def _yes_blocks_self_check(answer: str) -> bool:
    """NeMo self_check_*: Yes => block. Normalise Gemini / list-shaped text."""
    if not answer:
        return False
    t = answer.strip().lower()
    t = re.sub(r"\W+", " ", t)
    words = t.split()[:3]
    if not words:
        return False
    if words[0] == "yes":
        return True
    if words[0] == "no":
        return False
    if "unsafe" in words or "block" == words[0]:
        return True
    if "safe" in words[:2] and "unsafe" not in t:
        return False
    return False


def _guardrails_generate_config(max_tokens: int) -> types.GenerateContentConfig:
    """Optional Gemini context cache for static NeMo self-check prompts (set GEMINI_CACHED_CONTENT)."""
    cc = getattr(settings, "GEMINI_CACHED_CONTENT", "") or ""
    base = {"temperature": 0.0, "max_output_tokens": max_tokens}
    if cc:
        base["cached_content"] = cc
    return types.GenerateContentConfig(**base)


def _gemini_short_answer(prompt: str, max_tokens: int = 128) -> str:
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    r = client.models.generate_content(
        model=PRIMARY_MODEL,
        contents=prompt,
        config=_guardrails_generate_config(max_tokens),
    )
    text = (r.text or "").strip()
    if not text and r.candidates:
        cand = r.candidates[0]
        content = getattr(cand, "content", None)
        parts_list = getattr(content, "parts", None) if content else None
        if parts_list:
            parts = []
            for c in parts_list:
                if hasattr(c, "text") and c.text:
                    parts.append(c.text)
            text = " ".join(parts).strip()
    return text


async def _gemini_short_answer_async(prompt: str, max_tokens: int = 128) -> str:
    """Run sync Gemini client off the event loop (streaming/SSE path)."""
    return await asyncio.to_thread(_gemini_short_answer, prompt, max_tokens)


def self_check_input_python(user_message: str, is_habit_report: bool) -> Optional[str]:
    """Return refusal string if blocked; None if OK."""
    if is_habit_report:
        return None
    if not _nemoguardrails_available():
        _warn_nemoguardrails_missing_once()
        return None
    try:
        from nemoguardrails.llm.types import Task

        tm = _task_manager()
        prompt = tm.render_task_prompt(
            task=Task.SELF_CHECK_INPUT,
            context={"user_input": user_message},
        )
        ans = _gemini_short_answer(prompt)
        logger.debug("[SNIPER] self_check_input raw: %r", ans)
        if _yes_blocks_self_check(ans):
            return "I'm sorry, I can't respond to that."
    except ModuleNotFoundError:
        _warn_nemoguardrails_missing_once()
    except Exception as e:
        logger.exception("[SNIPER] self_check_input failed (allowing): %s", e)
    return None


async def self_check_input_python_async(user_message: str, is_habit_report: bool) -> Optional[str]:
    if is_habit_report:
        return None
    if not _nemoguardrails_available():
        _warn_nemoguardrails_missing_once()
        return None
    try:
        from nemoguardrails.llm.types import Task

        tm = _task_manager()
        prompt = tm.render_task_prompt(
            task=Task.SELF_CHECK_INPUT,
            context={"user_input": user_message},
        )
        ans = await _gemini_short_answer_async(prompt)
        logger.debug("[SNIPER] self_check_input raw: %r", ans)
        if _yes_blocks_self_check(ans):
            return "I'm sorry, I can't respond to that."
    except ModuleNotFoundError:
        _warn_nemoguardrails_missing_once()
    except Exception as e:
        logger.exception("[SNIPER] self_check_input failed (allowing): %s", e)
    return None


def memory_grounding_ok(user_message: str) -> bool:
    from kuro_backend.memory_manager import query_memory

    mem = query_memory(user_message, recent_messages=None)
    lt = (mem.get("long_term") or "").strip()
    comp = (mem.get("compliance") or "").strip()
    return len(lt) >= 40 or len(comp) >= 40


def _assistant_looks_like_tool_mutation_confirmation(assistant_message: str) -> bool:
    """True when the model already surfaced a reminder/habit tool outcome — do not replace with fact refusal."""
    if not assistant_message:
        return False
    s = assistant_message
    low = s.lower()
    if "reminder_id" in s:
        return True
    if "saya catat pengingat" in low or "catat pengingat untuk" in low:
        return True
    if "benar, master?" in low and "pengingat" in low:
        return True
    if "✅" in s and "habit" in low and ("dicatat" in low or "selesai" in low):
        return True
    if "sudah dicatat selesai" in low:
        return True
    return False


def sniper_fact_gate_python(user_message: str) -> Optional[str]:
    """If fact-check heuristic fires and memory lacks support, return canned refusal."""
    if not sniper_ctx.should_fact_check_heuristic(user_message):
        return None
    if memory_grounding_ok(user_message):
        return None
    entity = sniper_ctx.extract_entity_hint(user_message)
    return f"Saya tidak memiliki data faktual mengenai {entity} tersebut, Pantronux."


def self_check_output_python(user_message: str, bot_message: str) -> Optional[str]:
    """Return replacement refusal if output blocked; None if OK."""
    if not _nemoguardrails_available():
        _warn_nemoguardrails_missing_once()
        return None
    try:
        from nemoguardrails.llm.types import Task

        tm = _task_manager()
        prompt = tm.render_task_prompt(
            task=Task.SELF_CHECK_OUTPUT,
            context={"bot_response": bot_message, "user_input": user_message},
        )
        ans = _gemini_short_answer(prompt)
        logger.debug("[SNIPER] self_check_output raw: %r", ans)
        if _yes_blocks_self_check(ans):
            return "I'm sorry, I can't respond to that."
    except ModuleNotFoundError:
        _warn_nemoguardrails_missing_once()
    except Exception as e:
        logger.exception("[SNIPER] self_check_output failed (allowing): %s", e)
    return None


async def self_check_output_python_async(user_message: str, bot_message: str) -> Optional[str]:
    if not _nemoguardrails_available():
        _warn_nemoguardrails_missing_once()
        return None
    try:
        from nemoguardrails.llm.types import Task

        tm = _task_manager()
        prompt = tm.render_task_prompt(
            task=Task.SELF_CHECK_OUTPUT,
            context={"bot_response": bot_message, "user_input": user_message},
        )
        ans = await _gemini_short_answer_async(prompt)
        logger.debug("[SNIPER] self_check_output raw: %r", ans)
        if _yes_blocks_self_check(ans):
            return "I'm sorry, I can't respond to that."
    except ModuleNotFoundError:
        _warn_nemoguardrails_missing_once()
    except Exception as e:
        logger.exception("[SNIPER] self_check_output failed (allowing): %s", e)
    return None


def sniper_precheck_or_block(message: str) -> Optional[str]:
    return precheck_jailbreak(message)


def sniper_validate_and_maybe_block_input(message: str) -> Optional[str]:
    hit = sniper_precheck_or_block(message)
    if hit:
        return hit
    ctx = sniper_ctx.build_sniper_context(message)
    return self_check_input_python(message, bool(ctx.get("is_habit_report")))


def sniper_postprocess_output(user_message: str, assistant_message: str) -> str:
    """Apply fact gate + output self-check. Stream entrypoints chunk the returned string after this (see langgraph_core._iter_sse_text_chunks)."""
    if assistant_message is None:
        assistant_message = ""
    if not assistant_message:
        return assistant_message
    ctx = sniper_ctx.build_sniper_context(user_message)
    fact_hit = None
    if ctx.get("should_fact_check") and not _assistant_looks_like_tool_mutation_confirmation(
        assistant_message
    ):
        fact_hit = sniper_fact_gate_python(user_message)
    if fact_hit:
        return fact_hit
    blocked = self_check_output_python(user_message, assistant_message)
    if blocked:
        return blocked
    return assistant_message


async def sniper_validate_and_maybe_block_input_async(message: str) -> Optional[str]:
    """Non-blocking on event loop: jailbreak sync; Gemini self-check in thread pool."""
    hit = sniper_precheck_or_block(message)
    if hit:
        return hit
    ctx = sniper_ctx.build_sniper_context(message)
    return await self_check_input_python_async(message, bool(ctx.get("is_habit_report")))


async def sniper_postprocess_output_async(user_message: str, assistant_message: str) -> str:
    if assistant_message is None:
        assistant_message = ""
    if not assistant_message:
        return assistant_message
    ctx = sniper_ctx.build_sniper_context(user_message)
    if ctx.get("should_fact_check") and not _assistant_looks_like_tool_mutation_confirmation(
        assistant_message
    ):
        fact_hit = await asyncio.to_thread(sniper_fact_gate_python, user_message)
        if fact_hit:
            return fact_hit
    blocked = await self_check_output_python_async(user_message, assistant_message)
    if blocked:
        return blocked
    return assistant_message
