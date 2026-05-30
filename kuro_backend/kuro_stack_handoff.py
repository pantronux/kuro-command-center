"""Kuro Stack handoff routes for KRC Playground artifacts."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field


AnalysisMode = Literal[
    "auto",
    "summary",
    "integrity",
    "forensic",
    "divergence",
    "ontology",
    "lineage",
    "qa",
]

WorkflowMode = Literal["quick", "deep", "academic"]

DEFAULT_OPENWEBUI_DB = "/home/kuro/projects/kuro-stack/open-webui/data/webui.db"
DEFAULT_OPENWEBUI_BASE_URL = "http://127.0.0.1:3100"
DEFAULT_MODEL_ID = "kuro-kg-gemini-3.1-pro"
API_KEY_NAME = "KRC Playground Handoff"


class KuroStackAnalyzeRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, min_length=3, max_length=80)
    source_label: Optional[str] = Field(default=None, max_length=120)
    output_text: Optional[str] = Field(default=None, max_length=2_000_000)
    analysis_mode: AnalysisMode = "auto"
    workflow_mode: WorkflowMode = "quick"


class KuroStackAnalyzeResponse(BaseModel):
    status: str
    chat_id: str
    chat_url: str
    model: str
    title: str
    analysis_mode: AnalysisMode
    workflow_mode: WorkflowMode
    prompt_chars: int


@dataclass(frozen=True)
class HandoffPayload:
    session_id: str
    source_label: str
    json_text: str


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _openwebui_db_path() -> Path:
    return Path(os.getenv("KURO_STACK_OPENWEBUI_DB_PATH", DEFAULT_OPENWEBUI_DB))


def _openwebui_base_url() -> str:
    return os.getenv("KURO_STACK_OPENWEBUI_BASE_URL", DEFAULT_OPENWEBUI_BASE_URL).rstrip("/")


def _analysis_model_id() -> str:
    return os.getenv("KURO_STACK_ANALYSIS_MODEL", DEFAULT_MODEL_ID).strip() or DEFAULT_MODEL_ID


def _safe_title(session_id: str, mode: str) -> str:
    short_id = session_id if len(session_id) <= 18 else f"{session_id[:15]}..."
    mode_label = mode.title() if mode else "Auto"
    return f"KRC {mode_label} Analysis - {short_id}"


def _get_or_create_openwebui_api_key(db_path: Path) -> str:
    configured = os.getenv("KURO_STACK_OPENWEBUI_API_KEY", "").strip()
    if configured:
        return configured
    if not _env_bool("KURO_STACK_OPENWEBUI_API_KEY_AUTO_CREATE", True):
        raise RuntimeError("KURO_STACK_OPENWEBUI_API_KEY is not configured")
    if not db_path.exists():
        raise RuntimeError(f"Open WebUI database not found: {db_path}")

    conn = sqlite3.connect(str(db_path), timeout=5)
    try:
        user = conn.execute(
            "SELECT id FROM user WHERE role='admin' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if not user:
            user = conn.execute("SELECT id FROM user ORDER BY created_at ASC LIMIT 1").fetchone()
        if not user:
            raise RuntimeError("Open WebUI user table has no user")
        user_id = str(user[0])
        row = conn.execute(
            "SELECT key FROM api_key WHERE user_id=? AND json_extract(data, '$.name')=? LIMIT 1",
            (user_id, API_KEY_NAME),
        ).fetchone()
        if row and str(row[0]).startswith("sk-"):
            return str(row[0])

        now = int(time.time())
        api_key = f"sk-{secrets.token_hex(16)}"
        conn.execute(
            """
            INSERT INTO api_key (id, user_id, key, data, expires_at, last_used_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                user_id,
                api_key,
                json.dumps({"name": API_KEY_NAME}, separators=(",", ":")),
                now,
                now,
            ),
        )
        conn.commit()
        return api_key
    finally:
        conn.close()


def _normalize_json_text(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("No Playground JSON/output was provided")
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except Exception:
        return text


def _mode_header(mode: AnalysisMode, workflow_mode: WorkflowMode) -> str:
    headers = {
        "auto": (
            "Tolong analisis artifact Playground ini sebagai handoff KRC ke Kuro Stack. "
            "Gunakan perspektif yang paling sesuai dengan isi session, lalu jelaskan temuan dan next action."
        ),
        "summary": (
            "Tolong buat ringkasan eksekusi Playground: tujuan prompt, provider/model yang terlibat, "
            "hasil utama, keterbatasan data, dan keputusan operasional yang masuk akal."
        ),
        "integrity": (
            "Tolong audit integrity artifact ini. Fokus pada session_integrity, integrity_overview, "
            "snapshot trust, hash/provenance, status VERIFIED/UNVERIFIED/FAILED, dan risiko bukti."
        ),
        "forensic": (
            "Tolong lakukan forensic review. Bedakan raw evidence, canonical trace, visible reasoning artifact, "
            "provider output, dan asumsi. Jangan mengklaim akses ke hidden chain-of-thought."
        ),
        "divergence": (
            "Tolong analisis semantic divergence dan provider variance. Bandingkan jawaban antar provider, "
            "pola perbedaan, risiko disagreement, dan rekomendasi adjudication."
        ),
        "ontology": (
            "Tolong analisis dari perspektif ontology. Ekstrak entity, relation, klaim, dependency, "
            "celah graph, dan rekomendasi struktur knowledge berikutnya."
        ),
        "lineage": (
            "Tolong analisis lineage dan provenance. Jelaskan alur transformasi raw-to-canonical-to-report, "
            "custody events, titik drift, dan langkah verifikasi ulang."
        ),
        "qa": (
            "Tolong analisis artifact ini sebagai QA/evaluator. Turunkan test idea, ambiguity, coverage gap, "
            "acceptance criteria, dan rekomendasi regression check."
        ),
    }
    workflow_notes = {
        "quick": "Format output ringkas, actionable, dan langsung bisa dipakai.",
        "deep": "Format output mendalam, sertakan risk matrix dan langkah verifikasi teknis.",
        "academic": "Format output seperti review akademik dengan klaim, evidence, limitation, dan citation target.",
    }
    return f"{headers[mode]}\n\nMode review: {workflow_mode}. {workflow_notes[workflow_mode]}"


def build_kuro_stack_analysis_prompt(
    *,
    session_id: str,
    source_label: str,
    json_text: str,
    analysis_mode: AnalysisMode,
    workflow_mode: WorkflowMode,
) -> str:
    normalized = _normalize_json_text(json_text)
    header = _mode_header(analysis_mode, workflow_mode)
    return f"""{header}

Sebelum analisis, panggil Kuro Knowledge Gateway untuk mengambil konteks:
- query="KRC Playground Runtime"
- domain="research"
- max_results=3

File analisis:
- source: {source_label}
- session_id: {session_id or "-"}
- artifact_type: Playground session/output JSON

Output yang diminta:
1. Executive summary singkat.
2. Temuan utama berdasarkan JSON.
3. Integrity/trust state dan dampaknya.
4. Risiko, anomali, atau data yang perlu diverifikasi.
5. Rekomendasi tindakan berikutnya untuk consultant/evaluator.
6. Daftar follow-up prompt yang layak dijalankan di KRC Playground.

Gunakan hanya evidence yang terlihat di JSON dan konteks approved Kuro/KRC. Jika data tidak ada, tulis dengan jelas bahwa datanya tidak tersedia.

```json
{normalized}
```"""


def _build_openwebui_request(prompt: str, model_id: str) -> dict:
    user_message_id = str(uuid.uuid4())
    assistant_message_id = str(uuid.uuid4())
    now = int(time.time())
    return {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "parent_id": None,
        "id": assistant_message_id,
        "session_id": f"krc-handoff-{uuid.uuid4()}",
        "user_message": {
            "id": user_message_id,
            "parentId": None,
            "childrenIds": [assistant_message_id],
            "role": "user",
            "content": prompt,
            "timestamp": now,
            "models": [model_id],
        },
        "params": {"function_calling": "default"},
    }


def create_openwebui_analysis_chat(prompt: str) -> tuple[str, str]:
    db_path = _openwebui_db_path()
    api_key = _get_or_create_openwebui_api_key(db_path)
    model_id = _analysis_model_id()
    response = requests.post(
        f"{_openwebui_base_url()}/api/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=_build_openwebui_request(prompt, model_id),
        timeout=float(os.getenv("KURO_STACK_HANDOFF_TIMEOUT_S", "45")),
    )
    if response.status_code >= 400:
        detail = response.text[:500]
        raise RuntimeError(f"Open WebUI handoff failed ({response.status_code}): {detail}")
    payload = response.json()
    chat_id = payload.get("chat_id")
    if not chat_id:
        raise RuntimeError("Open WebUI did not return a chat_id")
    return str(chat_id), model_id


def update_openwebui_chat_title(chat_id: str, title: str) -> None:
    db_path = _openwebui_db_path()
    if not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path), timeout=5)
    try:
        row = conn.execute("SELECT chat FROM chat WHERE id=?", (chat_id,)).fetchone()
        if not row:
            return
        try:
            chat = json.loads(row[0] or "{}")
        except Exception:
            chat = {}
        chat["title"] = title
        conn.execute(
            "UPDATE chat SET title=?, chat=?, updated_at=? WHERE id=?",
            (title, json.dumps(chat, ensure_ascii=False), int(time.time()), chat_id),
        )
        conn.commit()
    finally:
        conn.close()


def _resolve_payload(request: KuroStackAnalyzeRequest, playground_service) -> HandoffPayload:
    if request.session_id:
        if playground_service is None:
            raise HTTPException(status_code=503, detail="Playground service is not mounted")
        try:
            _filename, payload = playground_service.build_session_json_artifact(
                session_id=request.session_id,
                artifact_type="session",
            )
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return HandoffPayload(
            session_id=request.session_id,
            source_label=request.source_label or "KRC Playground session artifact",
            json_text=payload,
        )
    if request.output_text:
        return HandoffPayload(
            session_id="-",
            source_label=request.source_label or "KRC Playground output panel",
            json_text=request.output_text,
        )
    raise HTTPException(status_code=422, detail="session_id or output_text is required")


def create_kuro_stack_handoff_router(auth_dependency: Callable) -> APIRouter:
    router = APIRouter(prefix="/api/integrations/kuro-stack", tags=["kuro-stack-handoff"])

    @router.post("/analyze-playground", response_model=KuroStackAnalyzeResponse)
    def analyze_playground(
        payload: KuroStackAnalyzeRequest,
        request: Request,
        _user: dict = Depends(auth_dependency),
    ):
        playground_service = getattr(getattr(request.app, "state", None), "playground_service", None)
        resolved = _resolve_payload(payload, playground_service)
        title = _safe_title(resolved.session_id, payload.analysis_mode)
        prompt = build_kuro_stack_analysis_prompt(
            session_id=resolved.session_id,
            source_label=resolved.source_label,
            json_text=resolved.json_text,
            analysis_mode=payload.analysis_mode,
            workflow_mode=payload.workflow_mode,
        )
        try:
            chat_id, model_id = create_openwebui_analysis_chat(prompt)
            update_openwebui_chat_title(chat_id, title)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return KuroStackAnalyzeResponse(
            status="created",
            chat_id=chat_id,
            chat_url=f"/c/{chat_id}",
            model=model_id,
            title=title,
            analysis_mode=payload.analysis_mode,
            workflow_mode=payload.workflow_mode,
            prompt_chars=len(prompt),
        )

    return router

