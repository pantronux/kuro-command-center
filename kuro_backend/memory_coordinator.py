"""
Unified Memory Coordinator — single orchestration surface for memory-related reads
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

import hashlib
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)
logger.propagate = False

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

    recent_messages = memory_manager.get_short_term(persona_scope=persona_mode)
    memory = memory_manager.query_memory(
        user_input,
        recent_messages=recent_messages,
        persona_scope=persona_mode,
        include_compliance=not bool(compliance_data),
    )
    memory_injection = memory_manager.format_memory_with_temporal_grounding(memory)

    mem0_context_block = None
    if mem0_retrieved_memories:
        mem0_context_block = perpetual_memory.perpetual_memory.format_memories_for_context(
            mem0_retrieved_memories
        )
        if mem0_context_block:
            logger.info(
                "[MEMORY_COORD] build_context persona=%s mem0_chars=%s",
                persona_mode,
                len(mem0_context_block),
            )

    referent_grounding_block = None
    if include_referent_grounding:
        referent_grounding_block = build_referent_grounding_block(
            user_input,
            persona_mode,
            chat_platform=chat_platform,
        )

    return {
        "recent_messages": recent_messages,
        "memory_injection": memory_injection,
        "mem0_context_block": mem0_context_block,
        "referent_grounding_block": referent_grounding_block,
    }


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
