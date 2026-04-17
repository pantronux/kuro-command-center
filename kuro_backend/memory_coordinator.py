"""
Kuro AI V5.5 — Unified Memory Coordinator — single orchestration surface for memory-related reads
and post-response writes across short-term, Chroma, Mem0, and SSOT revision (habits/reminders).

AUDIT — mutation entry points (update when adding routes or tools):
- Habits CRUD: main.py /api/habits -> core_service.add_habit_svc / update_habit_svc / delete_habit_svc (bump inside each svc)
- Habits: reminder_service -> core_service *_svc
- Raw core_service.add_habit / update_habit / delete_habit bypass bump — do not use from product code
- Long-term + Chroma summary: post-response worker -> execute_memory_write_task
- Mem0 extract: post-response worker + fast stream -> execute_mem0_extract_task (deduped)
- OpenClaw: advanced_execution_tool -> apply_openclaw_execution_result (revision when touched_* flags)
- Optional batch entry: record_mutation(domain=habits|long_term|mem0, ...)
- Deictic read path: build_referent_grounding_block, format_same_turn_attachment_index; apply_path_tokens_to_runtime (integrity + last_accessed_file)
- Vision bundle: build_gemini_contents_parts(text, image_paths) for LangGraph response_node
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)
logger.propagate = False

_MEM0_DEFAULT_TIMEOUT_SEC = float(os.getenv("KURO_MEM0_TIMEOUT_SEC", "3.0"))
_MEM0_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="kuro-mem0"
)

# Dedicated pool for parallel context fan-out (SQLite + Chroma + referent).
# Sized small because each call is I/O bound but we don't want to starve the
# Mem0 pool.
_CONTEXT_FANOUT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="kuro-ctx"
)
_CONTEXT_FETCH_TIMEOUT_SEC = float(os.getenv("KURO_CONTEXT_FETCH_TIMEOUT_SEC", "1.5"))


def _parallel_gather_sync(
    tasks: Dict[str, Any],
    *,
    timeout_s: float = _CONTEXT_FETCH_TIMEOUT_SEC,
    default: Any = None,
) -> Dict[str, Any]:
    """Run a dict of zero-arg callables concurrently and return their results.

    Returns ``default`` (or ``None``) for any task that times out or raises,
    so callers can always assume every requested key is present. This makes
    the helper safe to drop into hot paths where partial failures must degrade
    gracefully rather than bubble up.
    """
    if not tasks:
        return {}
    results: Dict[str, Any] = {}
    future_map: Dict[concurrent.futures.Future, str] = {}
    for name, fn in tasks.items():
        try:
            future_map[_CONTEXT_FANOUT_EXECUTOR.submit(fn)] = name
        except RuntimeError:
            # Executor shutting down — run inline as last resort.
            try:
                results[name] = fn()
            except Exception:
                results[name] = default
    try:
        done, not_done = concurrent.futures.wait(
            future_map.keys(), timeout=timeout_s, return_when=concurrent.futures.ALL_COMPLETED
        )
    except Exception as exc:
        logger.warning("[CONTEXT_FANOUT] wait() error: %s", exc)
        done, not_done = set(future_map.keys()), set()
    for fut in done:
        name = future_map[fut]
        try:
            results[name] = fut.result()
        except Exception as exc:
            logger.warning("[CONTEXT_FANOUT] task %s failed: %s", name, exc)
            results[name] = default
    for fut in not_done:
        name = future_map[fut]
        logger.warning("[CONTEXT_FANOUT] task %s timed out after %.2fs", name, timeout_s)
        results[name] = default
        fut.cancel()
    # Fill in missing keys (should be none, defensive)
    for name in tasks:
        results.setdefault(name, default)
    return results

_DEICTIC_HINT_RE = re.compile(
    r"\b(ini|itu|tersebut|tadi|barusan|yang\s+dimaksud|maksudnya|gambar\s+ini|"
    r"gambar\s+itu|lampiran|terlampir|yang\s+baru\s+saja|nomor\s+[12])\b",
    re.IGNORECASE,
)
_PATH_OR_BASENAME_RE = re.compile(
    r"(?P<abs>/[^\s]+?\.(?:png|jpe?g|gif|webp))\b|(?P<base>[\w\-]+\.(?:png|jpe?g|gif|webp))\b",
    re.IGNORECASE,
)

_MEM0_FINGERPRINTS: Dict[str, float] = {}
_MEM0_DEDUPE_TTL_SEC = 300.0
_FP_LOCK = threading.Lock()


def _mem0_fingerprint(user_input: str, final_response: str) -> str:
    blob = f"{user_input}\n---\n{final_response}"
    return hashlib.sha256(blob.encode("utf-8", errors="replace")).hexdigest()


def _mem0_should_skip_duplicate(fp: str) -> bool:
    now = time.monotonic()
    with _FP_LOCK:
        cutoff = now - _MEM0_DEDUPE_TTL_SEC
        stale = [k for k, t in _MEM0_FINGERPRINTS.items() if t < cutoff]
        for k in stale:
            del _MEM0_FINGERPRINTS[k]
        if fp in _MEM0_FINGERPRINTS:
            return True
        _MEM0_FINGERPRINTS[fp] = now
    return False


def _trace_coordinator_span(op: str, attrs: Dict[str, Any]) -> None:
    """Best-effort Phoenix span attributes (no-op if tracer unavailable)."""
    try:
        from kuro_backend import observability
        from opentelemetry import trace

        tracer = observability.get_tracer()
        if tracer is None:
            return
        span = trace.get_current_span()
        if span is None or not span.is_recording():
            return
        span.set_attribute("memory_coordinator.op", op)
        for k, v in attrs.items():
            if v is None:
                continue
            span.set_attribute(f"memory_coordinator.{k}", str(v)[:512])
    except Exception:
        pass


def _trace_memory_layer(domain: str, source: str, ok: bool, revision_after: Optional[str] = None) -> None:
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span is None or not span.is_recording():
            return
        span.set_attribute("memory.domain", domain[:256])
        span.set_attribute("memory.source", source[:256])
        span.set_attribute("memory.ok", ok)
        if revision_after is not None:
            span.set_attribute("memory.revision_after", str(revision_after)[:64])
    except Exception:
        pass


def user_message_looks_deictic(user_input: str) -> bool:
    return bool(user_input and _DEICTIC_HINT_RE.search(user_input))


def format_same_turn_attachment_index(file_attachments: Sequence[Dict[str, Any]]) -> str:
    if not file_attachments:
        return ""
    lines = [
        "[ATTACHMENT_ORDER_THIS_REQUEST]",
        "Gunakan urutan ini untuk merujuk 'gambar/file pertama, kedua, ...'. "
        "Nama stored_filename adalah nama unik di server.",
    ]
    for i, att in enumerate(file_attachments, 1):
        lines.append(
            f"{i}. type={att.get('type') or 'file'} "
            f"stored_filename={att.get('stored_filename') or ''} "
            f"original_filename={att.get('original_filename') or ''}"
        )
    return "\n".join(lines)


def _history_has_user_attachments(history: List[Dict[str, Any]]) -> bool:
    for row in history:
        if row.get("role") == "user" and row.get("attachments"):
            return True
    return False


def build_referent_grounding_block(
    user_input: str,
    persona_mode: str,
    *,
    chat_platform: Optional[str] = None,
    history_limit: int = 16,
) -> Optional[str]:
    from kuro_backend import chat_history

    deictic = user_message_looks_deictic(user_input)
    history = chat_history.get_history(
        limit=history_limit,
        offset=0,
        platform=chat_platform,
        persona=persona_mode,
    )
    has_att = _history_has_user_attachments(history)

    if not deictic and not has_att:
        return None

    lines: List[str] = [
        "[RECENT_ATTACHMENTS_GROUNDING]",
        "Aturan: untuk 'ini/itu/gambar tadi', rujuk entri user terbaru yang punya lampiran; "
        "jika masih ambigu, tanyakan jangan menebak.",
    ]
    found_any = False
    idx = 0
    for row in history:
        if row.get("role") != "user":
            continue
        attachments = row.get("attachments") or []
        if not attachments:
            continue
        idx += 1
        found_any = True
        snippet = (row.get("content") or "").strip().replace("\n", " ")[:120]
        att_display = ", ".join(str(a) for a in attachments[:12])
        if len(attachments) > 12:
            att_display += ", ..."
        lines.append(f"- user_turn#{idx} attachments=[{att_display}] snippet={snippet!r}")

    if not found_any:
        lines.append(
            "- (Tidak ada lampiran di riwayat terbaru.) "
            "Jika Master merujuk gambar, minta unggah ulang atau sebutkan nama file."
        )

    block = "\n".join(lines)
    _trace_coordinator_span(
        "referent_grounding",
        {"persona": persona_mode, "deictic": deictic, "has_attachments_in_history": has_att},
    )
    _trace_memory_layer("referent_grounding", "graph_read", True)
    return block


def apply_path_tokens_to_runtime(user_input: str, persona_mode: str) -> None:
    from kuro_backend import chat_history
    from kuro_backend import memory_manager

    if not user_input:
        return
    resolved: List[str] = []
    for m in _PATH_OR_BASENAME_RE.finditer(user_input):
        abs_p = m.group("abs")
        base = m.group("base")
        candidate = None
        if abs_p and os.path.isfile(abs_p):
            candidate = os.path.abspath(abs_p)
        elif base:
            rows = chat_history.get_uploaded_file_integrity(stored_filename=base, limit=3)
            for r in rows:
                sp = r.get("stored_path")
                if sp and os.path.isfile(sp):
                    candidate = os.path.abspath(sp)
                    break
        if candidate:
            resolved.append(candidate)
    if resolved:
        memory_manager.set_runtime_context_value("last_accessed_file", resolved[-1])
        logger.debug("[MEMORY_COORD] last_accessed_file=%s", resolved[-1])


def build_gemini_contents_parts(full_text: str, image_paths: Optional[Sequence[str]]) -> List[Any]:
    from google.genai import types

    from kuro_backend.core import _encode_image_to_base64, _get_mime_type

    parts: List[Any] = [types.Part(text=full_text)]
    if not image_paths:
        return parts
    for raw_path in image_paths:
        if not raw_path:
            continue
        path = os.path.abspath(os.path.expanduser(str(raw_path)))
        if not os.path.isfile(path):
            logger.warning("[MEMORY_COORD] vision skip missing file: %s", path)
            continue
        try:
            image_b64 = _encode_image_to_base64(path)
            parts.append(
                types.Part(
                    inline_data=types.Blob(
                        mime_type=_get_mime_type(path),
                        data=image_b64,
                    )
                )
            )
        except Exception as exc:
            logger.warning("[MEMORY_COORD] vision skip read error %s: %s", path, exc)
    return parts


# ---------------------------------------------------------------------------
# Sliding-Window Summarization (P2.1)
# ---------------------------------------------------------------------------
# Compress older short-term turns into a single summary block so the prompt
# stays small while historical context is preserved. Summaries are cached in
# SQLite (one row per persona) keyed by the last included entry id, so we only
# regenerate when genuinely new turns have arrived.

_SLIDING_WINDOW_MAX_TURNS = int(os.getenv("KURO_SHORT_TERM_MAX_TURNS", "6"))
_SLIDING_WINDOW_MAX_CHARS = int(os.getenv("KURO_SHORT_TERM_MAX_CHARS", "1200"))
_SLIDING_WINDOW_SUMMARY_MAX_CHARS = int(os.getenv("KURO_SHORT_TERM_SUMMARY_MAX_CHARS", "900"))


def _format_entries_for_prompt(entries: Sequence[Dict[str, Any]], *, max_chars_per_entry: int = 200) -> str:
    lines: List[str] = []
    for entry in entries:
        role = "User" if entry.get("role") == "user" else "Kuro"
        content = (entry.get("content") or "")[:max_chars_per_entry]
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


_summary_genai_client = None
_summary_genai_client_lock = threading.Lock()


def _get_summary_genai_client():
    """Lazy-initialized standalone Gemini client used by the summarizer.

    Kept separate from :func:`langgraph_core._get_genai_client` to avoid a
    circular import (``langgraph_core`` imports this module at module load).
    """
    global _summary_genai_client
    if _summary_genai_client is not None:
        return _summary_genai_client
    with _summary_genai_client_lock:
        if _summary_genai_client is None:
            from google import genai
            from kuro_backend.config import settings
            _summary_genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _summary_genai_client


def _summarize_older_turns(older_entries: Sequence[Dict[str, Any]]) -> str:
    """Synchronous Gemini call that produces a compact Indo summary of older
    turns. Returns empty string on any failure so caller can fall back to the
    uncompressed path."""
    if not older_entries:
        return ""
    try:
        from google.genai import types as genai_types
        from kuro_backend.config import PRIMARY_MODEL

        client = _get_summary_genai_client()

        convo_blob = _format_entries_for_prompt(older_entries, max_chars_per_entry=250)
        system_instruction = (
            "Anda adalah kompresor percakapan. Rangkum percakapan berikut dalam "
            "3-5 kalimat Bahasa Indonesia padat: topik utama, keputusan atau fakta "
            "penting yang muncul, nama/referensi spesifik. JANGAN menambah fakta "
            "yang tidak ada. JANGAN pakai bullet. Maksimum 220 token."
        )
        response = client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=convo_blob,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.0,
                top_p=0.1,
                top_k=1,
                max_output_tokens=220,
            ),
        )
        text = getattr(response, "text", "") or ""
        return text.strip()[:_SLIDING_WINDOW_SUMMARY_MAX_CHARS]
    except Exception as exc:
        logger.warning("[SLIDING_WINDOW] summary generation failed: %s", exc)
        return ""


def build_compressed_short_term_text(
    persona_scope: str,
    *,
    max_turns: int = _SLIDING_WINDOW_MAX_TURNS,
    max_chars: int = _SLIDING_WINDOW_MAX_CHARS,
) -> str:
    """Return a compressed short-term block suitable for prompt injection.

    - If <= ``max_turns`` entries exist, returns the verbatim recent turns.
    - Otherwise, compresses older turns into a cached ``[SUMMARY earlier_conversation]``
      block and prepends it before the verbatim latest ``max_turns``.

    The summary is cached per persona keyed by the highest included entry id so
    we only regenerate when new turns push past the window.
    """
    from kuro_backend import memory_manager

    entries = memory_manager.get_short_term_with_ids(persona_scope=persona_scope)
    if not entries:
        return ""
    if len(entries) <= max_turns:
        return _format_entries_for_prompt(entries, max_chars_per_entry=160)

    older = entries[:-max_turns]
    recent = entries[-max_turns:]
    older_max_id = max((e.get("id") or 0) for e in older)

    cached = memory_manager.get_short_term_summary(persona_scope)
    if cached and cached.get("last_entry_id", 0) >= older_max_id and cached.get("summary"):
        summary_text = cached["summary"]
    else:
        summary_text = _summarize_older_turns(older)
        if summary_text:
            try:
                memory_manager.upsert_short_term_summary(persona_scope, older_max_id, summary_text)
            except Exception as exc:
                logger.warning("[SLIDING_WINDOW] upsert cache failed: %s", exc)

    if not summary_text:
        # Fallback: concat recent only so we never exceed the window even
        # when summarization fails.
        return _format_entries_for_prompt(recent, max_chars_per_entry=160)

    recent_text = _format_entries_for_prompt(recent, max_chars_per_entry=160)
    compressed = f"[SUMMARY earlier_conversation]\n{summary_text}\n\n{recent_text}"
    if len(compressed) > max_chars:
        # Hard clamp in case summary + recent overshoot the budget.
        compressed = compressed[: max_chars - 3] + "..."
    return compressed


def build_context_for_llm(
    user_input: str,
    persona_mode: str,
    *,
    compliance_data: Optional[List[Any]] = None,
    mem0_retrieved_memories: Optional[List[Any]] = None,
    include_referent_grounding: bool = True,
    chat_platform: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Single read path: short-term + RAG memory + optional Mem0 block (same inputs as response_node / stream).
    Returns keys: recent_messages, memory_injection, mem0_context_block, referent_grounding_block.
    """
    from kuro_backend import memory_manager
    from kuro_backend import perpetual_memory

    _trace_coordinator_span(
        "build_context_for_llm",
        {"persona": persona_mode, "has_compliance": bool(compliance_data), "mem0_n": len(mem0_retrieved_memories or [])},
    )

    # P1.1 — Parallelize independent I/O. `get_short_term` (SQLite), the Mem0
    # formatter (CPU-only but cheap), and the referent grounding block are
    # independent of each other. `query_memory` depends on `recent_messages`
    # so it runs after the short-term fetch.
    parallel_tasks: Dict[str, Any] = {
        "short_term": lambda: memory_manager.get_short_term(persona_scope=persona_mode),
    }
    if include_referent_grounding:
        parallel_tasks["referent"] = lambda: build_referent_grounding_block(
            user_input,
            persona_mode,
            chat_platform=chat_platform,
        )
    if mem0_retrieved_memories:
        parallel_tasks["mem0_fmt"] = lambda: perpetual_memory.perpetual_memory.format_memories_for_context(
            mem0_retrieved_memories
        )

    fan_out = _parallel_gather_sync(parallel_tasks)
    recent_messages = fan_out.get("short_term") or []
    referent_grounding_block = fan_out.get("referent") if include_referent_grounding else None
    mem0_context_block = fan_out.get("mem0_fmt") if mem0_retrieved_memories else None
    if mem0_context_block:
        logger.info(
            "[MEMORY_COORD] build_context persona=%s mem0_chars=%s",
            persona_mode,
            len(mem0_context_block),
        )

    # query_memory depends on recent_messages (used for expansion), so it runs
    # after the fan-out completes. Chroma calls are already internally parallel.
    memory = memory_manager.query_memory(
        user_input,
        recent_messages=recent_messages,
        persona_scope=persona_mode,
        include_compliance=not bool(compliance_data),
    )
    # P2.1 — replace the short-term block with a sliding-window-compressed
    # version when the history exceeds the turn budget. Compressed summary is
    # cached per-persona so we pay the LLM cost only when new turns arrive.
    try:
        compressed_short_term = build_compressed_short_term_text(persona_mode)
        if compressed_short_term:
            memory["short_term"] = compressed_short_term
    except Exception as exc:
        logger.warning("[SLIDING_WINDOW] fallback to raw short-term: %s", exc)

    memory_injection = memory_manager.format_memory_with_temporal_grounding(memory)

    return {
        "recent_messages": recent_messages,
        "memory_injection": memory_injection,
        "mem0_context_block": mem0_context_block,
        "referent_grounding_block": referent_grounding_block,
    }


async def build_context_for_llm_async(
    user_input: str,
    persona_mode: str,
    *,
    compliance_data: Optional[List[Any]] = None,
    mem0_retrieved_memories: Optional[List[Any]] = None,
    include_referent_grounding: bool = True,
    chat_platform: Optional[str] = None,
) -> Dict[str, Any]:
    """Async variant of :func:`build_context_for_llm`.

    Offloads the full sync build onto the fan-out pool so the FastAPI event
    loop never blocks on SQLite/Chroma I/O. Semantics are identical to the
    sync version — same keys, same trimming rules.
    """
    import asyncio

    return await asyncio.to_thread(
        build_context_for_llm,
        user_input,
        persona_mode,
        compliance_data=compliance_data,
        mem0_retrieved_memories=mem0_retrieved_memories,
        include_referent_grounding=include_referent_grounding,
        chat_platform=chat_platform,
    )


# ---------------------------------------------------------------------------
# P1.2 — Mem0 prefetch fan-out
# ---------------------------------------------------------------------------
# The `memory_retrieval_node` always calls Mem0 after the supervisor has
# already made a routing decision. If we kick off Mem0 retrieval *during*
# supervisor evaluation, it runs in parallel with SQLite/Chroma reads in
# downstream nodes. The prefetch cache is keyed by session id so different
# concurrent users don't collide.

_MEM0_PREFETCH_CACHE: Dict[str, concurrent.futures.Future] = {}
_MEM0_PREFETCH_LOCK = threading.Lock()
_MEM0_PREFETCH_TTL_S = 30.0
_MEM0_PREFETCH_TIMESTAMPS: Dict[str, float] = {}


def prefetch_mem0(session_id: str, user_input: str, *, limit: int = 5) -> None:
    """Kick off a Mem0 retrieval in the background, keyed by session.

    Safe to call multiple times — existing in-flight futures are preserved.
    Expired entries are reaped lazily to avoid unbounded growth.
    """
    if not session_id or not user_input:
        return
    from kuro_backend import perpetual_memory

    now = time.monotonic()
    with _MEM0_PREFETCH_LOCK:
        # Reap stale prefetches so the cache never leaks.
        stale = [
            sid for sid, ts in _MEM0_PREFETCH_TIMESTAMPS.items()
            if now - ts > _MEM0_PREFETCH_TTL_S
        ]
        for sid in stale:
            _MEM0_PREFETCH_CACHE.pop(sid, None)
            _MEM0_PREFETCH_TIMESTAMPS.pop(sid, None)
        if session_id in _MEM0_PREFETCH_CACHE:
            return
        try:
            future = _MEM0_EXECUTOR.submit(
                perpetual_memory.perpetual_memory.retrieve_memories,
                user_input,
                limit,
            )
        except RuntimeError:
            return
        _MEM0_PREFETCH_CACHE[session_id] = future
        _MEM0_PREFETCH_TIMESTAMPS[session_id] = now


def take_prefetched_mem0(
    session_id: str,
    *,
    timeout_s: float = _MEM0_DEFAULT_TIMEOUT_SEC,
) -> Optional[List[Dict[str, Any]]]:
    """Pop and await an in-flight Mem0 prefetch, or return ``None`` if absent."""
    with _MEM0_PREFETCH_LOCK:
        future = _MEM0_PREFETCH_CACHE.pop(session_id, None)
        _MEM0_PREFETCH_TIMESTAMPS.pop(session_id, None)
    if future is None:
        return None
    try:
        return future.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        logger.warning("[MEM0] prefetch timed out after %.2fs (session=%s)", timeout_s, session_id)
        future.cancel()
        return []
    except Exception as exc:
        logger.warning("[MEM0] prefetch failed (session=%s): %s", session_id, exc)
        return []


def safe_mem0_retrieve(
    user_input: str,
    *,
    limit: int = 5,
    timeout_s: float = _MEM0_DEFAULT_TIMEOUT_SEC,
) -> List[Dict[str, Any]]:
    """
    Hard-timeout Mem0 retrieval. Returns `[]` on timeout or any exception so
    LangGraph nodes degrade gracefully to short-term-only context.
    """
    if not user_input:
        return []
    from kuro_backend import perpetual_memory

    try:
        future = _MEM0_EXECUTOR.submit(
            perpetual_memory.perpetual_memory.retrieve_memories,
            user_input,
            limit,
        )
        result = future.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        logger.warning(
            "[MEMORY_COORD] mem0 retrieve timed out after %.2fs (query=%r)",
            timeout_s,
            (user_input or "")[:60],
        )
        _trace_memory_layer("mem0", "retrieve", ok=False)
        return []
    except Exception as exc:
        logger.warning("[MEMORY_COORD] mem0 retrieve failed: %s", exc)
        _trace_memory_layer("mem0", "retrieve", ok=False)
        return []

    _trace_memory_layer("mem0", "retrieve", ok=True)
    if isinstance(result, list):
        return result
    logger.warning("[MEMORY_COORD] mem0 retrieve returned non-list %s; coercing", type(result))
    return []


def execute_memory_write_task(
    user_input: str,
    final_response: str,
    persona_scope: str,
) -> None:
    """Post-response long-term + Chroma summary + master facts (was memory_write worker)."""
    from kuro_backend import memory_manager

    _trace_coordinator_span(
        "execute_memory_write_task",
        {"persona": persona_scope, "chars_in": len(user_input or ""), "chars_out": len(final_response or "")},
    )
    logger.info("[MEMORY_COORD] memory_write start persona=%s", persona_scope)
    memory_manager.add_long_term_v2(f"User: {user_input}\nKuro: {final_response}")
    memory_manager.summarize_conversation_to_chroma(persona_scope=persona_scope)
    memory_manager.detect_and_save_master_facts(user_input, final_response)
    logger.info("[MEMORY_COORD] memory_write done persona=%s", persona_scope)


def execute_mem0_extract_task(user_input: str, final_response: str) -> None:
    """Mem0 extract+store with dedupe (graph + fast path may enqueue similar payloads)."""
    from kuro_backend import perpetual_memory

    fp = _mem0_fingerprint(user_input, final_response)
    if _mem0_should_skip_duplicate(fp):
        logger.info("[MEMORY_COORD] mem0_extract skipped duplicate fp=%s...", fp[:12])
        return

    _trace_coordinator_span(
        "execute_mem0_extract_task",
        {"fp": fp[:16], "chars_in": len(user_input or ""), "chars_out": len(final_response or "")},
    )
    memories_to_store = perpetual_memory.perpetual_memory.extract_personal_info(
        user_input,
        final_response,
    )
    if memories_to_store and isinstance(memories_to_store, list):
        perpetual_memory.perpetual_memory.store_memories(memories_to_store)
        logger.info("[MEMORY_COORD] mem0_extract stored n=%s", len(memories_to_store))
    else:
        logger.debug("[MEMORY_COORD] mem0_extract nothing to store")


def habit_create(title: str, scheduled_time: str, category: str = "General", source: str = "web_api") -> int:
    """Strong-sync habit create; delegates to core_service.add_habit_svc (includes bump)."""
    from kuro_backend.services import core_service

    _trace_coordinator_span("habit_create", {"source": source, "title": title[:80]})
    hid = core_service.add_habit_svc(title, scheduled_time, category)
    rev = core_service.get_data_revision()
    logger.info("[MEMORY_COORD] habit_create id=%s revision=%s source=%s", hid, rev, source)
    return hid


def habit_update(habit_id: int, source: str = "web_api", **kwargs: Any) -> None:
    from kuro_backend.services import core_service

    _trace_coordinator_span("habit_update", {"source": source, "habit_id": habit_id})
    core_service.update_habit_svc(habit_id, **kwargs)
    logger.info("[MEMORY_COORD] habit_update id=%s revision=%s", habit_id, core_service.get_data_revision())


def habit_delete(habit_id: int, source: str = "web_api") -> None:
    from kuro_backend.services import core_service

    _trace_coordinator_span("habit_delete", {"source": source, "habit_id": habit_id})
    core_service.delete_habit_svc(habit_id)
    logger.info("[MEMORY_COORD] habit_delete id=%s revision=%s", habit_id, core_service.get_data_revision())


def record_mutation(
    *,
    domain: str,
    source: str,
    payload: Dict[str, Any],
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Orchestrated mutation entry (plan contract). Dispatches to existing helpers; bump stays inside *_svc.
    idempotency_key is accepted for forward-compatible dedupe (not yet enforced).
    """
    from kuro_backend.services import core_service as _cs

    _trace_coordinator_span(
        "record_mutation",
        {"domain": domain, "source": source, "idem": (idempotency_key or "")[:24]},
    )
    if idempotency_key:
        logger.debug("[MEMORY_COORD] record_mutation idempotency_key present")

    if domain == "habits":
        op = str(payload.get("op") or "create").lower()
        if op == "create":
            hid = habit_create(
                str(payload["title"]),
                str(payload["scheduled_time"]),
                category=str(payload.get("category") or "General"),
                source=source,
            )
            return {
                "ok": True,
                "revision": _cs.get_data_revision(),
                "canonical_record_id": str(hid),
            }
        if op == "update":
            habit_id = int(payload["habit_id"])
            fields = {
                k: v
                for k, v in payload.items()
                if k not in ("op", "habit_id") and v is not None
            }
            habit_update(habit_id, source=source, **fields)
            return {
                "ok": True,
                "revision": _cs.get_data_revision(),
                "canonical_record_id": str(habit_id),
            }
        if op == "delete":
            habit_id = int(payload["habit_id"])
            habit_delete(habit_id, source=source)
            return {
                "ok": True,
                "revision": _cs.get_data_revision(),
                "canonical_record_id": str(habit_id),
            }
        return {"ok": False, "error": f"unknown habits op: {op}", "revision": _cs.get_data_revision()}

    if domain == "long_term":
        from kuro_backend import memory_manager

        persona = payload.get("persona_scope") or memory_manager.get_active_persona()
        execute_memory_write_task(
            str(payload.get("user_input", "")),
            str(payload.get("final_response", "")),
            str(persona),
        )
        return {"ok": True, "revision": _cs.get_data_revision(), "canonical_record_id": None}

    if domain == "mem0":
        execute_mem0_extract_task(
            str(payload.get("user_input", "")),
            str(payload.get("final_response", "")),
        )
        return {"ok": True, "revision": _cs.get_data_revision(), "canonical_record_id": None}

    return {"ok": False, "error": f"unsupported domain: {domain}", "revision": _cs.get_data_revision()}


def apply_openclaw_execution_result(
    *,
    success: bool,
    skill_name: str,
    raw: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Centralize SSOT revision bump rules after OpenClaw tool execution.
    Mirrors previous advanced_execution_tool logic.
    """
    from kuro_backend.services import core_service

    should_bump = bool(
        raw.get("touched_habits")
        or raw.get("touched_reminders")
        or raw.get("ssot_bump_required")
        or raw.get("data_mutation")
    )
    if success and skill_name == "harvest_gemini_share":
        should_bump = True

    revision_bumped = False
    revision_error: Optional[str] = None
    if success and should_bump:
        try:
            core_service.bump_data_revision()
            revision_bumped = True
            _trace_coordinator_span(
                "openclaw_bump",
                {
                    "skill": skill_name,
                    "revision_after": core_service.get_data_revision(),
                    "touched_habits": bool(raw.get("touched_habits")),
                    "touched_reminders": bool(raw.get("touched_reminders")),
                },
            )
        except Exception as exc:
            revision_error = str(exc)
            logger.exception("[MEMORY_COORD] bump after OpenClaw failed: %s", exc)

    return {
        "should_bump_revision": should_bump,
        "revision_bumped": revision_bumped,
        "revision_error": revision_error,
    }
