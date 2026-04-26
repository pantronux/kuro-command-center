"""
Kuro AI V6.0 Sovereign — Unified Memory Coordinator — single orchestration surface for memory-related reads
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

--- Header Doc ---
Purpose: Central memory-read orchestration + post-response write fan-out across all memory tiers.
Caller: langgraph_core response_node, main.py chat routes, dreaming_worker, services/core_service.
Dependencies: memory_manager, perpetual_memory, finance_db, reminder_service, habit_service, intelligence_engine, observability, Mem0 (optional).
Main Functions: build_context_for_llm(), post_response_memory_writes(), record_mutation(), build_gemini_contents_parts(), build_referent_grounding_block().
Side Effects: Reads + writes across sqlite + ChromaDB, Mem0 HTTP calls, SSoT revision bumps via core_service.bump_data_revision.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
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
    from kuro_backend import memory_manager

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
    raw_session_state = memory_manager.get_runtime_context_value("current_session_state", "")
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
                    summary = str(item.get("extracted_content", "")).replace("\n", " ")[:220]
                    lines.append(f"- current_session_file={fname!r} extracted={summary!r}")
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
    "butler": (
        "Anda adalah operational summarizer. "
        "Ringkas percakapan sebagai JSON WAJIB mengikuti schema. "
        "Ekstrak: "
        "- topic: urusan operasional yang dibahas. "
        "- decisions: instruksi Master yang disepakati. "
        "- entities: habit/reminder/integrasi yang disebut. "
        "- compliance_refs: kebijakan operasional internal. "
        "Kosongkan field lain."
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
    out: Dict[str, Any] = {k: v for k, v in _EMPTY_SUMMARY_JSON.items()}
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
        return dict(_EMPTY_SUMMARY_JSON)
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
        return dict(_EMPTY_SUMMARY_JSON)


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
        "butler":     [("compliance_refs", "compliance_ref"), ("decisions", "decision")],
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
    elif persona_key == "butler":
        priority_order = ["decisions", "compliance_refs", "entities"]
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

    entries = memory_manager.get_short_term_with_ids(persona_scope=persona_scope)
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


def build_context_for_llm(
    user_input: str,
    persona_mode: str,
    *,
    mem0_retrieved_memories: Optional[List[Any]] = None,
    include_referent_grounding: bool = True,
    chat_platform: Optional[str] = None,
    context_budget: Any = None,
) -> Dict[str, Any]:
    """
    Single read path: raw short-term + optional Mem0 block (same inputs as response_node / stream).
    Returns keys: recent_messages, memory_injection, mem0_context_block,
    referent_grounding_block, budget.

    When ``context_budget`` is not supplied, resolves to the persona's
    :class:`kuro_backend.personas.ContextBudget` so the Layer-1 summarizer
    can fire on the hybrid utilization threshold.
    """
    from kuro_backend import memory_manager
    from kuro_backend import perpetual_memory
    from kuro_backend import personas

    budget = context_budget or personas.get_context_budget(persona_mode)

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
    all_recent_messages = fan_out.get("short_term") or []
    recent_messages = all_recent_messages[-15:]
    referent_grounding_block = fan_out.get("referent") if include_referent_grounding else None
    mem0_context_block = fan_out.get("mem0_fmt") if mem0_retrieved_memories else None
    if mem0_context_block:
        logger.info(
            "[MEMORY_COORD] build_context persona=%s mem0_chars=%s",
            persona_mode,
            len(mem0_context_block),
        )

    # KURO V7.0: raw short-term window only (no summary compression) and Mem0 as
    # sole long-term semantic layer. Keep memory_injection focused on raw turns.
    short_term_block = _format_entries_for_prompt(recent_messages, max_chars_per_entry=800)
    memory = {
        "profile": "",
        "long_term": "",
        "short_term": short_term_block,
        "compliance": "",
    }
    memory_injection = memory_manager.format_memory_with_temporal_grounding(memory)

    finance_block = ""
    market_block = ""
    if memory_manager.normalize_persona(persona_mode) == "chancellor":
        try:
            from kuro_backend import finance_db

            finance_block = finance_db.format_ledger_snapshot()
            market_block = finance_db.format_market_snapshot_for_prompt()
        except Exception as exc:
            logger.debug("[MEMORY_COORD] finance/market snapshot skipped: %s", exc)
            finance_block = ""
            market_block = ""

    return {
        "recent_messages": recent_messages,
        "memory_injection": memory_injection,
        "mem0_context_block": mem0_context_block,
        "referent_grounding_block": referent_grounding_block,
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
    """Post-response memory writer for Mem0-only long-term semantic storage."""
    from kuro_backend import perpetual_memory

    _trace_coordinator_span(
        "execute_memory_write_task",
        {"persona": persona_scope, "chars_in": len(user_input or ""), "chars_out": len(final_response or "")},
    )
    logger.info("[MEMORY_COORD] memory_write start persona=%s (mem0-only)", persona_scope)
    payload = f"User: {user_input}\nKuro: {final_response}"
    perpetual_memory.perpetual_memory.store_memories(
        [{"text": payload, "metadata": {"source": "conversation_turn", "persona_scope": persona_scope}}]
    )
    logger.info("[MEMORY_COORD] memory_write done persona=%s (mem0-only)", persona_scope)


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
            result_h = {
                "ok": True,
                "revision": _cs.get_data_revision(),
                "canonical_record_id": str(hid),
            }
            _maybe_emit_proactive_from_mutation(domain, source, payload, result_h)
            return result_h
        if op == "update":
            habit_id = int(payload["habit_id"])
            fields = {
                k: v
                for k, v in payload.items()
                if k not in ("op", "habit_id") and v is not None
            }
            habit_update(habit_id, source=source, **fields)
            result_h = {
                "ok": True,
                "revision": _cs.get_data_revision(),
                "canonical_record_id": str(habit_id),
            }
            _maybe_emit_proactive_from_mutation(domain, source, payload, result_h)
            return result_h
        if op == "delete":
            habit_id = int(payload["habit_id"])
            habit_delete(habit_id, source=source)
            result_h = {
                "ok": True,
                "revision": _cs.get_data_revision(),
                "canonical_record_id": str(habit_id),
            }
            _maybe_emit_proactive_from_mutation(domain, source, payload, result_h)
            return result_h
        return {"ok": False, "error": f"unknown habits op: {op}", "revision": _cs.get_data_revision()}

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
        execute_mem0_extract_task(
            str(payload.get("user_input", "")),
            str(payload.get("final_response", "")),
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
