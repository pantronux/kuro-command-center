"""
Kuro AI V6.0 Sovereign — Unified Memory Coordinator — single orchestration surface for memory-related reads
and post-response writes across short-term, Chroma, Mem0, and SSOT revision (finances/market).

- Long-term + Chroma summary: post-response worker -> execute_memory_write_task
- Mem0 extract: post-response worker + fast stream -> execute_mem0_extract_task (deduped)
- OpenClaw: advanced_execution_tool -> apply_openclaw_execution_result (revision when touched_* flags)
- Optional batch entry: record_mutation(domain=long_term|mem0, ...)
- Deictic read path: build_referent_grounding_block, format_same_turn_attachment_index; apply_path_tokens_to_runtime (integrity + last_accessed_file)
- Vision bundle: build_gemini_contents_parts(text, image_paths) for LangGraph response_node

--- Header Doc ---
Purpose: Central memory-read orchestration + post-response write fan-out across all memory tiers.
Caller: langgraph_core response_node, main.py chat routes, dreaming_worker, services/core_service.
Dependencies: memory_manager, perpetual_memory, finance_db, intelligence_engine, observability, Mem0 (optional).
Main Functions: build_context_for_llm(), post_response_memory_writes(), record_mutation(), build_gemini_contents_parts(), build_referent_grounding_block().
Side Effects: Reads + writes across sqlite + Mem0, Mem0 HTTP calls, SSoT revision bumps via core_service.bump_data_revision.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import collections
import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Sequence
from datetime import datetime

from kuro_backend.memory_validation import validate_memory_relevance
from kuro_backend.temporal_weighting import apply_temporal_decay_weighting
from kuro_backend.semantic_integrity import prevent_memory_mutation
from kuro_backend.contradiction_memory_guard import contradiction_score as memory_contradiction_score
from kuro_backend.intelligence.retrieval_quality import detect_context_bleed
from kuro_backend.memory_canonicalization import canonical_selection_score, canonicalize_memory_payload
from kuro_backend.cognitive_budget_engine import evaluate_budget

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

# chat_context auto-generation constants
from kuro_backend.config import settings
CHAT_CONTEXT_REFRESH_THRESHOLD = getattr(settings, "KURO_CHAT_CONTEXT_REFRESH_THRESHOLD", int(os.getenv("KURO_CHAT_CONTEXT_REFRESH_THRESHOLD", "20")))
CHAT_CONTEXT_MODEL = os.getenv("KURO_CHAT_CONTEXT_MODEL", "gemini-3-flash-preview")
_MEMORY_INTEGRITY_V2_ENABLED = os.getenv("KURO_MEMORY_INTEGRITY_V2_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
_CANVAS3_MEMORY_CANONICALIZATION_ENABLED = os.getenv("KURO_CANVAS3_MEMORY_CANONICALIZATION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
_CANVAS3_COGNITIVE_BUDGET_ENABLED = os.getenv("KURO_CANVAS3_COGNITIVE_BUDGET_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
_INGESTION_BRIDGE_ENABLED = bool(getattr(settings, "KURO_INGESTION_BRIDGE_ENABLED", True))
_INGESTION_BRIDGE_TOP_K = int(getattr(settings, "KURO_INGESTION_BRIDGE_TOP_K", 5))
_INGESTION_BRIDGE_MAX_CHARS = int(getattr(settings, "KURO_INGESTION_BRIDGE_MAX_CHARS", 2500))
_INGESTION_BRIDGE_MIN_SCORE = float(getattr(settings, "KURO_INGESTION_BRIDGE_MIN_SCORE", 0.28))
_MEM0_USER_LOCKS: Dict[str, threading.Lock] = {}
_MEM0_QUEUE_DEDUP: set[str] = set()
_MEM0_PENDING_QUEUE: Dict[str, "collections.deque[tuple[str, str, str, Any]]"] = (
    collections.defaultdict(collections.deque)
)
_MEM0_QUEUE_LOCK = threading.Lock()
_MEM0_PENDING_PER_USER_MAX = int(os.getenv("KURO_MEM0_PENDING_PER_USER_MAX", "100"))
_user_locks: dict[str, asyncio.Lock] = {}


def _get_user_lock(username: str) -> asyncio.Lock:
    """Compatibility async lock map for per-user async write-serialization."""
    if username not in _user_locks:
        _user_locks[username] = asyncio.Lock()
    return _user_locks[username]


def _get_mem0_user_lock(username: str) -> threading.Lock:
    lock = _MEM0_USER_LOCKS.get(username)
    if lock is None:
        lock = threading.Lock()
        _MEM0_USER_LOCKS[username] = lock
    return lock


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
    r"gambar\s+itu|lampiran|terlampir|yang\s+baru\s+saja|nomor\s+[12]|"
    r"edit\s+the\s+previous\s+result|edit\s+previous|add\s+to\s+that|"
    r"tambah(kan)?\s+ke\s+yang\s+sebelumnya|edit\s+hasil\s+sebelumnya)\b",
    re.IGNORECASE,
)
_PATH_OR_BASENAME_RE = re.compile(
    r"(?P<abs>/[^\s]+?\.(?:png|jpe?g|gif|webp))\b|(?P<base>[\w\-]+\.(?:png|jpe?g|gif|webp))\b",
    re.IGNORECASE,
)

_MEM0_FINGERPRINTS: Dict[str, float] = {}
_MEM0_DEDUPE_TTL_SEC = 300.0
_FP_LOCK = threading.Lock()


def _mem0_fingerprint(
    user_input: str,
    final_response: str,
    runtime_id: str = "",
    runtime_namespace: str = "",
) -> str:
    blob = (
        f"{runtime_id}\n{runtime_namespace}\n"
        f"{user_input}\n---\n{final_response}"
    )
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
    username: str = "Pantronux",
    chat_id: Optional[str] = None,
) -> Optional[str]:
    from kuro_backend import chat_history
    from kuro_backend import memory_manager

    deictic = user_message_looks_deictic(user_input)
    history = chat_history.get_history(
        limit=history_limit,
        offset=0,
        platform=chat_platform,
        persona=persona_mode,
        username=username,
        chat_id=chat_id,
    )
    has_att = _history_has_user_attachments(history)

    if not deictic and not has_att:
        return None

    lines: List[str] = [
        "[RECENT_ATTACHMENTS_GROUNDING]",
        "Aturan: untuk 'ini/itu/gambar tadi', rujuk entri user terbaru yang punya lampiran; "
        "jika masih ambigu, tanyakan jangan menebak.",
    ]
    raw_session_state = memory_manager.get_runtime_context_value("current_session_state", "", username=username)
    if raw_session_state:
        try:
            session_state = json.loads(raw_session_state)
            if isinstance(session_state, dict):
                lines.append(
                    "Prioritas utama: gunakan CURRENT_SESSION_STATE berikut sebelum memakai memori lain."
                )
                lines.append(
                    f"- request_id={session_state.get('request_id', '')} user_message={session_state.get('user_message', '')!r}"
                )
                extractions = session_state.get("file_extractions") or []
                for item in extractions[:6]:
                    fname = item.get("original_filename", "")
                    content = str(item.get("extracted_content", ""))
                    lines.append(f"- current_session_file={fname!r}\n[RAW_CONTENT_START]\n{content}\n[RAW_CONTENT_END]")
        except Exception as exc:
            logger.debug("[MEMORY_COORD] current_session_state parse skipped: %s", exc)

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


# ---------------------------------------------------------------------------
# Persona-Aware Structured Summarizer (V5.5)
# ---------------------------------------------------------------------------
# Gemini `response_schema` gives us auditable JSON output so Advisor's
# Novelty Points and Tactical's Technical Specs survive compression. The same
# schema is returned for every persona; persona-specific sections are
# populated based on the dispatched instruction.

_STRUCTURED_SUMMARY_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "topic": {"type": "string"},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "entities": {"type": "array", "items": {"type": "string"}},
        "open_questions": {"type": "array", "items": {"type": "string"}},
        "novelty_points": {"type": "array", "items": {"type": "string"}},
        "technical_specs": {"type": "array", "items": {"type": "string"}},
        "compliance_refs": {"type": "array", "items": {"type": "string"}},
        "tone_markers": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["topic"],
}

_EMPTY_SUMMARY_JSON: Dict[str, Any] = {
    "topic": "",
    "decisions": [],
    "entities": [],
    "open_questions": [],
    "novelty_points": [],
    "technical_specs": [],
    "compliance_refs": [],
    "tone_markers": [],
}


_PERSONA_SUMMARIZER_PROMPTS: Dict[str, str] = {
    "advisor": (
        "Anda adalah forensic summarizer untuk riset PhD Digital Forensics on AI. "
        "Ringkas percakapan sebagai JSON WAJIB mengikuti schema. "
        "Ekstrak dengan teliti: "
        "- topic: fokus riset utama percakapan. "
        "- novelty_points: metode/argumen/temuan baru atau belum umum (WAJIB pertahankan). "
        "- open_questions: celah riset, kontradiksi, counter-evidence — jangan buang. "
        "- entities: paper, author, dataset, regulasi yang disebut. "
        "- decisions: hipotesis atau arah riset yang disepakati. "
        "DILARANG menambah fakta yang tidak muncul di percakapan."
    ),
    "tactical": (
        "Anda adalah DevOps log compressor. "
        "Ringkas percakapan sebagai JSON WAJIB mengikuti schema. "
        "Ekstrak: "
        "- topic: tujuan teknis. "
        "- technical_specs: path absolut, versi library, CLI flag, error code, "
        "env var, hostname, port (WAJIB pertahankan detail verbatim). "
        "- decisions: fix atau pendekatan yang disepakati. "
        "- entities: file/service/config yang disebut. "
        "- open_questions: root cause yang belum terverifikasi. "
        "DILARANG mengarang path atau versi."
    ),
    "consultant": (
        "Anda adalah GRC audit summarizer. "
        "Ringkas percakapan sebagai JSON WAJIB mengikuti schema. "
        "Ekstrak: "
        "- topic: domain audit / kerangka regulasi. "
        "- compliance_refs: klausul ISO (e.g. 'ISO 27001:2022 A.5.1'), "
        "control NIST, pasal UU PDP / GDPR yang disebut. "
        "- decisions: rekomendasi yang disepakati. "
        "- entities: framework / regulator / vendor. "
        "- open_questions: gap compliance yang belum diatasi."
    ),
    "chill": (
        "Anda adalah casual conversation summarizer. "
        "Ringkas percakapan sebagai JSON WAJIB mengikuti schema. "
        "Ekstrak: "
        "- topic: pokok obrolan santai. "
        "- tone_markers: mood, humor, preferensi ringan. "
        "- entities: nama/hal yang disebut. "
        "Kosongkan field lain."
    ),
}


def _coerce_summary_dict(raw: Any) -> Dict[str, Any]:
    """Normalize summarizer output into the canonical schema shape.

    Accepts a dict (already parsed by google.genai) or a JSON string. Fills
    missing keys with empty defaults and drops unexpected ones.
    """
    parsed: Dict[str, Any] = {}
    if isinstance(raw, dict):
        parsed = raw
    elif isinstance(raw, str):
        import json as _json
        try:
            parsed = _json.loads(raw) if raw.strip() else {}
        except _json.JSONDecodeError:
            parsed = {}
    out: Dict[str, Any] = _EMPTY_SUMMARY_JSON.copy()
    for key, default in _EMPTY_SUMMARY_JSON.items():
        val = parsed.get(key, default)
        if isinstance(default, list):
            if isinstance(val, list):
                out[key] = [str(item).strip() for item in val if str(item).strip()]
            else:
                out[key] = []
        else:
            out[key] = str(val or "").strip()
    return out


def _summarizer_instruction_for(persona: str) -> str:
    return _PERSONA_SUMMARIZER_PROMPTS.get(
        persona, _PERSONA_SUMMARIZER_PROMPTS["consultant"]
    )


def _summarize_older_turns(older_entries: Sequence[Dict[str, Any]]) -> str:
    """Legacy free-text summarizer. Kept for backward compatibility with
    any caller that still reads the plain-text ``summary`` column."""
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


def _summarize_older_turns_structured(
    persona_scope: str,
    older_entries: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Structured JSON summarizer. Dispatches by persona and returns a dict
    that always matches ``_EMPTY_SUMMARY_JSON`` shape."""
    if not older_entries:
        # ⚡ Bolt: Using .copy() is ~30% faster than dict() initialization
        return _EMPTY_SUMMARY_JSON.copy()
    try:
        from google.genai import types as genai_types
        from kuro_backend.config import PRIMARY_MODEL

        client = _get_summary_genai_client()
        convo_blob = _format_entries_for_prompt(older_entries, max_chars_per_entry=250)
        response = client.models.generate_content(
            model=PRIMARY_MODEL,
            contents=convo_blob,
            config=genai_types.GenerateContentConfig(
                system_instruction=_summarizer_instruction_for(persona_scope),
                temperature=0.0,
                top_p=0.1,
                top_k=1,
                max_output_tokens=512,
                response_mime_type="application/json",
                response_schema=_STRUCTURED_SUMMARY_SCHEMA,
            ),
        )
        parsed = getattr(response, "parsed", None)
        text = getattr(response, "text", "") or ""
        return _coerce_summary_dict(parsed if parsed is not None else text)
    except Exception as exc:
        logger.warning("[SLIDING_WINDOW] structured summary failed persona=%s: %s",
                       persona_scope, exc)
        return _EMPTY_SUMMARY_JSON.copy()


def _summary_to_fallback_text(summary_json: Dict[str, Any]) -> str:
    """Flatten the JSON summary into a prose blob for the legacy
    ``summary`` column and for emergency fallbacks."""
    if not summary_json:
        return ""
    bits: List[str] = []
    topic = str(summary_json.get("topic") or "").strip()
    if topic:
        bits.append(f"Topik: {topic}")
    for key in ("novelty_points", "technical_specs", "compliance_refs",
                "decisions", "open_questions", "entities", "tone_markers"):
        items = summary_json.get(key) or []
        if not items:
            continue
        label = key.replace("_", " ").title()
        joined = "; ".join(str(x) for x in items[:6])
        bits.append(f"{label}: {joined}")
    text = ". ".join(bits)
    return text[:_SLIDING_WINDOW_SUMMARY_MAX_CHARS]


def _persona_ledger_kinds(persona_scope: str) -> List[tuple[str, str]]:
    """Return the (schema_field, ledger_kind) pairs to persist for a persona.

    Only persona-critical facets are persisted to keep the ledger focused.
    """
    base = [
        ("decisions", "decision"),
        ("open_questions", "open_question"),
        ("entities", "entity"),
    ]
    per_persona = {
        "advisor":    [("novelty_points", "novelty_point"), ("open_questions", "open_question")],
        "tactical":   [("technical_specs", "technical_spec"), ("decisions", "decision")],
        "consultant": [("compliance_refs", "compliance_ref"), ("decisions", "decision")],
        "chill":      [],
    }
    return per_persona.get(persona_scope, []) + base


def _persist_summary_to_ledger(
    persona_scope: str,
    summary_json: Dict[str, Any],
    *,
    source_entry_id: Optional[int] = None,
) -> int:
    """Append persona-critical items from the JSON summary into the
    append-only research ledger. Returns insertion count."""
    from kuro_backend import memory_manager

    seen: set[tuple[str, str]] = set()
    records: List[Dict[str, Any]] = []
    for schema_field, ledger_kind in _persona_ledger_kinds(persona_scope):
        for item in summary_json.get(schema_field) or []:
            content = str(item or "").strip()
            if not content:
                continue
            key = (ledger_kind, content.lower()[:256])
            if key in seen:
                continue
            seen.add(key)
            records.append({
                "kind": ledger_kind,
                "content": content,
                "source_entry_id": source_entry_id,
            })
    if not records:
        return 0
    return memory_manager.append_research_ledger_batch(
        persona_scope, records, source_entry_id=source_entry_id,
    )


def render_summary_for_prompt(
    summary_json: Dict[str, Any],
    persona: str,
) -> str:
    """Render the structured summary as a readable ``[SUMMARY ...]`` block.

    Persona-critical facets are placed FIRST so token-budget head/tail
    trimming cannot clip them.
    """
    if not summary_json:
        return ""
    persona_key = (persona or "").strip().lower() or "consultant"
    topic = str(summary_json.get("topic") or "").strip()

    priority_order: List[str]
    if persona_key == "advisor":
        priority_order = ["novelty_points", "open_questions", "decisions",
                          "entities", "compliance_refs"]
    elif persona_key == "tactical":
        priority_order = ["technical_specs", "decisions", "entities",
                          "open_questions"]
    elif persona_key == "consultant":
        priority_order = ["compliance_refs", "decisions", "entities",
                          "open_questions"]
    elif persona_key == "chill":
        priority_order = ["tone_markers", "entities"]
    else:
        priority_order = ["decisions", "entities", "open_questions"]

    lines: List[str] = ["[SUMMARY earlier_conversation]"]
    if topic:
        lines.append(f"Topik: {topic}")

    pretty_labels = {
        "decisions": "Keputusan",
        "entities": "Entitas",
        "open_questions": "Pertanyaan Terbuka",
        "novelty_points": "Novelty Points",
        "technical_specs": "Technical Specs",
        "compliance_refs": "Compliance Refs",
        "tone_markers": "Tone Markers",
    }
    for field in priority_order:
        items = summary_json.get(field) or []
        if not items:
            continue
        label = pretty_labels.get(field, field)
        bullets = "\n".join(f"  - {str(it).strip()}" for it in items if str(it).strip())
        if bullets:
            lines.append(f"{label}:\n{bullets}")

    legacy_text = str(summary_json.get("_legacy_text") or "").strip()
    if legacy_text and len(lines) <= 2:
        lines.append(legacy_text)

    return "\n".join(lines)


def _should_summarize(
    entries: Sequence[Dict[str, Any]],
    max_turns: int,
    layer1_threshold_tokens: Optional[int],
) -> bool:
    """Hybrid trigger: fire when turn count exceeds window OR when the
    raw Layer-1 text exceeds the persona's L1 utilization threshold."""
    if len(entries) > max_turns:
        return True
    if layer1_threshold_tokens and layer1_threshold_tokens > 0:
        from kuro_backend import token_budget as _tb
        raw = _format_entries_for_prompt(entries, max_chars_per_entry=200)
        if _tb.approx_tokens(raw) >= layer1_threshold_tokens:
            return True
    return False


def build_compressed_short_term_text(
    persona_scope: str,
    *,
    max_turns: int = _SLIDING_WINDOW_MAX_TURNS,
    max_chars: int = _SLIDING_WINDOW_MAX_CHARS,
    layer1_threshold_tokens: Optional[int] = None,
    force_refresh_if_stale: bool = False,
    chat_id: Optional[str] = None,
) -> str:
    """Return a compressed short-term block suitable for prompt injection.

    Trigger is hybrid:
      - turn count > ``max_turns``, OR
      - raw Layer-1 token count >= ``layer1_threshold_tokens`` (when given).

    Summary is cached per persona keyed by the highest included entry id.
    When ``force_refresh_if_stale`` is set and the cache is stale, regeneration
    runs synchronously — used by the background warmer.
    """
    from kuro_backend import memory_manager

    if chat_id is None:
        logger.warning("[MEMORY_COORD] chat_id is None in format_same_turn_attachment_index. Session isolation may collapse.")
    entries = memory_manager.get_short_term_with_ids(persona_scope=persona_scope, chat_id=chat_id)
    if not entries:
        return ""

    if not _should_summarize(entries, max_turns, layer1_threshold_tokens):
        return _format_entries_for_prompt(entries, max_chars_per_entry=160)

    # Select split: keep latest ``max_turns`` verbatim, compress the rest.
    if len(entries) <= max_turns:
        older = entries[:-1] if len(entries) > 1 else []
        recent = entries[-1:]
    else:
        older = entries[:-max_turns]
        recent = entries[-max_turns:]
    if not older:
        return _format_entries_for_prompt(recent, max_chars_per_entry=160)

    older_max_id = max((e.get("id") or 0) for e in older)

    cached = memory_manager.get_short_term_summary_json(persona_scope)
    cached_valid = bool(
        cached
        and cached.get("last_entry_id", 0) >= older_max_id
        and (cached.get("summary_json") or {}).get("topic") is not None
    )

    summary_json: Dict[str, Any]
    if cached_valid and not force_refresh_if_stale:
        summary_json = _coerce_summary_dict(cached.get("summary_json") or {})
    else:
        summary_json = _summarize_older_turns_structured(persona_scope, older)
        if summary_json and summary_json.get("topic"):
            try:
                memory_manager.upsert_short_term_summary_json(
                    persona_scope,
                    older_max_id,
                    summary_json,
                    fallback_text=_summary_to_fallback_text(summary_json),
                )
            except Exception as exc:
                logger.warning("[SLIDING_WINDOW] upsert JSON cache failed: %s", exc)
            try:
                _persist_summary_to_ledger(
                    persona_scope, summary_json, source_entry_id=older_max_id,
                )
            except Exception as exc:
                logger.warning("[LEDGER] persist failed persona=%s: %s",
                               persona_scope, exc)

    rendered_summary = render_summary_for_prompt(summary_json, persona_scope)
    if not rendered_summary:
        # Last-resort: legacy plain-text cache (old rows before migration).
        legacy = memory_manager.get_short_term_summary(persona_scope)
        if legacy and legacy.get("summary"):
            rendered_summary = (
                f"[SUMMARY earlier_conversation]\n{legacy['summary']}"
            )

    if not rendered_summary:
        return _format_entries_for_prompt(recent, max_chars_per_entry=160)

    recent_text = _format_entries_for_prompt(recent, max_chars_per_entry=160)
    compressed = f"{rendered_summary}\n\n{recent_text}"
    if len(compressed) > max_chars:
        compressed = compressed[: max_chars - 3] + "..."
    return compressed


def refresh_short_term_summary_background(persona_scope: str) -> None:
    """Idempotent helper used by the post-response worker to keep the
    structured summary cache warm. Never raises."""
    try:
        build_compressed_short_term_text(
            persona_scope,
            force_refresh_if_stale=True,
        )
    except Exception as exc:
        logger.warning("[SLIDING_WINDOW] background refresh failed persona=%s: %s",
                       persona_scope, exc)


# ---------------------------------------------------------------------------
# chat_context Auto-Generation
# ---------------------------------------------------------------------------

def generate_chat_context(chat_id: str, persona_scope: str, username: str) -> Optional[str]:
    """
    Generate a compressed context summary for a chat session using Gemini.

    Triggered every CHAT_CONTEXT_REFRESH_THRESHOLD messages (default: 10 pairs = 20 rows).
    Uses the last 30 messages (raw history) as input.
    Stores result in chat_sessions.context_summary.

    Returns the generated context string or None on failure.
    """
    from kuro_backend import chat_history
    from kuro_backend import memory_manager as _mm
    from google import genai as _genai
    from google.genai import types as _genai_types

    try:
        # Fetch raw history for this chat (last 30 messages)
        raw_history = chat_history.get_history(
            limit=30,
            username=username,
            chat_id=chat_id,
        )

        if not raw_history:
            logger.debug("[CHAT_CONTEXT] No history for chat_id=%s", chat_id)
            return None

        # Format history as conversation text
        convo_lines = []
        for msg in raw_history:
            role_label = "User" if msg.get("role") == "user" else "Kuro"
            content = str(msg.get("content") or "")[:500]
            convo_lines.append(f"{role_label}: {content}")

        convo_blob = "\n".join(convo_lines)

        # Build the summarization prompt
        prompt = (
            "Anda adalah summarizer percakapan. Rangkum percakapan berikut "
            "dalam Bahasa Indonesia dengan format JSON berikut:\n"
            "{\n"
            '  "topic": "topik utama percakapan",\n'
            '  "decisions": ["keputusan yang diambil"],\n'
            '  "entities": ["entitas/istilah penting yang disebut"],\n'
            '  "open_questions": ["pertanyaan yang belum terjawab"],\n'
            '  "technical_specs": ["spesifikasi teknis jika ada"]\n'
            "}\n\n"
            "DILARANG menambah fakta yang tidak ada dalam percakapan.\n"
            f"Percakapan:\n{convo_blob}"
        )

        client = _genai.Client(api_key=settings.GEMINI_API_KEY)
        response = client.models.generate_content(
            model=CHAT_CONTEXT_MODEL,
            contents=prompt,
            config=_genai_types.GenerateContentConfig(
                temperature=0.0,
                top_p=0.1,
                top_k=1,
                max_output_tokens=384,
                response_mime_type="application/json",
            ),
        )

        raw_text = getattr(response, "text", "") or ""
        parsed = {}
        try:
            parsed = json.loads(raw_text) if raw_text.strip() else {}
        except json.JSONDecodeError:
            parsed = {}

        # Format the context block
        topic = parsed.get("topic", "") or "Percakapan umum"
        decisions = parsed.get("decisions", []) or []
        entities = parsed.get("entities", []) or []
        open_qs = parsed.get("open_questions", []) or []
        tech_specs = parsed.get("technical_specs", []) or []

        context_block = "[CHAT_CONTEXT - Generated by Gemini]\n"
        context_block += f"Topik: {topic}\n"
        if decisions:
            context_block += f"Keputusan: {'; '.join(decisions)}\n"
        if entities:
            context_block += f"Entitas: {'; '.join(entities)}\n"
        if open_qs:
            context_block += f"Pertanyaan terbuka: {'; '.join(open_qs)}\n"
        if tech_specs:
            context_block += f"Konteks teknis: {'; '.join(tech_specs)}\n"
        context_block += f"Terakhir diperbarui: {datetime.now().isoformat()}"

        # Persist to chat_sessions
        chat_history.update_session_context(chat_id, context_block)

        logger.info(
            "[CHAT_CONTEXT] Generated for chat_id=%s topic=%s",
            chat_id,
            topic[:60],
        )
        return context_block

    except Exception as exc:
        logger.warning("[CHAT_CONTEXT] Generation failed for chat_id=%s: %s", chat_id, exc)
        return None


def maybe_trigger_chat_context(chat_id: str, persona_scope: str, username: str) -> None:
    """
    Check if chat_context should be regenerated for this chat session.
    Called from langgraph_core post-response tasks.
    """
    from kuro_backend import chat_history

    started = time.perf_counter()
    try:
        msg_count = chat_history.get_session_message_count(chat_id)

        # Trigger every CHAT_CONTEXT_REFRESH_THRESHOLD pairs (2 messages per pair)
        pair_count = msg_count // 2
        if pair_count > 0 and pair_count % CHAT_CONTEXT_REFRESH_THRESHOLD == 0:
            logger.info(
                "[CHAT_CONTEXT] Triggering generation for chat_id=%s (pair_count=%d)",
                chat_id, pair_count,
            )
            # Run synchronously in post-response worker thread (non-blocking)
            generate_chat_context(chat_id, persona_scope, username)
            latency_ms = (time.perf_counter() - started) * 1000.0
            try:
                from kuro_backend import intelligence_db

                intelligence_db.add_audit_trail(
                    action="chat_context_refresh",
                    details=(
                        f"chat_id={chat_id} username={username} "
                        f"message_count_at_trigger={msg_count} latency_ms={latency_ms:.2f}"
                    ),
                )
            except Exception as audit_exc:
                logger.debug("[CHAT_CONTEXT] audit trail log skipped: %s", audit_exc)
    except Exception as exc:
        logger.debug("[CHAT_CONTEXT] maybe_trigger failed: %s", exc)


def _parse_dataset_and_section(vector_id: str) -> tuple[Optional[str], Optional[int]]:
    if not vector_id or ":" not in vector_id:
        return None, None
    left, right = vector_id.split(":", 1)
    try:
        return left, int(right)
    except Exception:
        return left, None


def _distance_to_similarity(distance: Any) -> float:
    try:
        value = float(distance)
    except Exception:
        return 0.0
    if value < 0:
        value = 0.0
    return 1.0 / (1.0 + value)


def _retrieve_ingestion_evidence(
    user_input: str,
    *,
    username: str,
    chat_id: Optional[str],
    top_k: int,
    max_chars: int,
    min_score: float,
) -> List[Dict[str, Any]]:
    if not _INGESTION_BRIDGE_ENABLED or not user_input:
        return []
    try:
        from kuro_backend.ingestion_center import embedding_manager, ingestion_registry, retrieval_analytics

        query_result = embedding_manager.query_owner_collection(
            owner_username=username,
            query_text=user_input,
            top_k=max(1, int(top_k or 1)),
        )
        if (query_result or {}).get("status") != "success":
            return []

        active_rows = ingestion_registry.list_active_datasets(
            username,
            allowed_statuses=("completed", "partially_indexed"),
        )
        active_map = {row.get("dataset_uuid"): row for row in active_rows if row.get("dataset_uuid")}
        if not active_map:
            return []

        ids = query_result.get("ids", []) or []
        docs = query_result.get("documents", []) or []
        metas = query_result.get("metadatas", []) or []
        dists = query_result.get("distances", []) or []

        candidates: List[Dict[str, Any]] = []
        for idx, vector_id in enumerate(ids):
            metadata = metas[idx] if idx < len(metas) and isinstance(metas[idx], dict) else {}
            doc_text = str(docs[idx] or "") if idx < len(docs) else ""
            distance = dists[idx] if idx < len(dists) else None
            dataset_uuid = str(metadata.get("dataset_uuid") or "")
            section_no: Optional[int]
            if dataset_uuid:
                raw_section = metadata.get("chunk_index")
                try:
                    section_no = int(raw_section)
                except Exception:
                    _, section_no = _parse_dataset_and_section(str(vector_id or ""))
            else:
                dataset_uuid, section_no = _parse_dataset_and_section(str(vector_id or ""))
            if not dataset_uuid or dataset_uuid not in active_map or section_no is None:
                continue

            chunk_row = ingestion_registry.get_chunk_by_dataset_and_index(dataset_uuid, section_no)
            chunk_text = str((chunk_row or {}).get("chunk_text") or doc_text or "").strip()
            if not chunk_text:
                continue

            score = _distance_to_similarity(distance)
            if score < min_score:
                continue

            dataset_row = active_map[dataset_uuid]
            candidates.append(
                {
                    "dataset_uuid": dataset_uuid,
                    "dataset_name": str(dataset_row.get("dataset_name") or metadata.get("dataset_name") or dataset_uuid),
                    "chunk_index": int(section_no),
                    "chunk_id": (chunk_row or {}).get("id"),
                    "score": score,
                    "chunk_text": chunk_text,
                }
            )

        if not candidates:
            return []

        candidates.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)

        selected: List[Dict[str, Any]] = []
        used_chars = 0
        for item in candidates:
            if len(selected) >= max(1, int(top_k or 1)):
                break
            remaining = max_chars - used_chars
            if remaining <= 0:
                break
            text = str(item.get("chunk_text") or "").strip()
            if not text:
                continue
            if len(text) > remaining:
                truncated = text[:remaining]
                if " " in truncated:
                    truncated = truncated.rsplit(" ", 1)[0]
                text = truncated.strip() or text[:remaining]
            if not text:
                continue
            row = dict(item)
            row["chunk_text"] = text
            selected.append(row)
            used_chars += len(text)

        for item in selected:
            try:
                retrieval_analytics.log_retrieval_event(
                    dataset_uuid=str(item.get("dataset_uuid") or ""),
                    chunk_id=item.get("chunk_id"),
                    retrieval_source="chat_bridge",
                    retrieval_score=float(item.get("score") or 0.0),
                    hallucination_flag=0,
                    username=username,
                    chat_id=chat_id,
                )
                chunk_id = item.get("chunk_id")
                if chunk_id:
                    ingestion_registry.increment_chunk_retrieval_count(int(chunk_id))
            except Exception as exc:
                logger.debug("[INGESTION_BRIDGE] analytics log skipped: %s", exc)
        return selected
    except Exception as exc:
        logger.debug("[INGESTION_BRIDGE] retrieval skipped: %s", exc)
        return []


def _build_ingestion_context_block(evidence_items: Sequence[Dict[str, Any]]) -> str:
    if not evidence_items:
        return ""
    lines: List[str] = [
        "[INGESTION_KNOWLEDGE_CONTEXT]",
        "Gunakan referensi dokumen ingestion berikut hanya jika relevan dengan pertanyaan user.",
    ]
    for idx, item in enumerate(evidence_items, 1):
        dataset_name = str(item.get("dataset_name") or item.get("dataset_uuid") or "unknown")
        section_no = int(item.get("chunk_index") or 0)
        score = float(item.get("score") or 0.0)
        chunk_text = str(item.get("chunk_text") or "").strip()
        if not chunk_text:
            continue
        lines.append(f"- Sumber {idx}: dokumen={dataset_name}; bagian={section_no}; skor={score:.2f}")
        lines.append(chunk_text)
    return "\n".join(lines)


def build_context_for_llm(
    user_input: str,
    persona_mode: str,
    *,
    mem0_retrieved_memories: Optional[List[Any]] = None,
    include_referent_grounding: bool = True,
    chat_platform: Optional[str] = None,
    context_budget: Any = None,
    session_id: Optional[str] = None,
    username: str = "Pantronux",
    chat_id: Optional[str] = None,
    runtime_id: str = "sovereign",
    runtime_namespace: str = "kuro.sovereign",
) -> Dict[str, Any]:
    """
    Single read path: raw short-term + optional Mem0 block (same inputs as response_node / stream).
    Returns keys: recent_messages, memory_injection, mem0_context_block,
    referent_grounding_block, ingestion_context_block, ingestion_sources, budget.

    When ``context_budget`` is not supplied, resolves to the persona's
    :class:`kuro_backend.personas.ContextBudget` so the Layer-1 summarizer
    can fire on the hybrid utilization threshold.
    """
    from kuro_backend import memory_manager
    from kuro_backend import perpetual_memory
    from kuro_backend import personas

    budget = context_budget or personas.get_context_budget(persona_mode)
    runtime_id = str(runtime_id or "sovereign")
    runtime_namespace = str(runtime_namespace or f"kuro.{runtime_id}")

    _trace_coordinator_span(
        "build_context_for_llm",
        {
            "persona": persona_mode,
            "mem0_n": len(mem0_retrieved_memories or []),
            "budget_total": budget.total_tokens,
        },
    )

    # Parallelize independent I/O. Short-term retrieval and referent grounding
    # are independent from Mem0 context formatting.
    parallel_tasks: Dict[str, Any] = {
        "short_term": lambda: (logger.warning("[MEMORY_COORD] chat_id is None in build_context_for_llm") if chat_id is None else None) or memory_manager.get_short_term(
            persona_scope=persona_mode,
            username=username,
            chat_id=chat_id,
            runtime_id=runtime_id,
            namespace=runtime_namespace,
        ),
        "session_files": lambda: memory_manager.get_session_files(session_id) if session_id else [],
        "ingestion": lambda: _retrieve_ingestion_evidence(
            user_input,
            username=username,
            chat_id=chat_id,
            top_k=_INGESTION_BRIDGE_TOP_K,
            max_chars=_INGESTION_BRIDGE_MAX_CHARS,
            min_score=_INGESTION_BRIDGE_MIN_SCORE,
        ),
    }
    if include_referent_grounding:
        parallel_tasks["referent"] = lambda: build_referent_grounding_block(
            user_input,
            persona_mode,
            chat_platform=chat_platform,
            username=username,
            chat_id=chat_id,
        )
    filtered_mem0 = list(mem0_retrieved_memories or [])
    if _MEMORY_INTEGRITY_V2_ENABLED and filtered_mem0:
        filtered_mem0 = validate_memory_relevance(user_input, filtered_mem0)
        if detect_context_bleed(user_input, filtered_mem0):
            logger.warning("[MEMORY_COORD] context_bleed detected for query=%r", (user_input or "")[:80])
            filtered_mem0 = []

    if filtered_mem0:
        parallel_tasks["mem0_fmt"] = lambda: perpetual_memory.perpetual_memory.format_memories_for_context(
            filtered_mem0
        )

    fan_out = _parallel_gather_sync(parallel_tasks)
    all_recent_messages = fan_out.get("short_term") or []
    # V1.0.0: Raw Episodic Buffer (Last 10 turns MUST be passed in raw, unsummarized form)
    recent_messages = all_recent_messages[-10:]
    referent_grounding_block = fan_out.get("referent") if include_referent_grounding else None
    mem0_context_block = fan_out.get("mem0_fmt") if filtered_mem0 else None
    ingestion_sources = fan_out.get("ingestion") or []
    ingestion_context_block = _build_ingestion_context_block(ingestion_sources)
    if mem0_context_block:
        logger.info(
            "[MEMORY_COORD] build_context persona=%s mem0_chars=%s",
            persona_mode,
            len(mem0_context_block),
        )
        if _MEMORY_INTEGRITY_V2_ENABLED:
            weighted = apply_temporal_decay_weighting(filtered_mem0)
            if weighted:
                mem0_context_block = (
                    "[MEMORY_INTEGRITY]\n"
                    f"weighted_memories={len(weighted)}\n"
                    + mem0_context_block
                )
        if _CANVAS3_MEMORY_CANONICALIZATION_ENABLED:
            cscore = canonical_selection_score(filtered_mem0)
            mem0_context_block = (
                "[MEMORY_CANONICALIZATION]\n"
                f"selection_score={cscore:.2f}\n"
                + mem0_context_block
            )

    # KURO V1.0.0: raw short-term window only (no summary compression) and Mem0 as
    # sole long-term semantic layer. Keep memory_injection focused on raw turns.
    # Label explicitly as RAW EPISODIC BUFFER
    short_term_block = _format_entries_for_prompt(recent_messages, max_chars_per_entry=10000)

    memory_injection = ""
    if short_term_block:
        memory_injection = f"[RAW EPISODIC BUFFER - LAST 10 TURNS]\n{short_term_block}"

    # V1.0.0 Active Buffer (Session Files)
    session_files = fan_out.get("session_files") or []
    if session_files:
        session_files_block = "[ACTIVE BUFFER - SESSION FILES]\n"
        for sf in session_files:
            session_files_block += f"\n--- File: {sf['filename']} ---\n{sf['content']}\n"
        memory_injection = f"{session_files_block}\n\n{memory_injection}"

    if _CANVAS3_COGNITIVE_BUDGET_ENABLED:
        budget_state = evaluate_budget(
            {
                "retrieval_retry_count": 0,
                "tool_budget_status": {},
            }
        )
        memory_injection = (
            "[COGNITIVE_BUDGET]\n"
            f"degradation_mode={budget_state.get('degradation_mode', 'normal')}\n\n"
            + memory_injection
        )

    finance_block = ""
    market_block = ""
    if memory_manager.normalize_persona(persona_mode) == "chancellor":
        try:
            from kuro_backend import finance_db

            finance_block = finance_db.format_ledger_snapshot(username=username)
            market_block = finance_db.format_market_snapshot_for_prompt(username=username)
        except Exception as exc:
            logger.debug("[MEMORY_COORD] finance/market snapshot skipped: %s", exc)
            finance_block = ""
            market_block = ""

    return {
        "recent_messages": recent_messages,
        "memory_injection": memory_injection,
        "mem0_context_block": mem0_context_block,
        "referent_grounding_block": referent_grounding_block,
        "ingestion_context_block": ingestion_context_block,
        "ingestion_sources": ingestion_sources,
        "budget": budget,
        "finance_block": finance_block,
        "market_block": market_block,
    }


async def build_context_for_llm_async(
    user_input: str,
    persona_mode: str,
    *,
    mem0_retrieved_memories: Optional[List[Any]] = None,
    include_referent_grounding: bool = True,
    chat_platform: Optional[str] = None,
    context_budget: Any = None,
    session_id: Optional[str] = None,
    username: str = "Pantronux",
    chat_id: Optional[str] = None,
    runtime_id: str = "sovereign",
    runtime_namespace: str = "kuro.sovereign",
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
        mem0_retrieved_memories=mem0_retrieved_memories,
        include_referent_grounding=include_referent_grounding,
        chat_platform=chat_platform,
        context_budget=context_budget,
        session_id=session_id,
        username=username,
        chat_id=chat_id,
        runtime_id=runtime_id,
        runtime_namespace=runtime_namespace,
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
import asyncio
_MEM0_PREFETCH_LOCK = threading.Lock() # Note: kept as threading.Lock because this is accessed synchronously from graph nodes, not awaited.
_MEM0_PREFETCH_TTL_S = 30.0
_MEM0_PREFETCH_TIMESTAMPS: Dict[str, float] = {}


def prefetch_mem0(session_id: str, user_input: str, *, limit: int = 5, username: str = "Pantronux") -> None:
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
                username,
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


def _filter_mem0_results_by_runtime(
    results: List[Dict[str, Any]],
    runtime_id: str,
    runtime_namespace: str,
) -> List[Dict[str, Any]]:
    """
    Filter Mem0 retrieval results to runtime-compatible rows.
    Legacy rows without runtime metadata are kept only for sovereign runtime.
    """
    filtered: List[Dict[str, Any]] = []
    for item in results:
        metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
        if not isinstance(metadata, dict):
            metadata = {}
        mem_runtime = str(metadata.get("runtime_id", "") or "").strip()
        mem_ns = str(metadata.get("runtime_namespace", "") or "").strip()

        # Legacy records without runtime metadata remain visible only to sovereign.
        if not mem_runtime and not mem_ns:
            if runtime_id == "sovereign":
                filtered.append(item)
            continue

        if mem_runtime and mem_runtime == runtime_id:
            filtered.append(item)
            continue
        if mem_ns and mem_ns == runtime_namespace:
            filtered.append(item)
    return filtered


def safe_mem0_retrieve(
    user_input: str,
    *,
    limit: int = 5,
    timeout_s: float = _MEM0_DEFAULT_TIMEOUT_SEC,
    username: str = "Pantronux",
    ctx: "RuntimeContext | None" = None,
) -> List[Dict[str, Any]]:
    """
    Hard-timeout Mem0 retrieval. Returns `[]` on timeout or any exception so
    LangGraph nodes degrade gracefully to short-term-only context.
    """
    if not user_input:
        return []
    if ctx is not None:
        from kuro_backend.runtime.boundary_guard import assert_memory_access

        assert_memory_access(ctx, ctx.config.memory_namespace)
    from kuro_backend import perpetual_memory
    started = time.perf_counter()

    try:
        future = _MEM0_EXECUTOR.submit(
            perpetual_memory.perpetual_memory.retrieve_memories,
            user_input,
            limit,
            username,
        )
        result = future.result(timeout=timeout_s)
    except concurrent.futures.TimeoutError:
        logger.warning(
            "[MEMORY_COORD] mem0 retrieve timed out after %.2fs (query=%r)",
            timeout_s,
            (user_input or "")[:60],
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            from kuro_backend import observability

            observability.record_memory_retrieval_latency(
                latency_ms=latency_ms,
                username=username,
                hit=False,
            )
        except Exception:
            pass
        _trace_memory_layer("mem0", "retrieve", ok=False)
        return []
    except Exception as exc:
        logger.warning("[MEMORY_COORD] mem0 retrieve failed: %s", exc)
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            from kuro_backend import observability

            observability.record_memory_retrieval_latency(
                latency_ms=latency_ms,
                username=username,
                hit=False,
            )
        except Exception:
            pass
        _trace_memory_layer("mem0", "retrieve", ok=False)
        return []

    latency_ms = (time.perf_counter() - started) * 1000.0
    try:
        from kuro_backend import observability

        observability.record_memory_retrieval_latency(
            latency_ms=latency_ms,
            username=username,
            hit=bool(result),
        )
    except Exception:
        pass
    _trace_memory_layer("mem0", "retrieve", ok=True)
    if isinstance(result, list):
        if ctx is not None:
            filtered = _filter_mem0_results_by_runtime(
                result,
                runtime_id=ctx.runtime_id,
                runtime_namespace=ctx.config.memory_namespace,
            )
            return filtered
        return result
    logger.warning("[MEMORY_COORD] mem0 retrieve returned non-list %s; coercing", type(result))
    return []


def execute_memory_write_task(
    user_input: str,
    final_response: str,
    persona_scope: str,
    username: str = "Pantronux",
) -> None:
    """Post-response memory writer for Mem0-only long-term semantic storage."""
    from kuro_backend import memory_manager

    if not (user_input or "").strip() or not (final_response or "").strip():
        return

    integrity_ok = prevent_memory_mutation(final_response, [user_input])
    contradiction = memory_contradiction_score(user_input, [final_response])
    integrity_score = max(0.0, min(1.0, (0.75 if integrity_ok else 0.25) - (contradiction * 0.25)))
    canonicalization_result = {
        "validation_passed": True,
        "canonical_summary": final_response,
        "conflict_resolution": "none",
        "temporal_score": 1.0,
        "promoted": True,
        "contradiction_detected": False,
    }

    if _CANVAS3_MEMORY_CANONICALIZATION_ENABLED:
        canonicalization_result = canonicalize_memory_payload(
            user_input=user_input,
            final_response=final_response,
        )
        if hasattr(memory_manager, "append_memory_canonicalization_log"):
            try:
                memory_manager.append_memory_canonicalization_log(
                    username=username,
                    session_id=persona_scope,
                    promoted=bool(canonicalization_result.get("promoted", False)),
                    temporal_score=float(canonicalization_result.get("temporal_score", 0.0) or 0.0),
                    canonical_summary=str(canonicalization_result.get("canonical_summary", "")),
                    payload=canonicalization_result,
                )
            except Exception as exc:
                logger.debug("[MEM_CANON] append log skipped: %s", exc)

    if not integrity_ok:
        logger.warning("[MEMORY_COORD] memory write blocked by semantic_integrity guard")
        if hasattr(memory_manager, "append_memory_integrity_log"):
            memory_manager.append_memory_integrity_log(
                memory_id=f"{int(time.time())}:{persona_scope}",
                integrity_score=integrity_score,
                drift_detected=1,
                contradiction_detected=1 if contradiction >= 0.5 else 0,
            )
        return

    mem0_text = str(canonicalization_result.get("canonical_summary", final_response) or final_response)
    execute_mem0_extract_task(user_input, mem0_text, username=username)
    if hasattr(memory_manager, "append_memory_integrity_log"):
        memory_manager.append_memory_integrity_log(
            memory_id=f"{int(time.time())}:{persona_scope}",
            integrity_score=integrity_score,
            drift_detected=0,
            contradiction_detected=1 if contradiction >= 0.5 else 0,
        )


def execute_mem0_extract_task(
    user_input: str,
    final_response: str,
    username: str = "Pantronux",
    ctx: "RuntimeContext | None" = None,
) -> None:
    """Mem0 extract+store with dedupe (graph + fast path may enqueue similar payloads)."""
    from kuro_backend import perpetual_memory, memory_manager
    import time
    import json

    runtime_id_for_dedup = "sovereign"
    runtime_namespace_for_dedup = "kuro.sovereign"
    if ctx is not None:
        runtime_id_for_dedup = str(ctx.runtime_id or runtime_id_for_dedup)
        runtime_namespace_for_dedup = str(
            ctx.config.memory_namespace or runtime_namespace_for_dedup
        )
    fp = _mem0_fingerprint(
        user_input,
        final_response,
        runtime_id_for_dedup,
        runtime_namespace_for_dedup,
    )
    if _mem0_should_skip_duplicate(fp):
        logger.info("[MEMORY_COORD] mem0_extract skipped duplicate fp=%s...", fp[:12])
        return
    if ctx is not None:
        from kuro_backend.runtime.boundary_guard import assert_memory_access

        assert_memory_access(ctx, ctx.config.memory_namespace)
    dedup_key = (
        f"{username}:{runtime_id_for_dedup}:{runtime_namespace_for_dedup}:"
        f"{hash((final_response or '')[:64])}"
    )
    user_lock = _get_mem0_user_lock(username)
    if not user_lock.acquire(blocking=False):
        with _MEM0_QUEUE_LOCK:
            if dedup_key in _MEM0_QUEUE_DEDUP:
                logger.info("[MEMORY_COORD] mem0_enqueue skipped duplicate key=%s", dedup_key)
                return
            queue_for_user = _MEM0_PENDING_QUEUE[username]
            if len(queue_for_user) >= max(1, _MEM0_PENDING_PER_USER_MAX):
                dropped = queue_for_user.popleft()
                _MEM0_QUEUE_DEDUP.discard(dropped[2])
                logger.warning(
                    "[MEMORY_COORD] mem0 pending queue capped user=%s max=%d; dropped oldest",
                    username,
                    _MEM0_PENDING_PER_USER_MAX,
                )
            _MEM0_QUEUE_DEDUP.add(dedup_key)
            queue_for_user.append(
                (user_input, final_response, dedup_key, ctx)
            )
        logger.info("[MEMORY_COORD] mem0 task queued for user=%s depth=%d", username, len(_MEM0_PENDING_QUEUE[username]))
        return

    try:
        _trace_coordinator_span(
            "execute_mem0_extract_task",
            {"fp": fp[:16], "chars_in": len(user_input or ""), "chars_out": len(final_response or "")},
        )

        max_attempts = 3
        attempt = 0
        while attempt < max_attempts:
            try:
                memories_to_store = perpetual_memory.perpetual_memory.extract_personal_info(
                    user_input,
                    final_response,
                    username,
                )
                if memories_to_store and isinstance(memories_to_store, list):
                    runtime_id = "sovereign"
                    runtime_namespace = "kuro.sovereign"
                    if ctx is not None:
                        runtime_id = str(ctx.runtime_id or runtime_id)
                        runtime_namespace = str(
                            ctx.config.memory_namespace or runtime_namespace
                        )
                    tagged_memories_to_store: List[Any] = []
                    for mem in memories_to_store:
                        if isinstance(mem, dict):
                            meta = mem.get("metadata", {})
                            if not isinstance(meta, dict):
                                meta = {"metadata_raw": str(meta)}
                            meta = dict(meta)
                            meta["runtime_id"] = runtime_id
                            meta["runtime_namespace"] = runtime_namespace
                            tagged = dict(mem)
                            tagged["metadata"] = meta
                            tagged_memories_to_store.append(tagged)
                        else:
                            tagged_memories_to_store.append(mem)

                    def _mem0_store() -> None:
                        perpetual_memory.perpetual_memory.store_memories(
                            tagged_memories_to_store,
                            username,
                        )

                    try:
                        from kuro_backend import semantic_cache

                        async def _atomic_mem0_write_and_invalidate() -> None:
                            async with semantic_cache.atomic_write_and_invalidate(
                                username=username,
                                query=user_input,
                                persona="mem0_extract",
                                response=final_response,
                                tags=(username,),
                                write_callable=_mem0_store,
                            ):
                                return

                        try:
                            running_loop = asyncio.get_running_loop()
                        except RuntimeError:
                            running_loop = None
                        if running_loop and running_loop.is_running():
                            _mem0_store()
                            semantic_cache.invalidate_tag(username)
                        else:
                            asyncio.run(_atomic_mem0_write_and_invalidate())
                    except Exception as sc_err:
                        logger.warning("[MEMORY_COORD] Atomic cache invalidation path failed: %s", sc_err)
                        _mem0_store()
                        try:
                            from kuro_backend import semantic_cache
                            semantic_cache.invalidate_tag(username)
                        except Exception as inner_sc_err:
                            logger.warning("[MEMORY_COORD] Failed to invalidate semantic cache: %s", inner_sc_err)
                    logger.info(
                        "[MEMORY_COORD] mem0_extract stored n=%s for user %s runtime=%s",
                        len(tagged_memories_to_store),
                        username,
                        runtime_id,
                    )
                    try:
                        from kuro_backend import observability

                        observability.record_mem0_write_result(success=True, username=username)
                    except Exception:
                        pass
                else:
                    logger.debug("[MEMORY_COORD] mem0_extract nothing to store")
                    try:
                        from kuro_backend import observability

                        observability.record_mem0_write_result(success=True, username=username)
                    except Exception:
                        pass
                return
            except Exception as e:
                attempt += 1
                logger.warning("[MEMORY_COORD] mem0_extract attempt %d failed: %s", attempt, e)
                if attempt < max_attempts:
                    time.sleep(2 ** (attempt - 1)) # Exponential backoff: 1s, 2s
                else:
                    logger.error("[MEMORY_COORD] mem0_extract failed permanently. Writing to mem0_write_failures.")
                    try:
                        from kuro_backend import observability

                        observability.record_mem0_write_result(success=False, username=username)
                    except Exception:
                        pass
                    try:
                        payload = json.dumps(
                            {
                                "user_input": user_input,
                                "final_response": final_response,
                                "runtime_id": runtime_id_for_dedup,
                                "runtime_namespace": runtime_namespace_for_dedup,
                                "chat_id": getattr(ctx, "chat_id", "") if ctx is not None else "",
                                "trace_id": getattr(ctx, "trace_id", "") if ctx is not None else "",
                            }
                        )
                        memory_manager.record_mem0_write_failure(username, payload)
                    except Exception as db_err:
                        logger.error("[MEMORY_COORD] Failed to record mem0_write_failure: %s", db_err)
    finally:
        user_lock.release()
        while True:
            with _MEM0_QUEUE_LOCK:
                if not _MEM0_PENDING_QUEUE[username]:
                    break
                (
                    queued_user_input,
                    queued_final_response,
                    queued_key,
                    queued_ctx,
                ) = _MEM0_PENDING_QUEUE[username].popleft()
                _MEM0_QUEUE_DEDUP.discard(queued_key)
            execute_mem0_extract_task(
                queued_user_input,
                queued_final_response,
                username=username,
                ctx=queued_ctx,
            )




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


    if domain == "long_term":
        from kuro_backend import memory_manager

        persona = payload.get("persona_scope") or memory_manager.get_active_persona()
        execute_memory_write_task(
            str(payload.get("user_input", "")),
            str(payload.get("final_response", "")),
            str(persona),
        )
        result_lt = {
            "ok": True,
            "revision": _cs.get_data_revision(),
            "canonical_record_id": None,
        }
        _maybe_emit_proactive_from_mutation(domain, source, payload, result_lt)
        return result_lt

    if domain == "mem0":
        username = payload.get("username", "Pantronux")
        execute_mem0_extract_task(
            str(payload.get("user_input", "")),
            str(payload.get("final_response", "")),
            username
        )
        result_mem0 = {
            "ok": True,
            "revision": _cs.get_data_revision(),
            "canonical_record_id": None,
        }
        _maybe_emit_proactive_from_mutation(domain, source, payload, result_mem0)
        return result_mem0

    return {"ok": False, "error": f"unsupported domain: {domain}", "revision": _cs.get_data_revision()}


def _maybe_emit_proactive_from_mutation(
    domain: str,
    source: str,
    payload: Dict[str, Any],
    result: Dict[str, Any],
) -> None:
    """Post-mutation observer: fire a ProactiveEvent when the payload carries
    an explicit anomaly marker.

    Designed to be microscopic on the hot path — a single ``payload.get``
    short-circuits when nothing anomalous happened. Publication is routed
    through the event bus on a background thread so the caller's request
    latency is never touched.
    """
    try:
        if not isinstance(payload, dict):
            return
        if not (payload.get("anomaly") is True or payload.get("anomaly_severity")):
            return
        severity = str(payload.get("anomaly_severity") or "warning").lower()
        kind_hint = str(payload.get("anomaly_kind") or domain or "generic").lower()
        if kind_hint in ("fitness", "fitness_anomaly"):
            kind = "fitness_anomaly"
        elif kind_hint in ("hardware", "server", "system"):
            kind = "hardware"
        elif kind_hint in ("security", "security_cve", "cve"):
            kind = "security_cve"
        else:
            kind = "generic"
        title = str(payload.get("anomaly_title") or f"{kind} anomaly from {source}")
        body = str(payload.get("anomaly_body") or "")
        fingerprint_seed = str(
            payload.get("anomaly_fingerprint")
            or f"mutation:{domain}:{source}:{title}"
        )
        from kuro_backend import proactive_events

        event = proactive_events.make_event(
            kind=kind,
            severity=severity,
            title=title,
            body=body,
            fingerprint_seed=fingerprint_seed,
            context={
                "domain": domain,
                "source": source,
                "revision": result.get("revision"),
            },
        )
        proactive_events.publish_async(event)
    except Exception as exc:
        logger.debug("[MEMORY_COORD] proactive observer skipped: %s", exc)


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
        raw.get("ssot_bump_required")
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
                },
            )
        except Exception as exc:
            revision_error = str(exc)
            logger.exception("[MEMORY_COORD] bump after OpenClaw failed: %s", exc)

    result = {
        "should_bump_revision": should_bump,
        "revision_bumped": revision_bumped,
        "revision_error": revision_error,
    }
    _maybe_emit_proactive_from_mutation(
        domain="openclaw",
        source=skill_name,
        payload=raw if isinstance(raw, dict) else {},
        result=result,
    )
    return result


# ---------------------------------------------------------------------------
# T2 Metacognitive Tier — Belief Revision (Tomasello 2025)
# ---------------------------------------------------------------------------

def evaluate_alignment(user_input: str, persona_mode: str, username: str = "Pantronux") -> Dict[str, Any]:
    """
    T2 Belief Revision: compare the current user input against prior BRD-backed
    commitments stored in the research_ledger (kind='decision' and 'novelty_point').

    Only meaningful when the research_ledger contains prior commitments — new
    sessions will return score=1.0 (no prior beliefs to conflict with).

    Args:
        user_input:   Raw user message.
        persona_mode: Active persona key (e.g. "advisor", "consultant", "auditor").
        username:     User requesting alignment check.

    Returns:
        {
            "score":          float,  # 0.0 (full conflict) … 1.0 (full alignment)
            "conflicts":      list,   # ledger items that contradict input
            "supports":       list,   # ledger items that support input
            "recommendation": str,    # suggested realignment action
        }
    """
    from kuro_backend import memory_manager

    _NULL_RESULT: Dict[str, Any] = {
        "score": 1.0,
        "conflicts": [],
        "supports": [],
        "recommendation": "",
    }

    # Fetch prior commitments — decisions and novelty points are the
    # primary BRD-anchored belief stores for the advisor/consultant/auditor path.
    try:
        prior_decisions = memory_manager.query_research_ledger(
            persona_scope=persona_mode, username=username, kinds=["decision"], limit=8
        )
        prior_novelty = memory_manager.query_research_ledger(
            persona_scope=persona_mode, username=username, kinds=["novelty_point"], limit=5
        )
    except Exception as exc:
        logger.warning("[EVALUATE_ALIGNMENT] ledger read failed for %s: %s", username, exc)
        return _NULL_RESULT

    all_priors = prior_decisions + prior_novelty
    if not all_priors:
        # No prior beliefs → no possible conflict.
        return _NULL_RESULT

    prior_text = "\n".join(
        f"- [{r.get('kind', '?')}] {r.get('content', '')}" for r in all_priors
    )

    try:
        from google.genai import types as genai_types
        from kuro_backend.config import CLASSIFIER_MODEL

        client = _get_summary_genai_client()
        prompt = (
            "You are a dissertation coherence auditor.\n\n"
            f"Prior BRD Commitments (from research ledger, persona={persona_mode}):\n"
            f"{prior_text}\n\n"
            f"Current User Input:\n{user_input}\n\n"
            "Evaluate alignment between the current input and the prior commitments.\n"
            "Return JSON with exactly these keys:\n"
            "{\n"
            '  "score": <float 0.0-1.0>,\n'
            '  "conflicts": ["<ledger item that contradicts input>", ...],\n'
            '  "supports": ["<ledger item that supports input>", ...],\n'
            '  "recommendation": "<one-sentence suggested realignment action>"\n'
            "}\n"
            "score=1.0 → fully aligned; score=0.0 → directly contradictory."
        )

        resp = client.models.generate_content(
            model=CLASSIFIER_MODEL,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=350,
                response_mime_type="application/json",
            ),
        )

        import json as _json
        raw_text = getattr(resp, "text", "") or ""
        result = _json.loads(raw_text) if raw_text.strip() else {}

        score = float(result.get("score", 1.0))
        score = max(0.0, min(1.0, score))

        return {
            "score": score,
            "conflicts": result.get("conflicts", []),
            "supports": result.get("supports", []),
            "recommendation": result.get("recommendation", ""),
        }

    except Exception as exc:
        logger.warning("[EVALUATE_ALIGNMENT] LLM call failed: %s", exc)
        return _NULL_RESULT
