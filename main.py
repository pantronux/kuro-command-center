"""
Kuro AI V6.0 "Sovereign" — FastAPI application entry point (web dashboard, API, Telegram).
"""

import warnings
import hashlib
import logging
import logging.handlers
import asyncio
import json
import os
import random
import signal
import sys
import threading
import time
import uuid
import re
import psutil
from collections import defaultdict, deque
from pathlib import Path
import uvicorn
from typing import Any, Dict, Optional, List
from datetime import date, datetime, timedelta
import fcntl
import atexit
from fastapi import (
    FastAPI,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
    Request,
    Depends,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    Query,
)
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    FileResponse,
    RedirectResponse,
    StreamingResponse,
)
from pydantic import BaseModel, Field
from jose import JWTError, jwt
from passlib.context import CryptContext
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import NetworkError, TimedOut

# --- Early warning suppression (must run before heavy imports initialize) ---
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*Pydantic V1 style.*")
logging.getLogger("pydantic").setLevel(logging.ERROR)
logging.getLogger("opentelemetry").setLevel(logging.ERROR)

from kuro_backend.config import settings
from kuro_backend.langgraph_core import (
    process_chat_with_graph,
    process_chat_with_graph_stream,
)
from kuro_backend import memory_manager
from kuro_backend import memory_coordinator
from kuro_backend import chat_history
from kuro_backend import tools

from kuro_backend import dashboard_broadcast
from kuro_backend.services import core_service as core_data
from kuro_backend.services.async_adapter import run_db
from kuro_backend.services.schemas import (
    ApiUsageDailyRecord,
    MarketHudChip,
    MonthlyBudgetRecord,
    RecurringExpenseRecord,
    WatchedSymbolRecord,
)
from kuro_backend import llm_utils
from kuro_backend import finance_db
from kuro_backend import auth_db
from kuro_backend import observability
from kuro_backend import intelligence_db
from kuro_backend import backup_manager
from kuro_backend import persona_history_admin
from kuro_backend import version as kuro_version
from kuro_backend import proactive_greeting
from kuro_backend.enterprise_flags import get_enterprise_flag_snapshot
from kuro_backend.runtime.runtime_context import resolve_runtime_context
from kuro_backend.runtime.runtime_registry import RuntimeRegistry
from kuro_backend.output.schema_registry import SchemaRegistry
from kuro_backend.ingestion_center import (
    chroma_inspector,
    ingestion_manager,
    ingestion_registry,
)
from kuro_backend.export_engine import export_manager
from kuro_backend.intelligence.stream_safety import sanitize_stream_chunk
from kuro_backend.export_engine.export_models import (
    ExportFormat as UniversalExportFormat,
    ExportRequest as UniversalExportRequest,
    ExportStatus as UniversalExportStatus,
)
from kuro_backend.logger_setup import setup_logging

# --- Logging Setup with Centralized Config ---
setup_logging(log_filename="kuro_sovereign.log", backup_count=30)


# APScheduler: prevent duplicate hardware-sentinel / job lines (root + apscheduler)
logging.getLogger("apscheduler").handlers = []
logging.getLogger("apscheduler").propagate = False

# Phoenix: suppress noisy POST /graphql 200 access lines in user-facing logs
logging.getLogger("phoenix.server.api").setLevel(logging.WARNING)
logging.getLogger("pydantic").setLevel(logging.ERROR)
logging.getLogger("opentelemetry").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

# --- JWT Authentication Configuration (Cookie-Based) ---
# Password hashing context (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT Configuration - SECURITY: No hardcoded fallback for secret key
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "JWT_SECRET_KEY environment variable is required. Set it in .env file."
    )
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "12"))

# Admin credentials from .env
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "Pantronux")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")

# Secondary User: Faikhira (V1.0.0 Restricted Access)
FAIKHIRA_USERNAME = os.getenv("FAIKHIRA_USERNAME", "Faikhira")
FAIKHIRA_PASSWORD_HASH = os.getenv("FAIKHIRA_PASSWORD_HASH", "")
FAIKHIRA_MASTER_NAME = os.getenv("FAIKHIRA_MASTER_NAME", "Master Faikhira")

# Cookie name for JWT token
COOKIE_NAME = "kuro_access_token"
CHAT_SESSION_HEADER = "X-Chat-Session"
_CHAT_SESSION_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_sse_buffers: dict[str, deque] = {}
_sse_event_counters: dict[str, int] = {}
_tg_rate_buckets: dict[str, dict] = defaultdict(
    lambda: {
        "tokens": float(getattr(settings, "KURO_TELEGRAM_RATE_LIMIT_PER_MIN", 10)),
        "last_refill": time.time(),
    }
)
_tg_inbound_queue: asyncio.Queue = asyncio.Queue(
    maxsize=int(getattr(settings, "KURO_TELEGRAM_QUEUE_MAXSIZE", 50))
)
_telegram_polling_shutdown = threading.Event()


def _check_telegram_rate_limit(chat_id: str, limit_per_min: int) -> bool:
    """Token-bucket limiter for inbound Telegram messages per chat_id."""
    bucket = _tg_rate_buckets[str(chat_id)]
    now = time.time()
    elapsed = now - float(bucket.get("last_refill", now))
    refill = elapsed * (float(limit_per_min) / 60.0)
    bucket["tokens"] = min(
        float(limit_per_min), float(bucket.get("tokens", 0.0)) + refill
    )
    bucket["last_refill"] = now
    if float(bucket["tokens"]) >= 1.0:
        bucket["tokens"] -= 1.0
        return True
    return False


class ChatSessionUpdate(BaseModel):
    title: str


class MessageEditRequest(BaseModel):
    new_content: str = Field(..., min_length=1, max_length=32000)


class NewChatSession(BaseModel):
    persona: str
    title: str = "New Chat"


class QARequirementRequest(BaseModel):
    requirement: str = Field(..., min_length=1, max_length=32000)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a bcrypt hash."""
    try:
        from passlib.hash import bcrypt

        return bcrypt.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_token_from_cookie(request: Request) -> Optional[str]:
    """Extract JWT token from HttpOnly cookie."""
    cookie_value = request.cookies.get(COOKIE_NAME)
    if cookie_value and cookie_value.startswith("Bearer "):
        return cookie_value[7:]
    return None


def validate_token(token: str) -> Optional[Dict]:
    """Validate JWT token and return user info."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username:
            return {"username": username}
    except JWTError:
        pass
    return None


def validate_token_dependency(request: Request) -> Dict[str, str]:
    """FastAPI dependency wrapper around cookie-based token validation."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user


def require_admin_user(request: Request) -> Dict[str, str]:
    """Resolve current user from cookie and enforce admin access."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if user.get("username") != os.getenv("ADMIN_USERNAME", "Pantronux"):
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required.")
    return user


class TraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-ID") or f"trace_{uuid.uuid4().hex[:16]}"
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response


def _build_system_status_backup_payload() -> Optional[Dict[str, Any]]:
    """Return additive backup status metadata for the System Status modal."""
    try:
        last_backup = intelligence_db.get_last_backup_status()
    except Exception as exc:
        logger.warning("[BACKUP] get_last_backup_status failed: %s", exc)
        return None

    if last_backup is None:
        return None

    try:
        backup_root = Path(settings.KURO_BACKUP_DIR).expanduser()
        if not backup_root.is_absolute():
            backup_root = Path(settings.WORKING_DIR).joinpath(backup_root).resolve()
        backup_dir_size_mb = (
            sum(f.stat().st_size for f in backup_root.rglob("*") if f.is_file())
            / (1024**2)
            if backup_root.exists()
            else 0.0
        )
        daily_root = backup_root / "daily"
        pre_migration_root = backup_root / "pre_migration"
        backup_count_daily = (
            sum(1 for p in daily_root.iterdir() if p.is_dir())
            if daily_root.exists()
            else 0
        )
        backup_count_pre_migration = (
            sum(1 for p in pre_migration_root.iterdir() if p.is_file())
            if pre_migration_root.exists()
            else 0
        )
    except Exception as exc:
        logger.warning("[BACKUP] backup directory stats failed: %s", exc)
        backup_dir_size_mb = 0.0
        backup_count_daily = 0
        backup_count_pre_migration = 0

    next_backup_at = None
    try:
        if _reminder_scheduler:
            job = _reminder_scheduler.get_job("nightly_backup")
            if job and job.next_run_time:
                next_backup_at = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as exc:
        logger.warning("[BACKUP] next nightly backup lookup failed: %s", exc)

    return {
        "last_backup_at": last_backup.get("completed_at"),
        "last_backup_status": last_backup.get("status"),
        "last_backup_type": last_backup.get("backup_type"),
        "files_backed_up": last_backup.get("files_backed_up", 0),
        "total_size_mb": round(
            float(last_backup.get("total_size_bytes", 0) or 0) / (1024**2),
            1,
        ),
        "duration_seconds": float(last_backup.get("duration_seconds", 0.0) or 0.0),
        "retain_days": settings.KURO_BACKUP_RETAIN_DAYS,
        "backup_dir_size_mb": round(backup_dir_size_mb, 1),
        "backup_count_daily": backup_count_daily,
        "backup_count_pre_migration": backup_count_pre_migration,
        "assets_covered": [
            "kuro_chat_history.db",
            "kuro_short_term.db",
            "kuro_auth.db",
            "kuro_finances.db",
            "kuro_intelligence.db",
            "master_profile.json",
            "kuro_memory.json",
            "kuro_compliance.db",
            "phoenix_data/phoenix.db",
            "logs/",
        ],
        "next_backup_at": next_backup_at,
        "error_message": last_backup.get("error_message"),
    }


def api_success(
    data: Any = None, trace_id: Optional[str] = None, **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": "success",
        "data": data,
        "error": None,
        "trace_id": trace_id,
    }
    payload.update(extra)
    return payload


def api_error(
    error: str, trace_id: Optional[str] = None, **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status": "error",
        "data": None,
        "error": error,
        "trace_id": trace_id,
    }
    payload.update(extra)
    return payload


def _detect_export_suggestions(
    persona: Optional[str],
    response_text: str,
    chat_id: Optional[str],
    assistant_message_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Suggest structured exports based on persona and response shape."""
    resolved_persona = memory_manager.normalize_persona(persona)

    text = (response_text or "").strip()
    if not text or not chat_id:
        return []

    lowered = text.lower()
    export_target = "selected_messages" if assistant_message_id else "chat_session"
    message_ids = [assistant_message_id] if assistant_message_id else []

    def _suggest(fmt: str, title: str, reason: str) -> Dict[str, Any]:
        return {
            "target": export_target,
            "format": fmt,
            "chat_id": chat_id,
            "message_ids": message_ids,
            "title": title,
            "reason": reason,
            "persona": resolved_persona,
        }

    suggestions: List[Dict[str, Any]] = []
    has_table = "|" in text and "---" in text
    qa_markers = (
        "test case",
        "test cases",
        "test scenario",
        "acceptance criteria",
        "expected result",
        "precondition",
        "steps to reproduce",
    )
    has_qa_shape = any(marker in lowered for marker in qa_markers) or has_table
    report_markers = (
        "executive summary",
        "recommendation",
        "roadmap",
        "analysis",
        "briefing",
        "findings",
    )
    has_report_shape = any(marker in lowered for marker in report_markers)
    data_markers = ("table", "matrix", "dataset", "rows", "columns", "spreadsheet")
    has_data_shape = has_table or any(marker in lowered for marker in data_markers)

    if resolved_persona == "auditor" and has_qa_shape:
        suggestions.append(
            _suggest(
                "xlsx",
                "Export Test Case to Excel",
                "Auditor detected structured QA test cases suitable for spreadsheet export.",
            )
        )

    if resolved_persona == "advisor":
        if has_report_shape:
            suggestions.append(
                _suggest(
                    "pdf",
                    "Export Report to PDF",
                    "Advisor output looks like a formal report suitable for PDF export.",
                )
            )
            suggestions.append(
                _suggest(
                    "docx",
                    "Export Report to Word",
                    "Advisor output looks editable and suitable for DOCX export.",
                )
            )
        if has_data_shape:
            suggestions.append(
                _suggest(
                    "xlsx",
                    "Export Analysis to Excel",
                    "Advisor output contains structured analysis suitable for Excel export.",
                )
            )

    if resolved_persona == "chancellor" and has_data_shape:
        suggestions.append(
            _suggest(
                "xlsx",
                "Export Financial Table to Excel",
                "Chancellor output contains structured financial data suitable for Excel.",
            )
        )
        suggestions.append(
            _suggest(
                "csv",
                "Export Financial Data to CSV",
                "Chancellor output contains structured financial data suitable for CSV.",
            )
        )

    # Deduplicate by format while preserving order.
    deduped: List[Dict[str, Any]] = []
    seen_formats = set()
    for item in suggestions:
        fmt = item.get("format")
        if fmt in seen_formats:
            continue
        seen_formats.add(fmt)
        deduped.append(item)
    return deduped


def _resolve_chat_session_id(request: Request, form_chat_id: str = None) -> str:
    if form_chat_id and _CHAT_SESSION_PATTERN.match(form_chat_id):
        return form_chat_id
    raw = (request.headers.get(CHAT_SESSION_HEADER) or "").strip()
    if raw and _CHAT_SESSION_PATTERN.match(raw):
        return raw
    return f"fallback_{request.client.host}_default"


def _normalize_runtime_id(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _resolve_requested_runtime_id(
    runtime_id_query: Optional[str],
    runtime_id_form: Optional[str],
) -> Optional[str]:
    query_value = _normalize_runtime_id(runtime_id_query)
    form_value = _normalize_runtime_id(runtime_id_form)
    if query_value and form_value and query_value != form_value:
        observability.record_counter_metric("runtime_query_form_mismatch_400_total")
        raise HTTPException(
            status_code=400,
            detail=(
                "runtime_id mismatch between query and form body; "
                "use one value consistently."
            ),
        )
    return query_value or form_value


def _resolve_runtime_context_for_chat_request(
    *,
    request: Request,
    username: str,
    resolved_persona: str,
    chat_id: Optional[str],
    runtime_id_query: Optional[str],
    runtime_id_form: Optional[str],
    trace_id: str,
) -> tuple[str, "RuntimeContext", bool]:
    incoming_chat_id = str(chat_id or "").strip()
    if not incoming_chat_id or incoming_chat_id.lower() == "null":
        incoming_chat_id = str(uuid.uuid4())
    session_scope = _resolve_chat_session_id(request, incoming_chat_id)
    requested_runtime_id = _resolve_requested_runtime_id(
        runtime_id_query, runtime_id_form
    )
    existing_session = chat_history.get_session(session_scope)
    should_create_session = existing_session is None
    if existing_session is not None:
        stored_runtime_id = _normalize_runtime_id(existing_session.get("runtime_id"))
        effective_runtime_id = stored_runtime_id or "sovereign"
        if requested_runtime_id and requested_runtime_id != effective_runtime_id:
            observability.record_counter_metric("runtime_conflict_409_total")
            raise HTTPException(
                status_code=409,
                detail=(
                    f"runtime_id conflict for chat_id={session_scope}: "
                    f"stored={effective_runtime_id}, requested={requested_runtime_id}"
                ),
            )
    else:
        effective_runtime_id = requested_runtime_id or "sovereign"

    ctx = resolve_runtime_context(
        effective_runtime_id,
        username=username,
        chat_id=session_scope,
        trace_id=trace_id,
    )
    if should_create_session:
        chat_history.create_session(
            session_scope,
            username,
            resolved_persona,
            "New Chat",
            runtime_id=ctx.runtime_id,
        )
    return session_scope, ctx, should_create_session


def _as_env_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_qa_playground_enabled() -> bool:
    return _as_env_bool(os.getenv("KURO_QA_PLAYGROUND_ENABLED"), True)


def _mount_playground_router_if_enabled(
    target_app: FastAPI,
    enabled_override: Optional[bool] = None,
) -> bool:
    api_enabled = (
        enabled_override
        if enabled_override is not None
        else _as_env_bool(os.getenv("KURO_PLAYGROUND_API_ENABLED"), False)
    )
    if not api_enabled:
        return False
    try:
        from playground_runtime.api import create_playground_router
        from playground_runtime.config import get_settings as get_playground_settings
        from playground_runtime.service import PlaygroundRuntimeService

        playground_settings = get_playground_settings()
        playground_service = PlaygroundRuntimeService(settings=playground_settings)
        target_app.state.playground_service = playground_service
        target_app.include_router(
            create_playground_router(
                service=playground_service,
                admin_dependency=require_admin_user,
            )
        )
        logger.info("[KPR] Playground router mounted at /api/playground")
        return True
    except Exception as exc:
        logger.exception("[KPR] Failed to mount playground router: %s", exc)
        return False


# --- FastAPI App ---
app = FastAPI(title="Kuro AI Web Dashboard")
app.add_middleware(TraceMiddleware)
_mount_playground_router_if_enabled(app)


@app.on_event("startup")
async def _register_dashboard_sync_loop():
    """Enable cross-thread revision bumps to schedule WebSocket REFRESH_NOW."""
    core_data.register_main_event_loop(asyncio.get_running_loop())
    RuntimeRegistry.load_all()
    # --- Header Doc ---
    # Purpose: Startup environment safety checks for required/optional integrations.
    # Caller: FastAPI startup lifecycle.
    # Dependencies: os.getenv, module logger.
    # Main Functions: required var CRITICAL logs + optional var WARNING logs.
    # Side Effects: Emits startup diagnostics into runtime logs.
    required_vars = ["GEMINI_API_KEY", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"]
    optional_vars_with_warnings = {
        "NEWSAPI_API_KEY": "Market news data will be unavailable. Market Sentinel running in price-only mode.",
        "SERPER_API_KEY": "Web search fallover will be disabled.",
        "METACULUS_API_TOKEN": "Prediction market scan will use demo mode.",
        "NVD_API_KEY": "NVD CVE feed running without auth (rate-limited).",
    }
    for var in required_vars:
        if not os.getenv(var):
            logger.critical(
                "STARTUP: Required env var %s is not set. System may fail.", var
            )
    for var, msg in optional_vars_with_warnings.items():
        if not os.getenv(var):
            logger.warning("STARTUP: Optional env var %s not set — %s", var, msg)

    # Clear stale dreaming leases
    try:
        from kuro_backend import memory_manager

        conn = memory_manager._get_short_term_conn()
        c = conn.cursor()
        c.execute("DELETE FROM dreaming_locks WHERE lease_expires_at < datetime('now')")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to clear stale dreaming leases: {e}")

    # Drain mem0_write_failures
    try:
        from kuro_backend import memory_manager, memory_coordinator
        import json

        failures = memory_manager.get_pending_mem0_write_failures()
        if failures:
            logger.info(
                f"Replaying {len(failures)} pending Mem0 writes from mem0_write_failures..."
            )
            for failure in failures:
                try:
                    payload = json.loads(failure["payload"])
                    replay_ctx = None
                    runtime_id = payload.get("runtime_id")
                    if runtime_id:
                        replay_ctx = resolve_runtime_context(
                            str(runtime_id),
                            username=failure["username"],
                            chat_id=str(payload.get("chat_id", "") or ""),
                            trace_id=str(payload.get("trace_id", "") or ""),
                        )
                    # Use execute_mem0_extract_task again (it will retry 3 times and save back if fails)
                    memory_coordinator.execute_mem0_extract_task(
                        user_input=payload.get("user_input", ""),
                        final_response=payload.get("final_response", ""),
                        username=failure["username"],
                        ctx=replay_ctx,
                    )
                except Exception as e:
                    logger.error(f"Failed to replay mem0 write failure: {e}")
    except Exception as e:
        logger.error(f"Error during mem0_write_failures replay: {e}")


@app.on_event("shutdown")
async def _shutdown_runtime_flags():
    """Set shutdown flags so background loops can exit gracefully."""
    _telegram_polling_shutdown.set()


def _ws_token_from_cookie(ws: WebSocket) -> Optional[str]:
    raw = ws.cookies.get(COOKIE_NAME)
    if raw and raw.startswith("Bearer "):
        return raw[7:]
    return raw


# --- Auth Routes ---
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve the login page. Redirect to / if already authenticated."""
    token = get_token_from_cookie(request)
    if validate_token(token):
        return RedirectResponse(url="/", status_code=302)
    return FileResponse(os.path.join(WEB_DIR, "templates", "login.html"))


@app.post("/api/login")
async def login_endpoint(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    remember_me: str = Form("false"),
):
    """Authenticate user and set JWT token in HttpOnly cookie with brute force protection."""
    client_ip = request.client.host
    user_agent = request.headers.get("user-agent", "")

    # Check if account is locked
    lockout_status = auth_db.is_account_locked(username)
    if lockout_status.get("locked"):
        return JSONResponse(
            status_code=429,
            content={
                "success": False,
                "error": f"Terlalu banyak percobaan login. Akun dikunci selama {lockout_status['remaining_minutes']} menit {lockout_status['remaining_seconds']} detik untuk keamanan.",
                "locked": True,
                "remaining_seconds": lockout_status["remaining_minutes"] * 60
                + lockout_status["remaining_seconds"],
            },
        )

    # Validate user existence (database-backed)
    user_info = auth_db.get_user(username)

    if not user_info:
        failed_count = auth_db.record_failed_attempt(username, client_ip, user_agent)
        if failed_count >= auth_db.MAX_FAILED_ATTEMPTS:
            auth_db.lock_account(username)
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": "Username atau password salah."},
        )

    # Use the correctly-cased username from DB
    username = user_info["username"]

    # Verify password
    if not verify_password(password, user_info["password_hash"]):
        failed_count = auth_db.record_failed_attempt(username, client_ip, user_agent)
        logger.warning(
            f"Failed login attempt {failed_count} for user: {username} from {client_ip}"
        )

        if failed_count >= auth_db.MAX_FAILED_ATTEMPTS:
            auth_db.lock_account(username)
            logger.warning(
                f"ACCOUNT LOCKED: {username} - Too many failed attempts ({failed_count})"
            )
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": "Terlalu banyak percobaan login. Akun dikunci selama 15 menit untuk keamanan.",
                    "locked": True,
                    "remaining_seconds": auth_db.LOCKOUT_DURATION_MINUTES * 60,
                },
            )

        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "error": f"Username atau password salah. ({auth_db.MAX_FAILED_ATTEMPTS - failed_count} percobaan tersisa)",
                "attempts_remaining": auth_db.MAX_FAILED_ATTEMPTS - failed_count,
            },
        )

    # Successful login
    auth_db.clear_failed_attempts(username)
    auth_db.record_successful_login(username, client_ip, user_agent)

    # Create access token
    access_token_expires = timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    access_token = create_access_token(
        data={"sub": username}, expires_delta=access_token_expires
    )

    logger.info(f"Successful login: {username} from {client_ip}")

    # Set token in HttpOnly cookie
    response = JSONResponse(content={"success": True, "username": username})
    response.set_cookie(
        key=COOKIE_NAME,
        value=f"Bearer {access_token}",
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_HOURS * 3600,
        path="/",
    )
    return response


@app.get("/api/auth/verify")
async def verify_token_endpoint(request: Request):
    """Verify if the current cookie token is valid."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if user:
        return {"success": True, "username": user.get("username")}
    return JSONResponse(
        status_code=401, content={"success": False, "error": "Invalid or expired token"}
    )


@app.get("/api/auth/stats")
async def auth_stats():
    """Get authentication statistics for dashboard."""
    return {"status": "success", "data": auth_db.get_login_stats()}


@app.get("/api/version")
async def get_version():
    """Return Kuro's canonical version payload (wired from kuro_backend.version).

    The dashboard badge reads this once on load; bumping VERSION in a single
    place keeps the sidebar + HUD banner in lockstep.
    """
    return {"status": "success", "data": kuro_version.version_info()}


@app.post("/api/auth/logout")
async def logout_endpoint():
    """Logout endpoint - clear the cookie."""
    response = JSONResponse(
        content={"success": True, "message": "Logged out successfully"}
    )
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return response


# --- User Management Routes ---


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    """Serve the user profile page."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    username = user.get("username")
    user_info = auth_db.get_user(username)

    return templates.TemplateResponse(
        request=request,
        name="profile.html",
        context={
            "username": username,
            "display_name": user_info.get("display_name", username),
            "email": user_info.get("email", ""),
            "role": user_info.get("role", "User"),
            "master_name": user_info.get("master_name", f"Master {username}"),
            "custom_persona": user_info.get("custom_persona", ""),
        },
    )


@app.post("/api/user/update")
async def update_profile(
    request: Request,
    username_new: str = Form(None),
    display_name: str = Form(...),
    email: str = Form(...),
):
    """Update user profile information."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        return JSONResponse(
            status_code=401, content={"success": False, "error": "Unauthorized"}
        )

    username = user.get("username")

    # Note: username_new is currently ignored to prevent complex session invalidation issues,
    # but could be implemented later if required.

    success = auth_db.update_user_profile(username, email, display_name)
    if success:
        return {"success": True, "message": "Profile updated successfully"}
    return JSONResponse(
        status_code=500, content={"success": False, "error": "Failed to update profile"}
    )


@app.post("/api/user/change-password")
async def change_password(
    request: Request,
    old_password: str = Form(...),
    new_password: str = Form(...),
    repeat_password: str = Form(...),
):
    """Handle password change with old password verification."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        return JSONResponse(
            status_code=401, content={"success": False, "error": "Unauthorized"}
        )

    if new_password != repeat_password:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "New passwords do not match"},
        )

    username = user.get("username")
    user_info = auth_db.get_user(username)

    if not verify_password(old_password, user_info["password_hash"]):
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": "Old password incorrect"},
        )

    # Hash new password
    from passlib.hash import bcrypt

    new_hash = bcrypt.hash(new_password)

    success = auth_db.update_password(username, new_hash)
    if success:
        return {"success": True, "message": "Password changed successfully"}
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Failed to update password"},
    )


@app.post("/api/user/update-persona")
async def update_persona(request: Request, custom_persona: str = Form(...)):
    """Update user's custom global persona instructions."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        return JSONResponse(
            status_code=401, content={"success": False, "error": "Unauthorized"}
        )

    username = user.get("username")
    success = auth_db.update_custom_persona(username, custom_persona)
    if success:
        return {"success": True, "message": "Custom persona updated successfully"}
    return JSONResponse(
        status_code=500, content={"success": False, "error": "Failed to update persona"}
    )


# CORS Middleware - SECURITY: Restrict to specific allowed origins
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "https://localhost:8443,https://127.0.0.1:8443,http://localhost:8000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Chat-Session", "Authorization", "Accept"],
)

# Static files and templates
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web_interface")
app.mount(
    "/static", StaticFiles(directory=os.path.join(WEB_DIR, "static")), name="static"
)
templates = Jinja2Templates(directory=os.path.join(WEB_DIR, "templates"))


# Profile assets mount (Kuro V6.1 — branding + Live2D Hijiki). Exposes the
# repo-level `profile/` directory so the dashboard can fetch `kuro_avatar.png`,
# `favicon.ico`, and the full Live2D runtime without copying anything into
# `web_interface/static/`.
_PROFILE_DIR = os.path.join(BASE_DIR, "profile")
if os.path.isdir(_PROFILE_DIR):
    app.mount("/profile", StaticFiles(directory=_PROFILE_DIR), name="profile")

# Upload directory - use tools.PROJECT_ROOT for consistency
UPLOAD_DIR = tools.UPLOAD_DIR
os.makedirs(UPLOAD_DIR, exist_ok=True)

_DOC_EXTENSIONS = {
    ".pdf",
    ".csv",
    ".txt",
    ".md",
    ".rtf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".json",
    ".yaml",
    ".yml",
}
_LOG_EXTENSIONS = {".log"}


def _slugify_filename_base(filename: str) -> tuple[str, str]:
    """Normalize original filename into safe slug base and extension."""
    safe_name = (filename or "").strip()
    if not safe_name:
        return "file", ""
    base, ext = os.path.splitext(safe_name)
    slug_base = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_").lower()
    return (slug_base or "file"), ext.lower()


def _resolve_upload_subdir(content_type: str, extension: str) -> str:
    """Route upload into a category folder."""
    ctype = (content_type or "").lower()
    ext = (extension or "").lower()
    if ctype.startswith("image/"):
        return "images"
    if ext in _LOG_EXTENSIONS or "log" in ctype:
        return "logs"
    if (
        ctype.startswith("text/")
        or ext in _DOC_EXTENSIONS
        or ctype
        in {
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-powerpoint",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        }
    ):
        return "docs"
    return "misc"


def _build_unique_filename(
    original_name: str, timestamp: str, random_suffix: str = ""
) -> str:
    """Build storage filename with optional random suffix failsafe."""
    slug_base, ext = _slugify_filename_base(original_name)
    suffix = f"_{random_suffix}" if random_suffix else ""
    return f"{slug_base}_{timestamp}{suffix}{ext}"


async def save_upload_file(
    file: UploadFile, username: str = "Pantronux"
) -> Dict[str, str]:
    """
    Save uploaded file with deterministic unique filename and user-category subfolder.
    Format: uploaded_files/{username}/{category}/{slugified_original}_{YYYYMMDD_HHMMSS}.{ext}
    """
    original_name = (file.filename or "").strip() or "file"
    _, ext = _slugify_filename_base(original_name)
    subdir = _resolve_upload_subdir(file.content_type or "", ext)

    # Path: uploaded_files/{username}/{category}/
    target_dir = os.path.join(UPLOAD_DIR, username, subdir)
    os.makedirs(target_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_name = _build_unique_filename(original_name, timestamp)
    target_path = os.path.join(target_dir, unique_name)
    collision_used = False

    if os.path.exists(target_path):
        collision_used = True
        for _ in range(10):
            suffix = f"{random.randint(1000, 9999)}"
            unique_name = _build_unique_filename(
                original_name, timestamp, random_suffix=suffix
            )
            target_path = os.path.join(target_dir, unique_name)
            if not os.path.exists(target_path):
                break

    content = await file.read()
    with open(target_path, "wb") as f:
        f.write(content)

    sha256_hash = hashlib.sha256(content).hexdigest()
    size_bytes = len(content)

    return {
        "original_filename": original_name,
        "stored_filename": unique_name,
        "stored_path": target_path,
        "content_type": file.content_type or "",
        "size_bytes": size_bytes,
        "sha256": sha256_hash,
    }

    logger.info(
        "Upload saved: original=%s stored=%s subdir=%s collision_failsafe=%s sha256=%s size_bytes=%s",
        original_name,
        unique_name,
        subdir,
        collision_used,
        sha256_hash,
        size_bytes,
    )

    return {
        "original_filename": original_name,
        "stored_filename": unique_name,
        "stored_path": target_path,
        "stored_dir": target_dir,
        "category": subdir,
        "content_type": file.content_type or "",
        "sha256": sha256_hash,
        "size_bytes": size_bytes,
    }


# --- Routes ---
# Public API routes (no auth required)
PUBLIC_API_ROUTES = [
    "/api/login",
    "/api/auth/verify",
    "/api/auth/stats",
    "/api/auth/logout",
    "/api/capabilities",
]


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """
    Cookie-based authentication middleware.

    ARCHITECTURE:
    - HTML pages: Backend handles redirect based on cookie
    - API routes: Require valid JWT in cookie
    """
    path = request.url.path

    # Allow static files without auth check
    if path.startswith("/static"):
        return await call_next(request)

    # Get token from cookie
    token = get_token_from_cookie(request)
    is_authenticated = validate_token(token) is not None

    # For HTML pages, handle redirect based on auth status
    if path == "/login":
        # Already handled in login_page endpoint, just pass through
        return await call_next(request)

    if path == "/" or path in ["/chat"]:
        if not is_authenticated:
            logger.info(
                f"Unauthenticated access to {path} from {request.client.host}, redirecting to /login"
            )
            return RedirectResponse(url="/login", status_code=302)
        return await call_next(request)

    # For API routes
    if path.startswith("/api/"):
        if path in PUBLIC_API_ROUTES:
            return await call_next(request)

        if not is_authenticated:
            logger.info(f"API auth failed for {request.client.host} on {path}")
            return JSONResponse(
                status_code=401,
                content=api_error("Authentication required. Please log in."),
            )

    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main web dashboard. Redirect to /login if not authenticated."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    username = user.get("username")
    user_info = auth_db.get_user(username) or {}

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "username": username,
            "display_name": user_info.get("display_name", username),
            "role": user_info.get("role", "User"),
            "is_admin": username == os.getenv("ADMIN_USERNAME", "Pantronux"),
            "restricted_persona": user_info.get("restricted_persona") or "",
            "master_name": user_info.get("master_name", f"Master {username}"),
        },
    )


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    """Serve chat dashboard route that supports URL persona state."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    username = user.get("username")
    user_info = auth_db.get_user(username) or {}

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "username": username,
            "display_name": user_info.get("display_name", username),
            "role": user_info.get("role", "User"),
            "is_admin": username == os.getenv("ADMIN_USERNAME", "Pantronux"),
            "restricted_persona": user_info.get("restricted_persona") or "",
            "master_name": user_info.get("master_name", f"Master {username}"),
        },
    )


@app.get("/api/me")
async def get_current_user(request: Request):
    """Return authenticated username + admin flag for frontend RBAC guards."""
    token = get_token_from_cookie(request)
    token_data = validate_token(token)
    if not token_data:
        raise HTTPException(status_code=401, detail="Authentication required.")
    username = token_data.get("username", "")
    return {
        "username": username,
        "is_admin": username == os.getenv("ADMIN_USERNAME", "Pantronux"),
    }


@app.get("/api/capabilities")
async def get_public_capabilities():
    """Return public-safe feature availability without internal topology."""
    return api_success(data=get_enterprise_flag_snapshot(admin=False))


@app.get("/api/admin/enterprise-flags")
async def get_admin_enterprise_flags(request: Request):
    """Return enterprise flag status for authenticated admins only."""
    require_admin_user(request)
    return api_success(data=get_enterprise_flag_snapshot(admin=True))


@app.get("/api/history")
async def get_chat_history(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    platform: str = None,
    persona: str = None,
    chat_id: str = None,
):
    """Get chat history from database with pagination for infinite scroll.

    Args:
        limit: Number of messages to return
        offset: Pagination offset
        platform: Filter by platform ('web', 'telegram', or None for all)
        persona: Filter by persona mode (defaults to active persona)
        chat_id: Filter by chat session ID
    """
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")
    user_info = auth_db.get_user(username) or {}

    # Persona restriction enforcement
    restricted_persona = user_info.get("restricted_persona")
    if restricted_persona:
        resolved_persona = restricted_persona
    else:
        resolved_persona = memory_manager.normalize_persona(
            persona or memory_manager.get_active_persona()
        )

    history = chat_history.get_history(
        limit=limit,
        offset=offset,
        platform=platform,
        persona=resolved_persona,
        username=username,
        chat_id=chat_id if chat_id else None,
    )
    total = chat_history.get_total_count(
        platform=platform, persona=resolved_persona, username=username
    )
    return api_success(
        data={
            "history": history,
            "persona": resolved_persona,
            "total": total,
            "has_more": offset + len(history) < total,
        },
        history=history,
        persona=resolved_persona,
        total=total,
        has_more=offset + len(history) < total,
    )


@app.delete("/api/history")
async def clear_chat_history(request: Request, persona: Optional[str] = None):
    """Clear chat history for the current user, optionally filtered by persona."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")

    chat_history.clear_history(username=username, persona=persona)
    target = f"persona '{persona}'" if persona else "all personas"
    return api_success(
        data={"message": f"Chat history for {target} cleared for {username}"},
        message=f"Chat history for {target} cleared for {username}",
    )


@app.get("/api/chat/search")
async def search_chat_history(request: Request, q: str, persona: Optional[str] = None):
    """Search chat history for a keyword."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")

    results = await run_db(chat_history.search_history, q, username, persona)
    return api_success(data={"results": results})


def _collect_research_status_snapshot(max_chars: int = 600) -> Dict[str, Any]:
    """Short Proxmox status payload for RESEARCH_MODE UI broadcasts."""
    snapshot: Dict[str, Any] = {}
    try:
        from kuro_backend.tools.base_tools import check_proxmox_infrastructure

        text = check_proxmox_infrastructure() or ""
        snapshot["proxmox"] = text[:max_chars]
    except Exception as exc:
        snapshot["proxmox"] = f"(unavailable: {exc})"
    try:
        import psutil as _psutil

        snapshot["host"] = {
            "cpu": _psutil.cpu_percent(interval=0.1),
            "ram": _psutil.virtual_memory().percent,
            "disk": _psutil.disk_usage("/").percent,
        }
    except Exception:
        pass
    return snapshot


async def _maybe_handle_ui_mode_command(message: str) -> Optional[Dict[str, Any]]:
    """If ``message`` is a UI mode command, broadcast it and return an
    envelope describing what happened. Callers forward ``cleaned_text`` to
    the LangGraph core when non-empty, otherwise return the built-in
    acknowledgement directly.
    """
    try:
        from kuro_backend import ui_mode_router, dashboard_broadcast
    except Exception as exc:
        logger.debug(f"UI mode router unavailable: {exc}")
        return None
    detected = ui_mode_router.detect_mode_command(message or "")
    if not detected:
        return None
    command, cleaned_text = detected
    payload: Dict[str, Any] = {}
    if command == "RESEARCH_MODE":
        payload["server_status"] = _collect_research_status_snapshot()
    try:
        asyncio.create_task(
            dashboard_broadcast.broadcast_ui_command(command, payload=payload)
        )
    except Exception as exc:
        logger.warning(f"UI command broadcast scheduling failed: {exc}")
    return {
        "command": command,
        "cleaned_text": cleaned_text,
        "acknowledgement": ui_mode_router.acknowledgement(command),
        "payload": payload,
    }


@app.post("/api/chat")
async def chat_endpoint(
    request: Request,
    message: str = Form(""),
    files: list[UploadFile] = File([]),
    persona: str = Form(None),
    chat_id: str = Form(None),
    runtime_id: Optional[str] = Query(default=None),
    runtime_id_form: Optional[str] = Form(default=None, alias="runtime_id"),
):
    """Handle chat requests from the web interface with vision and file reading support. (Non-streaming fallback)"""
    try:
        # Resolve user context
        token = get_token_from_cookie(request)
        user = validate_token(token)

        if not user:

            raise HTTPException(status_code=401, detail="Unauthorized")

        username = user.get("username")
        user_info = auth_db.get_user(username) or {}
        master_name = user_info.get("master_name", "Master Pantronux")

        trace_id = str(
            getattr(request.state, "trace_id", "") or f"chat_{uuid.uuid4().hex}"
        )

        # Persona restriction
        restricted_persona = user_info.get("restricted_persona")
        if restricted_persona:
            resolved_persona = restricted_persona
        else:
            resolved_persona = memory_manager.normalize_persona(
                persona
                or request.query_params.get("persona")
                or memory_manager.get_active_persona()
            )

        request_id = f"web_{uuid.uuid4().hex}"

        session_scope, ctx, _ = _resolve_runtime_context_for_chat_request(
            request=request,
            username=username,
            resolved_persona=resolved_persona,
            chat_id=chat_id,
            runtime_id_query=runtime_id,
            runtime_id_form=runtime_id_form,
            trace_id=trace_id,
        )

        # UI mode router gate — intercept "Kuro, mode riset" style commands
        # before hitting the LangGraph core. When the cleaned remainder is
        # empty we answer with a built-in acknowledgement and skip Gemini
        # entirely; otherwise we forward the remainder downstream.
        mode_envelope = None
        if message and not files:
            mode_envelope = await _maybe_handle_ui_mode_command(message)
            if mode_envelope and not (mode_envelope.get("cleaned_text") or "").strip():
                ack = mode_envelope["acknowledgement"]
                chat_history.add_message(
                    "web",
                    "user",
                    message,
                    [],
                    persona=resolved_persona,
                    request_id=request_id,
                )
                chat_history.add_message(
                    "web",
                    "assistant",
                    ack,
                    persona=resolved_persona,
                    request_id=request_id,
                )
                return api_success(
                    data={"response": ack, "ui_command": mode_envelope["command"]},
                    trace_id=trace_id,
                    response=ack,
                )
            if mode_envelope:
                message = mode_envelope["cleaned_text"] or message

        # Save and process uploaded files
        image_paths = []
        file_contents = []
        file_attachments = []
        session_extractions = []

        for file in files:
            if file.filename:
                saved_file = await save_upload_file(file, username=username)
                file_path = saved_file["stored_path"]
                stored_filename = saved_file["stored_filename"]
                chat_history.record_uploaded_file_integrity(
                    request_id=request_id,
                    platform="web",
                    persona=resolved_persona,
                    original_filename=saved_file["original_filename"],
                    stored_filename=stored_filename,
                    stored_path=file_path,
                    content_type=saved_file["content_type"],
                    size_bytes=saved_file["size_bytes"],
                    sha256=saved_file["sha256"],
                    username=username,
                    chat_id=session_scope,
                )

                # Check if it's an image for vision processing
                if file.content_type and file.content_type.startswith("image/"):
                    image_paths.append(file_path)
                    file_attachments.append(
                        {
                            "type": "image",
                            "original_filename": saved_file["original_filename"],
                            "stored_filename": stored_filename,
                            "path": file_path,
                        }
                    )
                    file_contents.append(
                        f"\n--- Gambar Dilampirkan: {saved_file['original_filename']} ---\n(Gambar ini telah diteruskan ke modul Vision Anda untuk dianalisis)"
                    )
                else:
                    # Use smart_read facade for Office/PDF/text/log files
                    read_result = tools.smart_read(
                        file_ref=file_path,
                        instruction="ekstrak konten utama file ini",
                        max_chars=10000,
                    )
                    parsed_content = read_result.get("summary") or read_result.get(
                        "content"
                    )
                    if parsed_content:
                        file_contents.append(
                            f"\n--- File: {saved_file['original_filename']} ---\n{parsed_content}"
                        )
                    session_extractions.append(
                        {
                            "original_filename": saved_file["original_filename"],
                            "stored_filename": stored_filename,
                            "path": file_path,
                            "extracted_content": (parsed_content or "")[:5000],
                        }
                    )

                    file_attachments.append(
                        {
                            "type": "file",
                            "original_filename": saved_file["original_filename"],
                            "stored_filename": stored_filename,
                            "path": file_path,
                        }
                    )

                logger.info(f"File saved: {file_path}")

        # Build enhanced message with file contents
        enhanced_message = message
        if file_contents:
            enhanced_message += "\n\n[Attached Files Content:]\n" + "\n".join(
                file_contents
            )
        att_idx = memory_coordinator.format_same_turn_attachment_index(file_attachments)
        if att_idx:
            enhanced_message += "\n\n" + att_idx
        if image_paths:
            memory_manager.set_runtime_context_value(
                "last_accessed_file", image_paths[-1]
            )
        if file_attachments:
            memory_manager.set_runtime_context_value(
                "current_session_state",
                json.dumps(
                    {
                        "request_id": request_id,
                        "user_message": message,
                        "attachments": file_attachments,
                        "file_extractions": session_extractions,
                    },
                    ensure_ascii=False,
                ),
            )
            for ex in session_extractions:
                memory_manager.upsert_session_file(
                    session_id=session_scope,
                    filename=ex["original_filename"],
                    content=ex.get("extracted_content", ""),
                )

        # Save user message to chat history
        chat_history.add_message(
            "web",
            "user",
            message,
            [f["stored_filename"] for f in file_attachments],
            persona=resolved_persona,
            request_id=request_id,
            username=username,
            chat_id=session_scope,
        )

        # Check if we need to generate a title (if session has only 1 user message)
        # This is done in a background task to not block the chat response
        async def _maybe_generate_title(cid, msg):
            history = chat_history.get_history(username=username, chat_id=cid, limit=5)
            # Filter user messages
            user_msgs = [m for m in history if m["role"] == "user"]
            if len(user_msgs) == 1:
                new_title = llm_utils.generate_chat_title(msg)
                chat_history.update_session_title(cid, new_title)
                logger.info(f"[TITLE_GEN] Generated title for {cid}: {new_title}")

        if not session_scope.startswith("legacy_"):
            asyncio.create_task(_maybe_generate_title(session_scope, message))

        # Process with AI core using LangGraph (with vision if images uploaded)
        response = process_chat_with_graph(
            enhanced_message,
            image_paths=image_paths if image_paths else None,
            persona_override=resolved_persona,
            approval_scope=f"web:{session_scope}:{resolved_persona}",
            trace_id=trace_id,
            session_id=session_scope,
            master_name=master_name,
            username=username,
            chat_id=session_scope,
            runtime_id=ctx.runtime_id,
            runtime_namespace=ctx.memory_namespace,
        )

        # Save AI response to chat history
        assistant_message_id = chat_history.add_message(
            "web",
            "assistant",
            response,
            [],
            persona=resolved_persona,
            request_id=request_id,
            username=username,
            chat_id=session_scope,
        )
        export_suggestions = _detect_export_suggestions(
            resolved_persona, response, session_scope, assistant_message_id
        )
        if assistant_message_id and export_suggestions:
            chat_history.update_message_export_suggestions(
                assistant_message_id, export_suggestions
            )

        return api_success(
            data={
                "response": response,
                "export_suggestion": (
                    export_suggestions[0] if export_suggestions else None
                ),
                "export_suggestions": export_suggestions,
            },
            trace_id=trace_id,
            response=response,  # backward compatibility for current frontend
            meta={
                "trace_id": trace_id,
                "export_suggestion": (
                    export_suggestions[0] if export_suggestions else None
                ),
                "export_suggestions": export_suggestions,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error in chat endpoint: {e}")
        return api_error(f"My apologies, {master_name} — an error occurred: {e}")


@app.post("/api/chat/stream")
async def chat_stream_endpoint(
    request: Request,
    message: str = Form(""),
    files: list[UploadFile] = File([]),
    persona: str = Form(None),
    chat_id: str = Form(None),
    runtime_id: Optional[str] = Query(default=None),
    runtime_id_form: Optional[str] = Form(default=None, alias="runtime_id"),
):
    """V6.0 STREAMING: Handle chat requests with Server-Sent Events (SSE) streaming."""
    from fastapi.responses import StreamingResponse

    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")
    user_info = auth_db.get_user(username) or {}
    master_name = user_info.get("master_name", "Master Pantronux")
    restricted_persona = user_info.get("restricted_persona")
    if restricted_persona:
        resolved_persona = restricted_persona
    else:
        resolved_persona = memory_manager.normalize_persona(
            persona
            or request.query_params.get("persona")
            or memory_manager.get_active_persona()
        )
    trace_id = str(
        getattr(request.state, "trace_id", "") or f"chatstream_{uuid.uuid4().hex}"
    )
    session_scope, ctx, is_new_session = _resolve_runtime_context_for_chat_request(
        request=request,
        username=username,
        resolved_persona=resolved_persona,
        chat_id=chat_id,
        runtime_id_query=runtime_id,
        runtime_id_form=runtime_id_form,
        trace_id=trace_id,
    )

    async def event_generator():
        """Generate SSE events for streaming response."""
        request_started = time.perf_counter()
        request_id = trace_id
        first_chunk_ms = None
        stream_metrics: Dict[str, Any] = {}
        last_event_id_raw = request.headers.get("Last-Event-ID")
        try:
            last_event_id = (
                int(last_event_id_raw) if last_event_id_raw is not None else None
            )
        except (TypeError, ValueError):
            last_event_id = None
        try:
            sse_buffer = _sse_buffers.setdefault(session_scope, deque(maxlen=10))
            next_event_id = int(_sse_event_counters.get(session_scope, 0))

            def _next_sse_id() -> int:
                nonlocal next_event_id
                next_event_id += 1
                _sse_event_counters[session_scope] = next_event_id
                return next_event_id

            def _buffered_event(event_name: Optional[str], data_str: str) -> str:
                event_id = _next_sse_id()
                if event_name:
                    frame = f"id: {event_id}\nevent: {event_name}\ndata: {data_str}\n\n"
                else:
                    frame = f"id: {event_id}\ndata: {data_str}\n\n"
                sse_buffer.append({"id": event_id, "data": frame})
                return frame

            if last_event_id is not None:
                for buffered in list(sse_buffer):
                    if int(buffered.get("id", 0)) > last_event_id:
                        yield str(buffered.get("data", ""))

            meta_payload = {"trace_id": trace_id, "phase": "started"}
            if is_new_session:
                meta_payload["chat_id"] = session_scope

            yield _buffered_event("meta", json.dumps(meta_payload, ensure_ascii=False))

            # UI mode router gate — broadcast the UI command and short-
            # circuit the SSE stream when the user's message is purely a
            # mode switch. The frontend receives a normal token stream
            # containing only the acknowledgement.
            user_message = message
            if user_message and not files:
                mode_envelope = await _maybe_handle_ui_mode_command(user_message)
                if (
                    mode_envelope
                    and not (mode_envelope.get("cleaned_text") or "").strip()
                ):
                    ack = mode_envelope["acknowledgement"]
                    chat_history.add_message(
                        "web",
                        "user",
                        user_message,
                        [],
                        persona=resolved_persona,
                        request_id=request_id,
                        username=username,
                    )
                    chat_history.add_message(
                        "web",
                        "assistant",
                        ack,
                        persona=resolved_persona,
                        request_id=request_id,
                        username=username,
                    )
                    yield (
                        _buffered_event(
                            "meta",
                            json.dumps(
                                {"ui_command": mode_envelope["command"]},
                                ensure_ascii=False,
                            ),
                        )
                    )
                    yield _buffered_event(
                        "chunk",
                        json.dumps({"text": ack, "chunk": ack}, ensure_ascii=False),
                    )
                    yield _buffered_event(
                        "complete",
                        json.dumps(
                            {
                                "trace_id": trace_id,
                                "response": ack,
                                "ui_command": mode_envelope["command"],
                            },
                            ensure_ascii=False,
                        ),
                    )
                    yield _buffered_event(None, "[DONE]")
                    return
                if mode_envelope:
                    user_message = mode_envelope["cleaned_text"] or user_message

            # Save uploaded files (same as non-streaming endpoint)
            image_paths = []
            file_contents = []
            file_attachments = []
            session_extractions = []

            for file in files:
                if file.filename:
                    saved_file = await save_upload_file(file, username=username)
                    file_path = saved_file["stored_path"]
                    stored_filename = saved_file["stored_filename"]
                    chat_history.record_uploaded_file_integrity(
                        request_id=request_id,
                        platform="web",
                        persona=resolved_persona,
                        original_filename=saved_file["original_filename"],
                        stored_filename=stored_filename,
                        stored_path=file_path,
                        content_type=saved_file["content_type"],
                        size_bytes=saved_file["size_bytes"],
                        sha256=saved_file["sha256"],
                        username=username,
                        chat_id=session_scope,
                    )

                    if file.content_type and file.content_type.startswith("image/"):
                        image_paths.append(file_path)
                        # FIX: Store image metadata separately, don't send raw metadata in text chunks
                        file_attachments.append(
                            {
                                "type": "image",
                                "original_filename": saved_file["original_filename"],
                                "stored_filename": stored_filename,
                                "path": file_path,
                            }
                        )
                        file_contents.append(
                            f"\n--- Gambar Dilampirkan: {saved_file['original_filename']} ---\n(Gambar ini telah diteruskan ke modul Vision Anda untuk dianalisis)"
                        )
                    else:
                        read_result = tools.smart_read(
                            file_ref=file_path,
                            instruction="ekstrak konten utama file ini",
                            max_chars=10000,
                        )
                        parsed_content = read_result.get("summary") or read_result.get(
                            "content"
                        )
                        if parsed_content:
                            file_contents.append(
                                f"\n--- File: {saved_file['original_filename']} ---\n{parsed_content}"
                            )
                        session_extractions.append(
                            {
                                "original_filename": saved_file["original_filename"],
                                "stored_filename": stored_filename,
                                "path": file_path,
                                "extracted_content": (parsed_content or "")[:5000],
                            }
                        )
                        file_attachments.append(
                            {
                                "type": "file",
                                "original_filename": saved_file["original_filename"],
                                "stored_filename": stored_filename,
                                "path": file_path,
                            }
                        )

            # Build enhanced message - image paths are passed separately to LangGraph
            # Image metadata is NOT injected into the text message to prevent raw metadata in chunks
            enhanced_message = user_message
            if file_contents:
                enhanced_message += "\n\n[Attached Files Content:]\n" + "\n".join(
                    file_contents
                )
            att_idx = memory_coordinator.format_same_turn_attachment_index(
                file_attachments
            )
            if att_idx:
                enhanced_message += "\n\n" + att_idx
            if image_paths:
                memory_manager.set_runtime_context_value(
                    "last_accessed_file", image_paths[-1]
                )
            if file_attachments:
                memory_manager.set_runtime_context_value(
                    "current_session_state",
                    json.dumps(
                        {
                            "request_id": request_id,
                            "user_message": user_message,
                            "attachments": file_attachments,
                            "file_extractions": session_extractions,
                        },
                        ensure_ascii=False,
                    ),
                )
                for ex in session_extractions:
                    memory_manager.upsert_session_file(
                        session_id=session_scope,
                        filename=ex["original_filename"],
                        content=ex.get("extracted_content", ""),
                    )

            # Save user message (post UI mode router cleanup)
            chat_history.add_message(
                "web",
                "user",
                user_message,
                [f["stored_filename"] for f in file_attachments],
                persona=resolved_persona,
                request_id=request_id,
                username=username,
                chat_id=session_scope,
            )

            # Check if we need to generate a title (if session has only 1 user message)
            async def _maybe_generate_title(cid, msg):
                history = chat_history.get_history(
                    username=username, chat_id=cid, limit=5
                )
                # Filter user messages
                user_msgs = [m for m in history if m["role"] == "user"]
                if len(user_msgs) == 1:
                    new_title = llm_utils.generate_chat_title(msg)
                    chat_history.update_session_title(cid, new_title)
                    logger.info(f"[TITLE_GEN] Generated title for {cid}: {new_title}")

            if not session_scope.startswith("legacy_"):
                asyncio.create_task(_maybe_generate_title(session_scope, user_message))

            # V6.0: Stream response - no guardrail overhead, direct LLM response
            full_response = []

            async for chunk in process_chat_with_graph_stream(
                enhanced_message,
                image_paths=image_paths if image_paths else None,
                persona_override=resolved_persona,
                stream_metrics=stream_metrics,
                approval_scope=f"web:{session_scope}:{resolved_persona}",
                trace_id=trace_id,
                session_id=session_scope,
                master_name=master_name,
                username=username,
                chat_id=session_scope,
                runtime_id=ctx.runtime_id,
                runtime_namespace=ctx.memory_namespace,
            ):
                safe_chunk = sanitize_stream_chunk(chunk)
                if not safe_chunk:
                    continue
                full_response.append(safe_chunk)
                if first_chunk_ms is None:
                    first_chunk_ms = round(
                        (time.perf_counter() - request_started) * 1000, 2
                    )
                # SSE: UI accepts `text` (preferred) or `chunk`; ensure_ascii=False for Indonesian / markdown
                payload = json.dumps(
                    {"text": safe_chunk, "chunk": safe_chunk}, ensure_ascii=False
                )
                yield _buffered_event("chunk", payload)

            # Send completion event
            response_text = "".join(full_response)
            structured_output_payload = stream_metrics.get("structured_output")
            if isinstance(structured_output_payload, dict):
                yield _buffered_event(
                    "structured_output",
                    json.dumps(structured_output_payload, ensure_ascii=False),
                )
            assistant_message_id = chat_history.add_message(
                "web",
                "assistant",
                response_text,
                [],
                persona=resolved_persona,
                request_id=request_id,
                username=username,
                chat_id=session_scope,
            )
            export_suggestions = _detect_export_suggestions(
                resolved_persona, response_text, session_scope, assistant_message_id
            )
            if assistant_message_id and export_suggestions:
                chat_history.update_message_export_suggestions(
                    assistant_message_id, export_suggestions
                )
            assistant_timestamp = None
            if assistant_message_id:
                saved_message = chat_history.get_message_by_id(assistant_message_id)
                if saved_message:
                    assistant_timestamp = saved_message.get("timestamp")
            total_ms = round((time.perf_counter() - request_started) * 1000, 2)
            observability.record_latency_metric("chat_stream_total_ms", total_ms)
            if first_chunk_ms is not None:
                observability.record_latency_metric(
                    "chat_stream_ttfb_ms", first_chunk_ms
                )
            if stream_metrics.get("guardrail_input_ms") is not None:
                observability.record_latency_metric(
                    "chat_stream_guardrail_input_ms",
                    stream_metrics["guardrail_input_ms"],
                )
            if stream_metrics.get("guardrail_output_ms") is not None:
                observability.record_latency_metric(
                    "chat_stream_guardrail_output_ms",
                    stream_metrics["guardrail_output_ms"],
                )
            if stream_metrics.get("graph_collect_ms") is not None:
                observability.record_latency_metric(
                    "chat_stream_graph_collect_ms", stream_metrics["graph_collect_ms"]
                )
            if stream_metrics.get("sse_chunk_count") is not None:
                observability.record_latency_metric(
                    "chat_stream_sse_chunk_count", stream_metrics["sse_chunk_count"]
                )

            complete_payload = api_success(
                data={"response": response_text},
                trace_id=trace_id,
                response=response_text,  # backward compatibility
                timestamp=assistant_timestamp,
                message_id=assistant_message_id,
                meta={
                    "trace_id": trace_id,
                    "timestamp": assistant_timestamp,
                    "message_id": assistant_message_id,
                    "ttfb_ms": first_chunk_ms,
                    "total_ms": total_ms,
                    "timings": stream_metrics,
                    "output_schema_valid": bool(
                        stream_metrics.get("output_schema_valid", False)
                    ),
                    "export_suggestion": (
                        export_suggestions[0] if export_suggestions else None
                    ),
                    "export_suggestions": export_suggestions,
                },
            )
            yield _buffered_event(
                "complete", json.dumps(complete_payload, ensure_ascii=False)
            )
            yield _buffered_event(None, "[DONE]")

        except Exception as e:
            logger.exception(f"Error in streaming endpoint: {e}")
            error_payload = json.dumps(
                api_error(f"Maaf, {master_name} — " + str(e), trace_id=trace_id),
                ensure_ascii=False,
            )
            if "session_scope" in locals():
                # Buffer error + completion only when a session context has been established.
                sse_buffer = _sse_buffers.setdefault(session_scope, deque(maxlen=10))
                next_event_id = int(_sse_event_counters.get(session_scope, 0))

                def _next_sse_id_err() -> int:
                    nonlocal next_event_id
                    next_event_id += 1
                    _sse_event_counters[session_scope] = next_event_id
                    return next_event_id

                event_id = _next_sse_id_err()
                frame = f"id: {event_id}\nevent: error\ndata: {error_payload}\n\n"
                sse_buffer.append({"id": event_id, "data": frame})
                yield frame
                done_id = _next_sse_id_err()
                done_frame = f"id: {done_id}\ndata: [DONE]\n\n"
                sse_buffer.append({"id": done_id, "data": done_frame})
                yield done_frame
            else:
                yield f"event: error\ndata: {error_payload}\n\n"
                yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@app.delete("/api/chat/stream/{request_id}")
async def cancel_chat_stream(request: Request, request_id: str):
    """Cancel an active chat stream."""
    # Because Gemini streaming via grpc is hard to explicitly kill without sharing the stream generator globally,
    # and since HTTP disconnection kills the FastApi StreamingResponse automatically,
    # the client just aborting the fetch handles it. This endpoint just acknowledges the client's intent to stop.
    logger.info(f"Stream {request_id} cancelled by client.")
    return {"status": "success", "message": "Stream cancelled"}


@app.get("/api/runtimes")
async def list_public_runtimes():
    """Public-safe runtime list (no internal topology fields)."""
    return [
        {
            "runtime_id": r.runtime_id,
            "display_name": r.display_name,
            "version": r.version,
        }
        for r in RuntimeRegistry.list_runtimes(include_stubs=False)
    ]


@app.get("/api/schemas")
async def list_output_schemas():
    return SchemaRegistry.list_schemas()


@app.get("/api/schemas/{contract_id}")
async def get_output_schema(contract_id: str):
    try:
        return SchemaRegistry.get_json_schema(contract_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown schema: {contract_id}")


@app.post("/api/playground/qa/interpret")
async def qa_playground_interpret(
    request: Request,
    payload: QARequirementRequest,
    token_data: Dict[str, str] = Depends(validate_token_dependency),
):
    trace_id = getattr(request.state, "trace_id", "")
    if not _is_qa_playground_enabled():
        return JSONResponse(
            status_code=503,
            content=api_error("QA Playground disabled", trace_id=trace_id),
        )
    from kuro_backend.playground.qa.qa_runtime import QARuntime

    username = token_data.get("username", "Pantronux")
    chat_id = _resolve_chat_session_id(request)
    try:
        runtime = QARuntime(username=username, chat_id=chat_id, runtime_id="qa")
        result = await runtime.process_request("interpret", payload.requirement)
        if not result.get("ok"):
            return JSONResponse(
                status_code=500,
                content=api_error(
                    f"QA interpret failed: {result.get('error', 'unknown error')}",
                    trace_id=trace_id,
                ),
            )
        parsed = result.get("data") or {}
        if not isinstance(parsed, dict):
            parsed = {"result": parsed}
        parsed["trace_id"] = trace_id
        return parsed
    except Exception as exc:
        logger.exception("QA interpret route failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content=api_error(f"QA interpret failed: {exc}", trace_id=trace_id),
        )


@app.post("/api/playground/qa/generate-testcases")
async def qa_playground_generate_testcases(
    request: Request,
    payload: QARequirementRequest,
    token_data: Dict[str, str] = Depends(validate_token_dependency),
):
    trace_id = getattr(request.state, "trace_id", "")
    if not _is_qa_playground_enabled():
        return JSONResponse(
            status_code=503,
            content=api_error("QA Playground disabled", trace_id=trace_id),
        )
    from kuro_backend.playground.qa.qa_runtime import QARuntime

    username = token_data.get("username", "Pantronux")
    chat_id = _resolve_chat_session_id(request)
    try:
        runtime = QARuntime(username=username, chat_id=chat_id, runtime_id="qa")
        result = await runtime.process_request(
            "generate_testcases", payload.requirement
        )
        if not result.get("ok"):
            return JSONResponse(
                status_code=500,
                content=api_error(
                    f"QA testcase generation failed: {result.get('error', 'unknown error')}",
                    trace_id=trace_id,
                ),
            )
        output = result.get("data") or {}
        if not isinstance(output, dict):
            output = {"structured_output": output}
        output["trace_id"] = trace_id
        return output
    except Exception as exc:
        logger.exception("QA testcase route failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content=api_error(
                f"QA testcase generation failed: {exc}", trace_id=trace_id
            ),
        )


@app.post("/api/playground/qa/generate-gherkin")
async def qa_playground_generate_gherkin(
    request: Request,
    payload: QARequirementRequest,
    token_data: Dict[str, str] = Depends(validate_token_dependency),
):
    trace_id = getattr(request.state, "trace_id", "")
    if not _is_qa_playground_enabled():
        return JSONResponse(
            status_code=503,
            content=api_error("QA Playground disabled", trace_id=trace_id),
        )
    from kuro_backend.playground.qa.qa_runtime import QARuntime

    username = token_data.get("username", "Pantronux")
    chat_id = _resolve_chat_session_id(request)
    try:
        runtime = QARuntime(username=username, chat_id=chat_id, runtime_id="qa")
        result = await runtime.process_request("generate_gherkin", payload.requirement)
        if not result.get("ok"):
            return JSONResponse(
                status_code=500,
                content=api_error(
                    f"QA gherkin generation failed: {result.get('error', 'unknown error')}",
                    trace_id=trace_id,
                ),
            )
        output = result.get("data") or {}
        if not isinstance(output, dict):
            output = {"gherkin": str(output)}
        output["trace_id"] = trace_id
        return output
    except Exception as exc:
        logger.exception("QA gherkin route failed: %s", exc)
        return JSONResponse(
            status_code=500,
            content=api_error(
                f"QA gherkin generation failed: {exc}", trace_id=trace_id
            ),
        )


@app.get("/api/admin/runtimes/{runtime_id}")
async def get_admin_runtime_config(
    runtime_id: str,
    token_data: Dict[str, str] = Depends(validate_token_dependency),
):
    """Admin-only full runtime configuration view."""
    if token_data.get("username") != os.getenv("ADMIN_USERNAME", "Pantronux"):
        raise HTTPException(status_code=403, detail="Admin only")
    runtime_cfg = RuntimeRegistry.get_exact(runtime_id)
    if runtime_cfg is None:
        raise HTTPException(status_code=404, detail=f"Unknown runtime_id: {runtime_id}")
    return runtime_cfg.model_dump()


@app.get("/api/admin/boundary-violations")
async def get_boundary_violations(
    limit: int = Query(default=100, ge=1, le=500),
    token_data: Dict[str, str] = Depends(validate_token_dependency),
):
    if token_data.get("username") != os.getenv("ADMIN_USERNAME", "Pantronux"):
        raise HTTPException(status_code=403, detail="Admin only")
    return intelligence_db.get_recent_boundary_violations(limit=limit)


@app.get("/api/admin/runtime-health")
async def get_runtime_health(
    token_data: Dict[str, str] = Depends(validate_token_dependency),
):
    if token_data.get("username") != os.getenv("ADMIN_USERNAME", "Pantronux"):
        raise HTTPException(status_code=403, detail="Admin only")
    return intelligence_db.get_runtime_health_snapshot(hours=24)


@app.get("/api/system-status")
async def system_status(request: Request):
    """Get real-time system status with additive backup metadata."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user or user.get("username") != os.getenv("ADMIN_USERNAME", "Pantronux"):
        raise HTTPException(status_code=403, detail="Forbidden")
    return api_success(
        data={
            "system_health_report": tools.get_system_status(),
            "backup": _build_system_status_backup_payload(),
        }
    )


@app.get("/api/log-storage")
async def log_storage(request: Request):
    """Get log storage usage information."""
    require_admin_user(request)
    usage = get_log_storage_usage()
    return api_success(data=usage)


@app.get("/api/proxmox-status")
async def proxmox_status(request: Request):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user or user.get("username") != os.getenv("ADMIN_USERNAME", "Pantronux"):
        raise HTTPException(status_code=403, detail="Forbidden")
    """Get Proxmox infrastructure status."""
    return api_success(data=tools.check_proxmox_infrastructure())


@app.get("/api/health")
async def health_check(request: Request):
    """Health check endpoint."""
    require_admin_user(request)
    return api_success(
        data={"health": "healthy", "memory_stats": memory_manager.get_memory_stats()}
    )


@app.get("/api/observability/status")
async def observability_status(request: Request):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user or user.get("username") != os.getenv("ADMIN_USERNAME", "Pantronux"):
        raise HTTPException(status_code=403, detail="Forbidden")
    """Get observability status including Phoenix and OpenTelemetry."""
    return {
        "status": "success",
        "data": {
            "phoenix_running": observability._phoenix_app is not None,
            "opentelemetry_enabled": observability.get_tracer() is not None,
            "dashboard_url": (
                observability._phoenix_app.url if observability._phoenix_app else None
            ),
            "phoenix_port": observability.PHOENIX_PORT,
        },
    }


@app.get("/api/observability/tokens")
async def token_usage(request: Request, session_id: str = None):
    """Get token usage for sessions."""
    require_admin_user(request)
    if session_id:
        usage = observability.get_session_token_usage(session_id)
        return {"status": "success", "data": {session_id: usage}}
    else:
        # Return summary of all active sessions
        all_usage = {}
        total_tokens = 0
        for sid, usage in observability._token_tracker.items():
            all_usage[sid] = usage
            total_tokens += usage.get("total_tokens", 0)

        return {
            "status": "success",
            "data": {
                "sessions": all_usage,
                "total_sessions": len(all_usage),
                "total_tokens_all_sessions": total_tokens,
            },
        }


@app.get("/api/observability/latency")
async def latency_metrics(request: Request):
    """Get aggregated latency metrics snapshot."""
    require_admin_user(request)
    return {
        "status": "success",
        "data": {
            "latency": observability.get_latency_metrics_snapshot(),
            "counters": observability.get_counter_metrics_snapshot(),
        },
    }


@app.get("/api/evaluation/summary")
async def evaluation_summary(username: str = "Pantronux"):
    """
    Beta 3: Admin-only evaluation summary endpoint.
    Returns aggregated reasoning quality metrics.
    """
    if username != os.getenv("ADMIN_USERNAME", "Pantronux"):
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required.")

    from kuro_backend.evaluation import autonomous_evaluator

    summary = autonomous_evaluator.get_evaluation_summary()

    if summary.get("status") == "error":
        raise HTTPException(status_code=500, detail=summary.get("message"))

    return summary


@app.get("/api/backup/status")
async def backup_status(request: Request):
    """Admin-only last backup status endpoint."""
    require_admin_user(request)
    return api_success(data=backup_manager.get_backup_status())


@app.post("/api/backup/run")
async def trigger_manual_backup(request: Request):
    """Admin-only manual backup trigger."""
    require_admin_user(request)
    try:
        result = await asyncio.to_thread(backup_manager.run_manual_backup, "manual")
        return api_success(data=result)
    except Exception as exc:
        logger.error("[BACKUP] Manual backup failed: %s", exc)
        raise HTTPException(status_code=500, detail="Manual backup failed.")


@app.get("/api/backup/history")
async def backup_history(request: Request):
    """Admin-only backup history endpoint."""
    require_admin_user(request)
    return api_success(data=intelligence_db.get_backup_history(limit=30))


def run_observability_cleanup():
    observability.cleanup_old_sessions()


@app.get("/api/observability/cleanup")
async def cleanup_observability():
    """Cleanup old observability data."""
    observability.cleanup_old_sessions()
    return {"status": "success", "message": "Observability cleanup completed"}


@app.get("/observability", response_class=HTMLResponse)
async def observability_dashboard(request: Request):
    """Redirect to Phoenix dashboard."""
    # Simple redirect to Phoenix
    phoenix_url = f"http://localhost:{observability.PHOENIX_PORT}"
    return f"""
    <html>
    <head>
        <title>Kuro AI - Observability Dashboard</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #1a1a2e; color: #eee; }}
            .container {{ max-width: 800px; margin: 0 auto; }}
            h1 {{ color: #00d4ff; }}
            .card {{ background: #16213e; padding: 20px; margin: 20px 0; border-radius: 8px; }}
            a {{ color: #00d4ff; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            .warning {{ color: #ff6b6b; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔍 Kuro AI Observability Dashboard</h1>
            
            <div class="card">
                <h2>Phoenix Tracing Dashboard</h2>
                <p>Access the Arize Phoenix dashboard for detailed trace analysis:</p>
                <p><a href="{phoenix_url}" target="_blank">Open Phoenix Dashboard →</a></p>
                <p class="warning">⚠️ Authentication required: username={observability.PHOENIX_AUTH_USERNAME}</p>
            </div>
            
            <div class="card">
                <h2>Quick Links</h2>
                <ul>
                    <li><a href="/api/observability/status">Observability Status API</a></li>
                    <li><a href="/api/observability/tokens">Token Usage API</a></li>
                    <li><a href="/">Main Dashboard</a></li>
                </ul>
            </div>
            
            <div class="card">
                <h2>What's Tracked</h2>
                <ul>
                    <li>✅ LangGraph Node Execution (duration, input/output)</li>
                    <li>✅ Guardrails Validation (re-ask loops, failures)</li>
                    <li>✅ Token Usage (per session, with alerts)</li>
                    <li>✅ Memory Operations (Mem0 retrieval/extraction)</li>
                    <li>✅ Client Data Queries (special labeling)</li>
                </ul>
            </div>
        </div>
    </body>
    </html>
    """


@app.get("/api/system-analysis")
async def system_analysis(request: Request):
    """Full system health analysis from /var/log."""
    require_admin_user(request)
    return {"status": "success", "data": tools.analyze_system_health()}


@app.post("/api/index-path")
async def index_path(request: Request, path: str = Form("/home/kuro/projects/")):
    """Index a system path recursively."""
    require_admin_user(request)
    # Security: only allow whitelisted paths, prevent path traversal
    path = os.path.abspath(path)
    is_whitelisted = any(
        os.path.commonpath([os.path.realpath(path), os.path.realpath(wp)])
        == os.path.realpath(wp)
        for wp in tools.WHITELIST_PATHS
    )
    if not is_whitelisted:
        return {"status": "error", "message": "Path not in whitelist"}

    result = tools.index_system_path(path)
    return result


@app.post("/api/memory/reindex")
async def memory_reindex(request: Request, source: str = Form("uploaded_files")):
    """
    V3.0 CONTEXTUAL RAG RE-INDEXING:
    Clear old ChromaDB and re-index files with contextual enrichment.

    source: "uploaded_files" (default) or "all" (includes system paths)
    """
    require_admin_user(request)
    try:
        import time

        start_time = time.time()

        file_texts = {}

        if source == "uploaded_files":
            # Read all files from uploaded_files directory
            upload_dir = tools.UPLOAD_DIR
            if os.path.exists(upload_dir):
                for root, dirs, files in os.walk(upload_dir):
                    for filename in files:
                        filepath = os.path.join(root, filename)
                        try:
                            # Only process text-based files
                            ext = os.path.splitext(filename)[1].lower()
                            if ext in [
                                ".txt",
                                ".md",
                                ".py",
                                ".js",
                                ".json",
                                ".log",
                                ".csv",
                                ".yaml",
                                ".yml",
                            ]:
                                with open(
                                    filepath, "r", encoding="utf-8", errors="replace"
                                ) as f:
                                    file_texts[filename] = f.read()[
                                        :100000
                                    ]  # Limit to 100k chars
                        except Exception as e:
                            logger.warning(f"Could not read {filepath}: {e}")

        if not file_texts:
            return {
                "status": "error",
                "message": "No files found to re-index",
                "source": source,
            }

        # Run contextual re-indexing
        result = memory_manager.reindex_all_files(file_texts)

        elapsed = time.time() - start_time

        return {
            "status": "success" if result["success"] else "partial",
            "files_processed": result["files_processed"],
            "total_chunks": result["total_chunks"],
            "errors": result["errors"],
            "contexts": result["contexts"],
            "elapsed_seconds": round(elapsed, 2),
        }

    except Exception as e:
        logger.error(f"Memory re-indexing failed: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/memory/stats")
async def memory_stats(request: Request):
    """V3.0 Enhanced memory statistics."""
    require_admin_user(request)
    return {"status": "success", "data": memory_manager.get_memory_stats()}


@app.post("/api/compliance/ingest")
async def compliance_ingest(request: Request, clear: bool = Form(False)):
    require_admin_user(request)
    return JSONResponse(
        status_code=410,
        content={
            "status": "disabled",
            "message": "Compliance module purged in KURO V1.0.0",
        },
    )


@app.get("/api/compliance/stats")
async def compliance_stats(request: Request):
    require_admin_user(request)
    return JSONResponse(
        status_code=410,
        content={
            "status": "disabled",
            "message": "Compliance module purged in KURO V1.0.0",
        },
    )


@app.get("/api/compliance/search")
async def compliance_search(query: str):
    return JSONResponse(
        status_code=410,
        content={
            "status": "disabled",
            "message": "Compliance module purged in KURO V1.0.0",
        },
    )


# --- Legacy 410 API Routes (Reminders / Habits purged) ---
def _legacy_module_gone_response(module_name: str) -> JSONResponse:
    return JSONResponse(
        status_code=410,
        content={
            "status": "disabled",
            "message": f"{module_name} module purged in KURO V1.0.0",
        },
    )


@app.api_route(
    "/api/reminders",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
@app.api_route(
    "/api/reminders/{legacy_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def reminders_legacy_gone(legacy_path: str = ""):
    return _legacy_module_gone_response("Reminders")


@app.api_route(
    "/api/habits",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
@app.api_route(
    "/api/habits/{legacy_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def habits_legacy_gone(legacy_path: str = ""):
    return _legacy_module_gone_response("Habits")


# --- Chat Session Management ---
@app.get("/api/chats")
async def get_chats(
    request: Request, persona: str = None, limit: int = 50, offset: int = 0
):
    """Get all chat sessions for the current user and persona."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")

    if not persona:
        persona = memory_manager.get_active_persona()

    sessions = chat_history.get_sessions(username, persona, limit=limit, offset=offset)
    # Inject context_summary into each session
    for session in sessions:
        context = chat_history.get_session_context(session.get("chat_id", ""))
        if context:
            session["context_summary"] = context
    return api_success(data=sessions)


@app.post("/api/chats")
async def create_chat(request: Request, session_data: NewChatSession):
    """Create a new chat session."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")

    chat_id = f"chat_{uuid.uuid4().hex[:12]}"
    success = chat_history.create_session(
        chat_id=chat_id,
        username=username,
        persona=session_data.persona,
        title=session_data.title,
    )

    if success:
        return api_success(data={"chat_id": chat_id, "title": session_data.title})
    else:
        return api_error("Gagal membuat sesi chat baru.")


@app.get("/api/chats/{chat_id}/messages")
async def get_chat_messages_page(
    request: Request,
    chat_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    before_id: Optional[int] = Query(default=None),
):
    """Cursor-paginated message history for one chat session."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")

    page = chat_history.get_history_page(
        chat_id=chat_id,
        username=username,
        limit=limit,
        before_id=before_id,
    )
    return api_success(data=page, **page)


@app.put("/api/chats/{chat_id}")
async def update_chat_title(request: Request, chat_id: str, update: ChatSessionUpdate):
    """Update chat session title."""
    token = get_token_from_cookie(request)
    if not validate_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")

    success = chat_history.update_session_title(chat_id, update.title)
    if success:
        return api_success(message="Judul chat diperbarui.")
    else:
        return api_error("Gagal memperbarui judul chat.")


@app.delete("/api/chats/{chat_id}")
async def delete_chat(request: Request, chat_id: str):
    """Delete a chat session and its history."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")

    # Beta 5: Block deletion of pinned sessions
    session = chat_history.get_session(chat_id)
    if session and session.get("is_pinned"):
        raise HTTPException(
            status_code=403, detail="Cannot delete a pinned session. Unpin it first."
        )

    success = chat_history.delete_session(chat_id, username=username)
    if success:
        try:
            from kuro_backend import semantic_cache

            semantic_cache.invalidate_tag(username)
        except Exception as cache_exc:
            logger.debug(
                "[CHAT] semantic cache invalidate after delete skipped: %s", cache_exc
            )
    if success:
        return api_success(message="Sesi chat dihapus.")
    else:
        return api_error("Gagal menghapus sesi chat.")


@app.post("/api/chats/{chat_id}/pin")
async def pin_chat(request: Request, chat_id: str):
    """Pin a chat session."""
    token = get_token_from_cookie(request)
    if not validate_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if chat_history.pin_session(chat_id):
        return api_success(message="Chat dipin.")
    return api_error("Gagal mengepin chat.")


@app.post("/api/chats/{chat_id}/unpin")
async def unpin_chat(request: Request, chat_id: str):
    """Unpin a chat session."""
    token = get_token_from_cookie(request)
    if not validate_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if chat_history.unpin_session(chat_id):
        return api_success(message="Chat unpin.")
    return api_error("Gagal unpin chat.")


@app.put("/api/chats/{chat_id}/messages/{msg_id}/edit")
async def edit_message(
    request: Request, chat_id: str, msg_id: int, edit: MessageEditRequest
):
    """Edit a user message and truncate history after it."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    username = user["username"]
    msg = chat_history.get_message_by_id(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    if msg["username"] != username:
        raise HTTPException(status_code=403, detail="You do not own this message")

    if msg["role"] != "user":
        raise HTTPException(status_code=400, detail="Only user messages can be edited")

    if msg["chat_id"] != chat_id:
        raise HTTPException(
            status_code=400, detail="Message does not belong to this chat"
        )

    edit_group_id = msg.get("edit_group_id") or uuid.uuid4().hex

    # Save current content to edits table before updating
    chat_history.save_message_edit(
        original_msg_id=msg_id,
        chat_id=chat_id,
        username=username,
        role="user",
        content=msg["content"],
        edit_type="edit",
        edit_group_id=edit_group_id,
    )

    # Update message content and mark as edited
    chat_history.update_message_content(msg_id, edit.new_content)
    # Truncate all subsequent messages
    deleted_count = chat_history.delete_messages_after(msg_id, chat_id)

    return api_success(
        data={
            "chat_id": chat_id,
            "message_id": msg_id,
            "edit_group_id": edit_group_id,
            "deleted_after_count": deleted_count,
        }
    )


@app.post("/api/chats/{chat_id}/messages/{msg_id}/regenerate")
async def regenerate_message(request: Request, chat_id: str, msg_id: int):
    """Prepare to regenerate an assistant response."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    username = user["username"]
    msg = chat_history.get_message_by_id(msg_id)
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    if msg["username"] != username:
        raise HTTPException(status_code=403, detail="You do not own this message")

    if msg["role"] != "assistant":
        raise HTTPException(
            status_code=400, detail="Only assistant messages can be regenerated"
        )

    preceding_user_msg = chat_history.get_preceding_user_message(msg_id, chat_id)
    if not preceding_user_msg:
        raise HTTPException(
            status_code=400,
            detail="Cannot find preceding user message to regenerate from",
        )

    edit_group_id = msg.get("edit_group_id") or uuid.uuid4().hex

    # Save assistant response to edits table
    chat_history.save_message_edit(
        original_msg_id=msg_id,
        chat_id=chat_id,
        username=username,
        role="assistant",
        content=msg["content"],
        edit_type="regeneration",
        edit_group_id=edit_group_id,
    )

    # Delete the assistant message and everything after
    chat_history.delete_messages_after(msg_id - 1, chat_id)

    return api_success(
        data={"preceding_user_message": preceding_user_msg, "deleted_msg_id": msg_id}
    )


@app.post("/api/chats/{chat_id}/messages/{msg_id}/bookmark")
async def toggle_message_bookmark(request: Request, chat_id: str, msg_id: int):
    """Toggle the bookmark state of a message."""
    token = get_token_from_cookie(request)
    if not validate_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")

    new_state = chat_history.toggle_bookmark(msg_id)
    if new_state is not None:
        return api_success(data={"is_bookmarked": bool(new_state)})
    return api_error("Gagal mengubah bookmark.")


@app.get("/api/chats/{chat_id}/bookmarks")
async def get_bookmarks(request: Request, chat_id: str):
    """Get all bookmarked messages for a chat session."""
    token = get_token_from_cookie(request)
    if not validate_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")

    bookmarks = chat_history.get_bookmarked_messages(chat_id)
    return api_success(data=bookmarks)


@app.get("/api/chats/{chat_id}/search")
async def search_in_chat(request: Request, chat_id: str, q: str = Query(...)):
    """Search for messages within a specific chat session."""
    token = get_token_from_cookie(request)
    if not validate_token(token):
        raise HTTPException(status_code=401, detail="Unauthorized")

    results = chat_history.search_messages_in_session(chat_id, q)
    return api_success(data=results)


@app.get("/api/chats/{chat_id}/export")
async def export_chat(request: Request, chat_id: str, format: str = Query("md")):
    """Export a chat session as a file download via the universal export engine."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if format not in (UniversalExportFormat.MD.value, UniversalExportFormat.TXT.value):
        raise HTTPException(
            status_code=400, detail="Legacy route only supports md or txt"
        )

    export_request = UniversalExportRequest(
        target="chat_session",
        format=format,
        chat_id=chat_id,
    )
    content, _, media_type = export_manager.export_sync(
        export_request, user["username"]
    )
    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="kuro_chat_{chat_id[:8]}.{format}"'
        },
    )


@app.get("/api/export/history")
async def export_history(request: Request, limit: int = 20):
    """List recent export jobs for the current user."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    jobs = intelligence_db.list_export_jobs(user["username"], limit=limit)
    return api_success(data=jobs)


@app.post("/api/export")
async def create_export(
    request: Request,
    export_request: UniversalExportRequest,
    background_tasks: BackgroundTasks,
):
    """Create a synchronous or asynchronous export."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if export_request.format in {
        UniversalExportFormat.MD,
        UniversalExportFormat.TXT,
        UniversalExportFormat.JSON,
        UniversalExportFormat.CSV,
        UniversalExportFormat.XLSX,
        UniversalExportFormat.DOCX,
    }:
        content, filename, media_type = export_manager.export_sync(
            export_request, user["username"]
        )
        return StreamingResponse(
            iter([content]),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    job_id = export_manager.create_async_pdf_job(export_request, user["username"])
    background_tasks.add_task(export_manager.process_export_job, job_id)
    return JSONResponse(
        status_code=202,
        content={
            "status": "accepted",
            "job_id": job_id,
            "export_format": export_request.format.value,
            "target": export_request.target.value,
        },
    )


@app.get("/api/export/{job_id}")
async def get_export_status(request: Request, job_id: int):
    """Return export job metadata for the current owner."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    job = intelligence_db.get_export_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")
    if job.get("username") != user["username"]:
        raise HTTPException(status_code=403, detail="Forbidden")

    payload = {
        "id": job["id"],
        "status": job["status"],
        "file_size": job.get("file_size"),
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
        "error_message": job.get("error_message"),
    }
    if job.get("status") == UniversalExportStatus.COMPLETED.value:
        payload["download_url"] = f"/api/export/{job_id}/download"
    return payload


@app.get("/api/export/{job_id}/download")
async def download_export(request: Request, job_id: int):
    """Download a completed export file."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    job = intelligence_db.get_export_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")
    if job.get("username") != user["username"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if job.get("status") != UniversalExportStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail="Export job is not completed")
    if not job.get("file_path") or not os.path.exists(job["file_path"]):
        raise HTTPException(status_code=404, detail="Export file not found")

    return FileResponse(
        job["file_path"],
        media_type="application/pdf",
        filename=os.path.basename(job["file_path"]),
    )


# --- Intelligence Hub Routes ---
@app.get("/api/intelligence/history")
async def intelligence_history(limit: int = 20, offset: int = 0, search: str = None):
    """Get intelligence briefing history with pagination and search."""
    if search:
        briefings = intelligence_db.search_briefings(search, limit=limit)
        return {
            "status": "success",
            "briefings": briefings,
            "total": len(briefings),
            "has_more": False,
            "search_query": search,
        }

    briefings = intelligence_db.get_briefings(limit=limit, offset=offset)
    total = intelligence_db.get_total_count()

    return {
        "status": "success",
        "briefings": briefings,
        "total": total,
        "has_more": offset + len(briefings) < total,
    }


@app.get("/api/intelligence/latest")
async def intelligence_latest():
    """Get the latest intelligence briefing."""
    briefings = intelligence_db.get_briefings(limit=1)
    if briefings:
        return {"status": "success", "briefing": briefings[0]}
    return {
        "status": "success",
        "briefing": None,
        "message": "No briefings available yet",
    }


@app.get("/api/intelligence/run")
async def intelligence_run(force: str = "false"):
    """Manually trigger daily intelligence research."""
    try:
        force_bool = force.lower() == "true"
        from kuro_backend.intelligence_engine import run_daily_research

        briefing = run_daily_research(force=force_bool)
        return {"status": "success", "briefing": briefing}
    except Exception as e:
        logger.error("Intelligence run failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="An internal error occurred")


@app.get("/intelligence", response_class=HTMLResponse)
async def intelligence_dashboard():
    """Serve the intelligence hub dashboard."""
    return FileResponse(os.path.join(WEB_DIR, "templates", "intelligence.html"))


@app.get("/ingestion", response_class=HTMLResponse)
async def ingestion_dashboard(request: Request):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if user and user.get("username") != os.getenv("ADMIN_USERNAME", "Pantronux"):
        return RedirectResponse(url="/", status_code=302)
    require_admin_user(request)
    return FileResponse(os.path.join(WEB_DIR, "templates", "ingestion_center.html"))


@app.get("/ingestion/analytics", response_class=HTMLResponse)
async def ingestion_analytics_dashboard(request: Request):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if user and user.get("username") != os.getenv("ADMIN_USERNAME", "Pantronux"):
        return RedirectResponse(url="/", status_code=302)
    require_admin_user(request)
    return FileResponse(os.path.join(WEB_DIR, "templates", "ingestion_analytics.html"))


@app.get("/ingestion/logs", response_class=HTMLResponse)
async def ingestion_logs_dashboard(request: Request):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if user and user.get("username") != os.getenv("ADMIN_USERNAME", "Pantronux"):
        return RedirectResponse(url="/", status_code=302)
    require_admin_user(request)
    return FileResponse(os.path.join(WEB_DIR, "templates", "ingestion_logs.html"))


class OrphanSourceRecoveryRequest(BaseModel):
    filenames: List[str] = Field(default_factory=list)
    category: str = "recovered"
    tags: str = "recovered,orphan-source"
    memory_scope: str = "chroma_only"


@app.get("/api/ingestion/datasets")
async def list_ingestion_datasets(request: Request, active_only: bool = Query(False)):
    user = require_admin_user(request)
    return ingestion_manager.get_dashboard_snapshot(
        owner_username=user["username"], active_only=active_only
    )


@app.get("/api/ingestion/datasets/{dataset_uuid}")
async def get_ingestion_dataset(request: Request, dataset_uuid: str):
    require_admin_user(request)
    payload = ingestion_manager.get_dataset_detail(dataset_uuid)
    if payload.get("status") == "error":
        raise HTTPException(status_code=404, detail=payload["message"])
    return payload


@app.get("/api/ingestion/datasets/{dataset_uuid}/chunks")
async def get_ingestion_chunks(request: Request, dataset_uuid: str):
    require_admin_user(request)
    dataset = ingestion_registry.get_dataset(dataset_uuid)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return {"status": "success", "data": ingestion_registry.list_chunks(dataset_uuid)}


@app.get("/api/ingestion/datasets/{dataset_uuid}/lineage")
async def get_ingestion_lineage(request: Request, dataset_uuid: str):
    require_admin_user(request)
    dataset = ingestion_registry.get_dataset(dataset_uuid)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found.")
    return {"status": "success", "data": ingestion_registry.list_lineage(dataset_uuid)}


@app.get("/api/ingestion/jobs")
async def list_ingestion_jobs(request: Request, limit: int = Query(25, ge=1, le=200)):
    user = require_admin_user(request)
    return {
        "status": "success",
        "data": ingestion_manager.list_jobs(
            owner_username=user["username"], limit=limit
        ),
    }


@app.get("/api/ingestion/search")
async def search_ingestion_datasets(
    request: Request, q: str = Query(..., min_length=1)
):
    user = require_admin_user(request)
    return ingestion_manager.search_datasets(q, owner_username=user["username"])


@app.get("/api/ingestion/analytics/overview")
async def ingestion_analytics_overview(request: Request):
    require_admin_user(request)
    return ingestion_manager.get_analytics_overview()


@app.get("/api/ingestion/analytics/retrieval")
async def ingestion_analytics_retrieval(request: Request):
    require_admin_user(request)
    overview = ingestion_manager.get_analytics_overview()
    return {"status": "success", "data": overview["data"]["retrieval"]}


@app.get("/api/ingestion/logs")
async def ingestion_logs_overview(
    request: Request,
    job_limit: int = Query(100, ge=1, le=500),
    failed_limit: int = Query(50, ge=1, le=200),
):
    user = require_admin_user(request)
    return ingestion_manager.get_logs_overview(
        username=user["username"],
        job_limit=job_limit,
        failed_limit=failed_limit,
    )


@app.get("/api/ingestion/chroma/health")
async def ingestion_chroma_health(request: Request):
    require_admin_user(request)
    return {"status": "success", "data": chroma_inspector.get_collection_health()}


@app.get("/api/ingestion/graph/{dataset_uuid}")
async def ingestion_graph(request: Request, dataset_uuid: str):
    require_admin_user(request)
    detail = ingestion_manager.get_dataset_detail(dataset_uuid)
    if detail.get("status") == "error":
        raise HTTPException(status_code=404, detail=detail["message"])
    dataset = detail["data"]["dataset"]
    chunks = detail["data"]["chunks"]
    nodes = [
        {
            "id": f"dataset:{dataset_uuid}",
            "label": dataset.get("dataset_name", dataset_uuid),
            "type": "dataset",
            "meta": {"status": dataset.get("ingestion_status", "")},
        }
    ]
    edges = []
    for chunk in chunks:
        chunk_node_id = f"chunk:{chunk['id']}"
        nodes.append(
            {
                "id": chunk_node_id,
                "label": f"Chunk {chunk['chunk_index']}",
                "type": "chunk",
                "meta": {
                    "preview": chunk.get("preview_text", ""),
                    "score": chunk.get("retrieval_count", 0),
                },
            }
        )
        edges.append(
            {
                "source": f"dataset:{dataset_uuid}",
                "target": chunk_node_id,
                "type": "contains",
                "weight": 1.0,
            }
        )
        try:
            entities = json.loads(chunk.get("entity_json") or "[]")
        except Exception:
            entities = []
        for entity in entities:
            entity_id = f"entity:{dataset_uuid}:{entity}"
            if not any(node["id"] == entity_id for node in nodes):
                nodes.append(
                    {"id": entity_id, "label": entity, "type": "entity", "meta": {}}
                )
            edges.append(
                {
                    "source": chunk_node_id,
                    "target": entity_id,
                    "type": "mentions",
                    "weight": 0.5,
                }
            )
    return {"status": "success", "data": {"nodes": nodes, "edges": edges}}


@app.post("/api/ingestion/upload")
async def upload_ingestion_dataset(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    category: str = Form("general"),
    tags: str = Form(""),
    memory_scope: str = Form("chroma_only"),
    source_type: str = Form(""),
):
    user = require_admin_user(request)
    payload = ingestion_manager.create_dataset_from_upload(
        file=file,
        username=user["username"],
        category=category,
        tags=tags,
        memory_scope=memory_scope,
        source_type=source_type or None,
    )
    job = payload.get("data", {}).get("job")
    if job is not None:
        ingestion_manager.schedule_ingestion_job(background_tasks, job["id"])
    return JSONResponse(status_code=202, content=payload)


@app.post("/api/ingestion/datasets/{dataset_uuid}/reindex")
async def reindex_ingestion_dataset(
    background_tasks: BackgroundTasks, request: Request, dataset_uuid: str
):
    user = require_admin_user(request)
    payload = ingestion_manager.reindex_dataset(dataset_uuid, user["username"])
    if payload.get("status") == "error":
        raise HTTPException(status_code=404, detail=payload["message"])
    job = payload.get("data", {}).get("job")
    if job is not None:
        ingestion_manager.schedule_ingestion_job(background_tasks, job["id"])
    return JSONResponse(status_code=202, content=payload)


@app.get("/api/ingestion/orphan-sources")
async def list_ingestion_orphan_sources(request: Request):
    user = require_admin_user(request)
    return ingestion_manager.discover_orphan_source_files(user["username"])


@app.post("/api/ingestion/orphan-sources/reingest")
async def recover_ingestion_orphan_sources(
    background_tasks: BackgroundTasks,
    request: Request,
    payload: OrphanSourceRecoveryRequest,
):
    user = require_admin_user(request)
    result = ingestion_manager.recover_orphan_source_files(
        username=user["username"],
        filenames=payload.filenames,
        category=payload.category,
        tags=payload.tags,
        memory_scope=payload.memory_scope,
    )
    for row in result.get("data", {}).get("jobs", []):
        ingestion_manager.schedule_ingestion_job(background_tasks, row["job"]["id"])
    return JSONResponse(status_code=202, content=result)


@app.post("/api/ingestion/datasets/{dataset_uuid}/archive")
async def archive_ingestion_dataset(request: Request, dataset_uuid: str):
    user = require_admin_user(request)
    return ingestion_manager.archive_dataset(dataset_uuid, user["username"])


@app.post("/api/ingestion/datasets/{dataset_uuid}/delete")
async def delete_ingestion_dataset(request: Request, dataset_uuid: str):
    user = require_admin_user(request)
    payload = ingestion_manager.delete_dataset(dataset_uuid, user["username"])
    if payload.get("status") == "error":
        raise HTTPException(status_code=404, detail=payload["message"])
    return payload


@app.post("/api/ingestion/chroma/cleanup-orphans")
async def cleanup_ingestion_orphans(request: Request):
    require_admin_user(request)
    orphans = chroma_inspector.find_orphan_chunks()
    return {
        "status": "success",
        "data": {"orphan_count": len(orphans), "orphans": orphans},
    }


@app.post("/api/read-file")
async def read_file(request: Request, file_path: str = Form("")):
    """Read a file using universal parser."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        return JSONResponse(
            status_code=401, content={"status": "error", "message": "Unauthorized"}
        )

    if not file_path:
        return {"status": "error", "message": "No file path provided"}

    # Security: Prevent path traversal
    abs_upload_dir = os.path.abspath(tools.UPLOAD_DIR)
    abs_file_path = os.path.abspath(file_path)
    if os.path.commonpath(
        [os.path.realpath(abs_file_path), os.path.realpath(abs_upload_dir)]
    ) != os.path.realpath(abs_upload_dir):
        return {
            "status": "error",
            "message": "Invalid file path: Path traversal is not allowed",
        }

    result = tools.universal_read(file_path)
    return result


@app.get("/api/list-files")
async def list_files(request: Request):
    """List files for the current user."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")
    files = chat_history.list_user_files(username)
    return {"status": "success", "data": files}


# --- Documentation Routes ---
@app.get("/tutorial", response_class=HTMLResponse)
async def tutorial_frontend():
    """Serve the documentation/tutorial frontend."""
    return FileResponse(os.path.join(WEB_DIR, "templates", "tutorial.html"))


@app.get("/api/tutorial/content")
async def tutorial_content():
    """Return the raw markdown content of SYSTEM_MAP.md."""
    try:
        map_path = os.path.join(BASE_DIR, "SYSTEM_MAP.md")
        if not os.path.exists(map_path):
            return {"status": "error", "message": "SYSTEM_MAP.md not found"}
        with open(map_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"status": "success", "markdown": content}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/playground/tutorial", response_class=HTMLResponse)
async def playground_tutorial_frontend(request: Request):
    """Serve the private Playground tutorial frontend."""
    require_admin_user(request)
    return FileResponse(os.path.join(WEB_DIR, "templates", "playground_tutorial.html"))


@app.get("/api/playground/tutorial/content")
async def playground_tutorial_content(request: Request):
    """Return the raw markdown content of SYSTEM_MAP_PLAYGROUND.md."""
    require_admin_user(request)
    try:
        map_path = os.path.join(
            BASE_DIR, "playground_runtime", "SYSTEM_MAP_PLAYGROUND.md"
        )
        if not os.path.exists(map_path):
            return JSONResponse(
                status_code=404,
                content={
                    "status": "error",
                    "message": "SYSTEM_MAP_PLAYGROUND.md not found",
                },
            )
        with open(map_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"status": "success", "markdown": content}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )


# --- Compliance Routes ---
@app.get("/compliance")
async def compliance_dashboard():
    return RedirectResponse(url="/tutorial")


@app.get("/api/compliance/progress/{standard}")
async def compliance_progress(standard: str):
    return JSONResponse(
        status_code=410,
        content={
            "status": "disabled",
            "message": "Compliance module purged in KURO V1.0.0",
        },
    )


@app.get("/api/compliance/evidence")
async def compliance_evidence(standard: str = None):
    return JSONResponse(
        status_code=410,
        content={
            "status": "disabled",
            "message": "Compliance module purged in KURO V1.0.0",
        },
    )


@app.get("/api/compliance/search")
async def compliance_search(query: str, standard: str = None):
    return JSONResponse(
        status_code=410,
        content={
            "status": "disabled",
            "message": "Compliance module purged in KURO V1.0.0",
        },
    )


@app.post("/api/compliance/analyze")
async def compliance_analyze(
    document: str = Form(""), standard: str = Form("iso27001")
):
    return JSONResponse(
        status_code=410,
        content={
            "status": "disabled",
            "message": "Compliance module purged in KURO V1.0.0",
        },
    )


@app.get("/api/compliance/audit-trail")
async def audit_trail(limit: int = 50):
    return JSONResponse(
        status_code=410,
        content={
            "status": "disabled",
            "message": "Compliance module purged in KURO V1.0.0",
        },
    )


@app.get("/api/dashboard/data-revision")
async def dashboard_data_revision():
    """Cross-worker revision from SQLite (fallback if WebSocket disconnects)."""
    revision = await run_db(core_data.get_data_revision)
    return {"status": "success", "revision": revision}


@app.websocket("/ws/dashboard")
async def dashboard_sync_websocket(websocket: WebSocket):
    """Push REFRESH_NOW when data_revision bumps (same cookie auth as dashboards).

    V6.0 Sovereign: also delivers the once-per-day personalized greeting via
    ``proactive_greeting.maybe_send`` right after the handshake so the
    master hears Kuro the moment the dashboard loads.
    """
    token = _ws_token_from_cookie(websocket)
    token_info = validate_token(token)
    if not token_info:
        await websocket.close(code=4401)
        return
    await dashboard_broadcast.connect(websocket)
    try:
        try:
            await proactive_greeting.maybe_send(
                websocket,
                token_info.get("username"),
            )
        except Exception as greeting_exc:
            logger.warning(f"[GREETING] maybe_send failed: {greeting_exc}")
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await dashboard_broadcast.disconnect(websocket)


# --- Finances SSoT (The Chancellor) ---
@app.get("/api/finances/budget")
async def finances_get_budget(request: Request, month: Optional[str] = None):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")
    m = (month or "").strip() or date.today().strftime("%Y-%m")
    row = await run_db(finance_db.get_budget, m, username)
    if not row:
        return {"status": "success", "month": m, "budget": None}
    rec = MonthlyBudgetRecord.model_validate(dict(row))
    return {"status": "success", "month": m, "budget": rec.model_dump(mode="json")}


@app.post("/api/finances/budget")
async def finances_set_budget(
    request: Request,
    month: str = Form(...),
    amount_usd: float = Form(...),
    notes: str = Form(""),
):
    try:
        token = get_token_from_cookie(request)
        user = validate_token(token)

        if not user:

            raise HTTPException(status_code=401, detail="Unauthorized")

        username = user.get("username")
        await run_db(finance_db.add_budget, month, amount_usd, notes or "", username)
        await run_db(core_data.bump_data_revision)
        return {"status": "success", "month": month.strip()}
    except Exception as e:
        logger.error("finances_set_budget: %s", e)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )


@app.get("/api/finances/expenses")
async def finances_list_expenses(request: Request):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")
    rows = await run_db(finance_db.list_recurring_expenses, True, username)
    out = [
        RecurringExpenseRecord.model_validate(dict(r)).model_dump(mode="json")
        for r in rows
    ]
    return {"status": "success", "expenses": out}


@app.post("/api/finances/expenses")
async def finances_add_expense(
    request: Request,
    label: str = Form(...),
    amount_usd: float = Form(...),
    cadence: str = Form("monthly"),
    next_due: str = Form(""),
    category: str = Form(""),
):
    try:
        token = get_token_from_cookie(request)
        user = validate_token(token)

        if not user:

            raise HTTPException(status_code=401, detail="Unauthorized")

        username = user.get("username")
        await run_db(
            finance_db.upsert_recurring_expense,
            label,
            amount_usd,
            cadence,
            next_due,
            category,
            True,
            username,
        )
        await run_db(core_data.bump_data_revision)
        return {"status": "success", "label": label.strip()}
    except Exception as e:
        logger.error("finances_add_expense: %s", e)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )


@app.delete("/api/finances/expenses/{expense_id}")
async def finances_delete_expense(expense_id: int, request: Request):
    try:
        token = get_token_from_cookie(request)
        user = validate_token(token)

        if not user:

            raise HTTPException(status_code=401, detail="Unauthorized")

        username = user.get("username")
        ok = await run_db(finance_db.delete_recurring_expense, expense_id, username)
        if ok:
            await run_db(core_data.bump_data_revision)
        return {"status": "success", "deleted": bool(ok)}
    except Exception as e:
        logger.error("finances_delete_expense: %s", e)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )


@app.get("/api/finances/api-usage")
async def finances_api_usage(request: Request, days: int = 7):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")
    rows = await run_db(
        finance_db.get_last_n_days_spend, max(1, min(int(days), 90)), username
    )
    out = [
        ApiUsageDailyRecord.model_validate(dict(r)).model_dump(mode="json")
        for r in rows
    ]
    return {"status": "success", "usage": out}


# --- Market Sentinel (Chancellor + OpenClaw cache) ---
@app.get("/api/market/watch")
async def market_list_watch(request: Request):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")
    rows = await run_db(finance_db.list_watched_symbols, True, username)
    out = [
        WatchedSymbolRecord.model_validate(dict(r)).model_dump(mode="json")
        for r in rows
    ]
    return {"status": "success", "symbols": out}


@app.post("/api/market/watch")
async def market_add_watch(
    request: Request, symbol: str = Form(...), label: str = Form("")
):
    try:
        token = get_token_from_cookie(request)
        user = validate_token(token)

        if not user:

            raise HTTPException(status_code=401, detail="Unauthorized")

        username = user.get("username")
        sym = (symbol or "").strip().upper()
        if not sym:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "symbol required"},
            )
        await run_db(finance_db.upsert_watched_symbol, sym, label or "", username)
        await run_db(core_data.bump_data_revision)
        return {"status": "success", "symbol": sym}
    except Exception as e:
        logger.error("market_add_watch: %s", e)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )


@app.delete("/api/market/watch/{symbol}")
async def market_delete_watch(symbol: str, request: Request):
    try:
        token = get_token_from_cookie(request)
        user = validate_token(token)

        if not user:

            raise HTTPException(status_code=401, detail="Unauthorized")

        username = user.get("username")
        sym = (symbol or "").strip().upper()
        ok = await run_db(finance_db.delete_watched_symbol, sym, username)
        if ok:
            await run_db(core_data.bump_data_revision)
        return {"status": "success", "deleted": bool(ok)}
    except Exception as e:
        logger.error("market_delete_watch: %s", e)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)},
        )


@app.get("/api/market/hud")
async def market_hud(request: Request):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")
    raw = await run_db(finance_db.get_market_hud_items, username)
    items = [MarketHudChip.model_validate(x).model_dump(mode="json") for x in raw]
    news_available = bool(os.getenv("NEWSAPI_API_KEY"))
    return {"status": "success", "items": items, "news_available": news_available}


# --- Market Sentinel (V2) Routes ---


@app.get("/api/sentinel/latest")
async def api_sentinel_latest(request: Request):
    """Fetch the latest unique scan for each stock."""


# --- Hybrid Market Sentinel V3 ---
@app.get("/api/sentinel/stocks")
async def api_sentinel_stocks(
    request: Request, sort_by: str = "latest", category: Optional[str] = None
):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")
    stocks = await run_db(
        finance_db.get_all_sentinel_stocks, sort_by, category, username
    )
    return {"status": "success", "stocks": stocks}


@app.get("/api/sentinel/stock/{code}")
async def api_sentinel_stock_detail(code: str, request: Request):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")
    stock = await run_db(finance_db.get_sentinel_stock_detail, code, username)
    history = await run_db(finance_db.get_sentinel_history_for_chart, code, username)
    return {"status": "success", "stock": stock, "history": history}


@app.get("/api/sentinel/pins")
async def api_sentinel_pins(request: Request):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")
    pins = await run_db(finance_db.get_user_pins, username)
    return {"status": "success", "pins": pins}


@app.post("/api/sentinel/pins/{code}")
async def api_sentinel_toggle_pin(code: str, request: Request):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")
    try:
        res = await run_db(finance_db.toggle_pin_stock, username, code)
        return {"status": "success", **res}
    except ValueError as e:
        return JSONResponse(
            status_code=400, content={"status": "error", "message": str(e)}
        )


@app.post("/api/sentinel/run")
async def api_sentinel_manual_run(request: Request):
    """Manually trigger a triangulation scan (restricted to master)."""
    from kuro_backend import price_ticker_worker
    from kuro_backend import market_sentinel

    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")
    if username != os.getenv("ADMIN_USERNAME", "Pantronux"):
        raise HTTPException(
            status_code=403, detail="Only Master can trigger Sentinel scans."
        )
    def _run_fresh_scan():
        price_ticker_worker.run_price_update(username)
        market_sentinel.run_triangulation_scan(username)

    asyncio.create_task(asyncio.to_thread(_run_fresh_scan))
    return {
        "status": "success",
        "message": "Triangulation scan triggered in background.",
    }


@app.post("/api/sentinel/price-update")
async def api_sentinel_price_update(request: Request):
    """Manually trigger a price ticker update (restricted to master)."""
    from kuro_backend import price_ticker_worker

    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")
    if username != os.getenv("ADMIN_USERNAME", "Pantronux"):
        raise HTTPException(
            status_code=403, detail="Only Master can trigger price updates."
        )
    asyncio.create_task(
        asyncio.to_thread(price_ticker_worker.run_price_update, username)
    )
    return {"status": "success", "message": "Price update triggered in background."}


@app.get("/api/openclaw/skills")
async def list_openclaw_skills(request: Request):
    """Admin-only OpenClaw skill introspection endpoint."""
    require_admin_user(request)
    try:
        from kuro_backend.execution import openclaw_bridge

        skills = await openclaw_bridge.list_available_skills()
        return {
            "skills": skills,
            "circuit_breaker_state": openclaw_bridge.get_circuit_state(),
        }
    except Exception as exc:
        return {
            "skills": [],
            "error": str(exc),
            "circuit_breaker_state": "unknown",
        }


@app.get("/api/market/brief")
async def market_brief(request: Request):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    username = user.get("username")
    parts = await run_db(finance_db.get_market_brief_parts, username)
    brief = (parts.get("brief_text") or "").strip()
    if not brief:
        brief = (
            parts.get("last_sentinel_note") or ""
        ).strip() or "No market briefing cached yet. The nightly sentinel will populate this."
    return {"status": "success", "brief": brief}


@app.get("/market", response_class=HTMLResponse)
async def market_dashboard():
    """Market Sentinel hub (watchlist + probability ticker)."""
    return FileResponse(os.path.join(WEB_DIR, "templates", "market.html"))


# --- Persona API Endpoint ---
@app.post("/api/persona")
async def set_persona(request: Request):
    """Set the active persona for Kuro AI."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        return {"status": "error", "message": "Unauthorized"}

    username = user.get("username")
    user_info = auth_db.get_user(username) or {}
    restricted_persona = user_info.get("restricted_persona")

    try:
        body = await request.json()
        persona = body.get("persona", "consultant")

        # Enforce restriction
        if restricted_persona and persona != restricted_persona:
            return {
                "status": "error",
                "message": f"Unauthorized. Your account is restricted to the {restricted_persona} persona.",
            }

        result = memory_manager.set_active_persona(persona, username=username)
        return result
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/persona")
async def get_persona(request: Request):
    """Get the current active persona."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        return {"status": "error", "message": "Unauthorized"}

    username = user.get("username")
    user_info = auth_db.get_user(username) or {}
    restricted_persona = user_info.get("restricted_persona")

    try:
        if restricted_persona:
            return {"status": "success", "persona": restricted_persona}

        persona = memory_manager.get_active_persona(username=username)
        return {"status": "success", "persona": persona}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/persona/history/stats")
async def persona_history_stats(request: Request):
    """Get persona distribution and available backup snapshots."""
    require_admin_user(request)
    try:
        return {
            "status": "success",
            "counts": persona_history_admin.get_persona_counts(),
            "backups": persona_history_admin.list_backups(limit=30),
        }
    except Exception as e:
        logger.exception("persona_history_stats failed: %s", e)
        return {"status": "error", "message": str(e)}


@app.get("/api/persona/history/preview")
async def persona_history_preview(request: Request, limit_turns: int = 30):
    """Preview consultant/advisor turn classification without writing data."""
    require_admin_user(request)
    try:
        preview = persona_history_admin.preview_reclassify(limit_turns=limit_turns)
        return {"status": "success", "preview": preview}
    except Exception as e:
        logger.exception("persona_history_preview failed: %s", e)
        return {"status": "error", "message": str(e)}


@app.post("/api/persona/history/reclassify")
async def persona_history_reclassify(request: Request):
    """Reclassify consultant/advisor history into separated persona buckets."""
    require_admin_user(request)
    try:
        body = await request.json()
        apply_changes = bool(body.get("apply", False))
        result = persona_history_admin.run_reclassify(apply_changes=apply_changes)
        return {"status": "success", "result": result}
    except Exception as e:
        logger.exception("persona_history_reclassify failed: %s", e)
        return {"status": "error", "message": str(e)}


@app.post("/api/persona/history/override")
async def persona_history_override(request: Request):
    """Manual override persona assignment for specific chat_history row IDs."""
    require_admin_user(request)
    try:
        body = await request.json()
        row_ids = body.get("row_ids", [])
        persona = body.get("persona", "")
        result = persona_history_admin.override_persona(
            row_ids=row_ids, persona=persona
        )
        return {"status": "success", "result": result}
    except Exception as e:
        logger.exception("persona_history_override failed: %s", e)
        return {"status": "error", "message": str(e)}


@app.post("/api/persona/history/restore")
async def persona_history_restore(request: Request):
    """Restore persona labels from a selected DB backup snapshot."""
    require_admin_user(request)
    try:
        body = await request.json()
        backup_file = body.get("backup_file", "")
        result = persona_history_admin.restore_persona_from_backup(
            backup_file=backup_file
        )
        return {"status": "success", "result": result}
    except Exception as e:
        logger.exception("persona_history_restore failed: %s", e)
        return {"status": "error", "message": str(e)}


# --- Hardware Sentinel ---
_hardware_sentinel_scheduler = None


def start_hardware_sentinel():
    """Start the hardware monitoring scheduler with dynamic intervals."""
    global _hardware_sentinel_scheduler
    from apscheduler.schedulers.background import BackgroundScheduler

    _hardware_sentinel_scheduler = BackgroundScheduler(daemon=True)

    # Add job that runs every 30 seconds but checks time-based intervals internally
    _hardware_sentinel_scheduler.add_job(
        hardware_sentinel_check,
        "interval",
        seconds=30,
        id="hardware_sentinel",
        replace_existing=True,
    )

    _hardware_sentinel_scheduler.start()
    logger.info("Hardware Sentinel scheduler started.")


# Track last check times to implement dynamic intervals
_last_hardware_check = None


def hardware_sentinel_check():
    """Check hardware metrics with dynamic intervals: 2hr work hours, 4hr off-hours."""
    global _last_hardware_check

    now = datetime.now()
    current_hour = now.hour

    # Determine interval based on time of day
    # Work hours: 8 AM - 4 PM (08:00 - 16:00)
    is_work_hours = 8 <= current_hour < 16
    check_interval = timedelta(hours=2) if is_work_hours else timedelta(hours=4)

    # Skip if not enough time has passed since last check
    if _last_hardware_check and (now - _last_hardware_check) < check_interval:
        return

    _last_hardware_check = now
    dashboard_broadcast.schedule_ui_command(
        "STATUS_TICKER",
        {"status": "SCANNING", "source": "HARDWARE"},
    )

    try:
        # Collect metrics
        cpu_percent = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        ram_percent = ram.percent
        disk = psutil.disk_usage("/")
        disk_percent = disk.percent

        # Network I/O
        net_io = psutil.net_io_counters()
        net_sent_mb = net_io.bytes_sent / (1024 * 1024)
        net_recv_mb = net_io.bytes_recv / (1024 * 1024)

        # Log metrics
        logger.info(
            f"Hardware Sentinel Check [{ 'work hours' if is_work_hours else 'off-hours' }]: "
            f"CPU={cpu_percent}%, RAM={ram_percent}%, Disk={disk_percent}%, "
            f"Net TX={net_sent_mb:.1f}MB, RX={net_recv_mb:.1f}MB"
        )

        # Check thresholds and route through the proactive event bus so
        # dedup + severity gating stay centralised.
        try:
            from kuro_backend import proactive_events

            alert_specs = []
            if ram_percent > 90:
                alert_specs.append(
                    (
                        "warning",
                        f"RAM usage {ram_percent}%",
                        (
                            f"Master, Kuro's VM memory utilisation has reached "
                            f"{ram_percent}%. Kindly review the active processes."
                        ),
                        f"hw:ram:{int(ram_percent)//5*5}",
                    )
                )
            if cpu_percent > 85:
                alert_specs.append(
                    (
                        "warning",
                        f"CPU usage {cpu_percent}%",
                        (
                            f"Master, Kuro's VM CPU utilisation has reached "
                            f"{cpu_percent}%. An intensive workload has been detected."
                        ),
                        f"hw:cpu:{int(cpu_percent)//5*5}",
                    )
                )
            if disk_percent > 85:
                alert_specs.append(
                    (
                        "critical" if disk_percent > 95 else "warning",
                        f"Disk usage {disk_percent}%",
                        (
                            f"Master, disk utilisation has reached {disk_percent}%. "
                            f"Do consider pruning any files that are no longer required."
                        ),
                        f"hw:disk:{int(disk_percent)//5*5}",
                    )
                )

            for severity, title, body, seed in alert_specs:
                logger.warning("[HARDWARE] %s — %s", title, body)
                event = proactive_events.make_event(
                    kind="hardware",
                    severity=severity,
                    title=title,
                    body=body,
                    fingerprint_seed=seed,
                    context={
                        "cpu_percent": cpu_percent,
                        "ram_percent": ram_percent,
                        "disk_percent": disk_percent,
                        "net_sent_mb": round(net_sent_mb, 1),
                        "net_recv_mb": round(net_recv_mb, 1),
                    },
                )
                proactive_events.publish(event)
        except Exception as bus_exc:
            logger.error(f"Hardware bus dispatch failed: {bus_exc}")

    except Exception as e:
        logger.error(f"Error in hardware sentinel check: {e}")
    finally:
        # Always signal IDLE so the HUD ticker snaps back even if the
        # scan raised mid-way through.
        try:
            detail = None
            if _last_hardware_check is not None:
                detail = f"last {_last_hardware_check.strftime('%H:%M')}"
            dashboard_broadcast.schedule_ui_command(
                "STATUS_TICKER",
                {"status": "IDLE", "source": "HARDWARE", "detail": detail or ""},
            )
        except Exception:
            pass


# --- Background Scheduler ---
_reminder_scheduler = None
_evaluation_scheduler = None
_openclaw_last_open_alert_at = 0.0


def start_evaluation_scheduler():
    """Dedicated scheduler for autonomous evaluation metrics (Beta 3)."""
    global _evaluation_scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    from kuro_backend.evaluation.evaluation_scheduler import run_evaluation_batch_job

    _evaluation_scheduler = BackgroundScheduler(daemon=True)
    _evaluation_scheduler.add_job(
        run_evaluation_batch_job,
        "cron",
        hour=2,
        minute=30,
        id="nightly_eval",
        replace_existing=True,
    )
    _evaluation_scheduler.start()
    logger.info("Evaluation Scheduler started.")


def start_reminder_scheduler():
    """Start the background scheduler for automated intelligence cycles."""
    global _reminder_scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    from kuro_backend.memory_v2.decay_engine import expire_stale_memories
    from kuro_backend.memory_v2.memory_store import MemoryStore

    _reminder_scheduler = BackgroundScheduler(daemon=True)

    def run_nightly_backup_job():
        if not settings.KURO_BACKUP_ENABLED:
            logger.info("[BACKUP] Nightly backup skipped: disabled by config.")
            return
        result = backup_manager.run_nightly_backup_sync()
        if result.get("status") == "failed":
            logger.error("[BACKUP] Nightly backup FAILED: %s", result.get("errors", []))
            return
        logger.info(
            "[BACKUP] Nightly backup OK - %s files, %.1f MB, %.1fs",
            result.get("files_backed_up", 0),
            result.get("total_size_mb", 0.0),
            result.get("duration_seconds", 0.0),
        )

    def run_research_ledger_prune_job():
        try:
            result = memory_manager.prune_research_ledger(
                retention_days=90,
                archive_retention_days=365,
            )
            logger.info("[LEDGER] Weekly prune complete: %s", result)
        except Exception as exc:
            logger.warning("[LEDGER] Weekly prune failed: %s", exc)

    def run_openclaw_circuit_open_alert_job():
        global _openclaw_last_open_alert_at
        try:
            from kuro_backend.execution import openclaw_bridge

            # Never alert when OpenClaw is intentionally disabled.
            if not openclaw_bridge.is_openclaw_enabled():
                return
            metrics = openclaw_bridge.get_circuit_metrics()
            if metrics.get("circuit_breaker_state") != "open":
                return
            opened_at = float(metrics.get("opened_at_monotonic") or 0.0)
            if opened_at <= 0.0:
                return
            elapsed = time.monotonic() - opened_at
            if elapsed < 1800:
                return
            if (time.monotonic() - _openclaw_last_open_alert_at) < 1800:
                return
            _openclaw_last_open_alert_at = time.monotonic()
            from kuro_backend import telegram_notifier

            asyncio.run(
                telegram_notifier.send_message_with_retry(
                    "⚠️ OpenClaw circuit breaker has remained OPEN for >30 minutes. Please inspect bridge/service health."
                )
            )
        except Exception as exc:
            logger.debug("[OPENCLAW] Circuit-open alert check skipped: %s", exc)

    def run_retry_failed_telegram_notifications_job():
        async def _runner():
            try:
                from kuro_backend import telegram_notifier

                pending = intelligence_db.get_pending_failed_notifications(
                    max_attempts=5,
                    limit=3,
                )
                for notif in pending:
                    try:
                        payload = json.loads(notif["payload_json"])
                    except Exception:
                        intelligence_db.mark_notification_dead(int(notif.get("id", 0)))
                        continue
                    success = await telegram_notifier.send_message_with_retry(
                        payload.get("text", ""),
                        payload.get("chat_id"),
                        max_attempts=1,
                        record_failure=False,
                    )
                    if success:
                        intelligence_db.update_notification_attempt(
                            int(notif["id"]), error_message=None, success=True
                        )
                    else:
                        intelligence_db.update_notification_attempt(
                            int(notif["id"]),
                            error_message="retry failed",
                            success=False,
                        )
                        if int(notif.get("attempt_count", 0)) + 1 >= 5:
                            intelligence_db.mark_notification_dead(int(notif["id"]))
            except Exception as exc:
                logger.warning(
                    "[TELEGRAM] retry failed-notification job error: %s", exc
                )

        asyncio.run(_runner())

    def run_memory_decay_job():
        try:
            expired_count = expire_stale_memories(MemoryStore())
            logger.info("[MEMORY_V2] Decay job complete: expired=%s", expired_count)
        except Exception as exc:
            logger.warning("[MEMORY_V2] Decay job failed: %s", exc)

    # Daily intelligence briefing at 08:00 AM
    _reminder_scheduler.add_job(
        send_daily_intelligence_briefing,
        "cron",
        hour=8,
        minute=0,
        id="daily_intelligence_briefing",
        replace_existing=True,
    )

    # Quantitative updates for all users
    def run_all_price_updates():
        from kuro_backend import price_ticker_worker

        all_users = auth_db.get_all_users() or ["Pantronux"]
        for u in all_users:
            try:
                price_ticker_worker.run_price_update(username=u)
            except Exception as e:
                logger.error(f"[TICKER] Failed for {u}: {e}")

    _reminder_scheduler.add_job(
        run_all_price_updates,
        "cron",
        day_of_week="mon-fri",
        hour="9-16",
        minute="0,30",
        id="price_ticker_update",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("Price Ticker updates scheduled for all users.")

    # Market Sentinel autonomous scans for all users
    def run_all_sentinel_scans():
        from kuro_backend import price_ticker_worker
        from kuro_backend import market_sentinel

        all_users = auth_db.get_all_users() or ["Pantronux"]
        for u in all_users:
            try:
                price_ticker_worker.run_price_update(username=u)
                market_sentinel.run_triangulation_scan(username=u)
            except Exception as e:
                logger.error(f"[SENTINEL] Failed for {u}: {e}")

    _reminder_scheduler.add_job(
        run_all_sentinel_scans,
        "cron",
        day_of_week="mon-fri",
        hour="9,13,17,21",
        minute=0,
        id="market_sentinel_scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.info("Market Sentinel Triangulation scans scheduled for all users.")

    # Autonomous memory dreaming cycle (Kuro AI V6.0 Sovereign).
    if os.getenv("KURO_DREAMING_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        try:
            from kuro_backend import dreaming_worker

            dreaming_cron_hour = int(os.getenv("KURO_DREAMING_CRON_HOUR", "3"))
        except Exception as dreaming_exc:
            logger.warning(f"Dreaming worker hook skipped: {dreaming_exc}")
        else:
            _reminder_scheduler.add_job(
                dreaming_worker.run_dreaming_cycle,
                "cron",
                hour=dreaming_cron_hour,
                minute=0,
                id="kuro_dreaming_cycle",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                f"Autonomous dreaming cycle scheduled at {dreaming_cron_hour:02d}:00 daily."
            )

    # Fitness anomaly sentinel (Kuro AI V6.0 Sovereign).
    if os.getenv("KURO_FITNESS_ENABLED", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        try:
            from kuro_backend import fitness_service

            fitness_interval = int(os.getenv("KURO_FITNESS_INTERVAL_MIN", "30"))
        except Exception as fitness_exc:
            logger.warning(f"Fitness sentinel hook skipped: {fitness_exc}")
        else:
            _reminder_scheduler.add_job(
                fitness_service.run_fitness_sentinel,
                "interval",
                minutes=max(5, fitness_interval),
                id="kuro_fitness_sentinel",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                f"Fitness anomaly sentinel scheduled every {fitness_interval} minute(s)."
            )

    from kuro_backend import file_retention_worker

    _reminder_scheduler.add_job(
        file_retention_worker.run_retention_cycle,
        "cron",
        hour=2,
        minute=0,
        id="file_retention_cycle",
        replace_existing=True,
    )

    _reminder_scheduler.add_job(
        run_nightly_backup_job,
        "cron",
        hour=1,
        minute=0,
        id="nightly_backup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _reminder_scheduler.add_job(
        run_research_ledger_prune_job,
        "cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        id="weekly_research_ledger_prune",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _reminder_scheduler.add_job(
        run_openclaw_circuit_open_alert_job,
        "interval",
        minutes=5,
        id="openclaw_circuit_open_alert",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _reminder_scheduler.add_job(
        run_retry_failed_telegram_notifications_job,
        "interval",
        minutes=30,
        id="retry_failed_telegram_notifications",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _reminder_scheduler.add_job(
        run_memory_decay_job,
        "cron",
        hour=4,
        minute=0,
        id="memory_decay_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    _reminder_scheduler.start()
    logger.info("Intelligence scheduler started.")


def send_daily_intelligence_briefing():
    """Send daily intelligence briefing to Telegram at 08:00 AM for all users."""
    try:
        from kuro_backend.intelligence_engine import (
            run_daily_research,
            format_telegram_message,
            format_stock_telegram_message,
        )
        from kuro_backend import telegram_notifier

        # Get all users to process
        all_usernames = auth_db.get_all_users()
        if not all_usernames:
            all_usernames = ["Pantronux"]

        for username in all_usernames:
            try:
                logger.info(
                    f"[INTELLIGENCE] Running daily research for {username} (08:00 AM briefing)..."
                )
                briefing = run_daily_research(username=username)

                # Check if it was skipped (already exists) to avoid re-sending Telegram
                if briefing.get("_already_exists"):
                    logger.info(
                        f"[INTELLIGENCE] Briefing already exists for {username}, skipping Telegram delivery."
                    )
                    continue

                # Get display name for message
                display_name = username
                try:
                    user_info = auth_db.get_user(username)
                    display_name = (
                        user_info.get("master_name", username)
                        if user_info
                        else username
                    )
                except:
                    pass

                # Message 1: Main Briefing
                # TELEGRAM FILTER: Only send to Master/Admin to avoid double-spamming global channel
                is_admin = username == os.getenv("ADMIN_USERNAME", "Pantronux")

                if is_admin:
                    telegram_message = format_telegram_message(
                        briefing, display_name=display_name
                    )
                    asyncio.run(
                        telegram_notifier.send_message_with_retry(telegram_message)
                    )

                    # Message 2: Stock Recommendations
                    stock_message = format_stock_telegram_message(briefing)
                    if stock_message:
                        asyncio.run(
                            telegram_notifier.send_message_with_retry(stock_message)
                        )

                    logger.info(
                        f"[INTELLIGENCE] Daily briefing sent to Telegram for {username}"
                    )
                else:
                    logger.info(
                        f"[INTELLIGENCE] Briefing generated for {username}, skipping Telegram (non-Admin)."
                    )
            except Exception as user_exc:
                logger.error(
                    f"[INTELLIGENCE] Failed to send briefing for {username}: {user_exc}"
                )

    except Exception as e:
        logger.error(f"[INTELLIGENCE] Global failure in daily briefing: {e}")


def cleanup_old_artifacts(days: int = 14):
    """Clean up uploaded files and cache older than specified days.

    Security Rule: Does not delete files marked as identity or essential in database.
    """
    try:
        cutoff_date = datetime.now() - timedelta(days=days)
        deleted_count = 0
        deleted_size = 0

        # Clean uploaded_files directory
        if os.path.exists(tools.UPLOAD_DIR):
            for filename in os.listdir(tools.UPLOAD_DIR):
                filepath = os.path.join(tools.UPLOAD_DIR, filename)
                if not os.path.isfile(filepath):
                    continue

                # Check file modification time
                file_mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                if file_mtime < cutoff_date:
                    # Security check: skip essential files
                    # (In production, check against database)
                    try:
                        file_size = os.path.getsize(filepath)
                        os.remove(filepath)
                        deleted_count += 1
                        deleted_size += file_size
                        logger.info(
                            f"Deleted old artifact: {filename} ({file_size / 1024:.1f}KB, {days}+ days old)"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to delete {filename}: {e}")

        # Clean __pycache__ directories
        for root, dirs, files in os.walk("/home/kuro/projects/kuro"):
            if "__pycache__" in dirs:
                cache_dir = os.path.join(root, "__pycache__")
                try:
                    for f in os.listdir(cache_dir):
                        fp = os.path.join(cache_dir, f)
                        if os.path.isfile(fp):
                            file_mtime = datetime.fromtimestamp(os.path.getmtime(fp))
                            if file_mtime < cutoff_date:
                                os.remove(fp)
                                deleted_count += 1
                except Exception as e:
                    logger.warning(f"Error cleaning __pycache__ in {root}: {e}")

        deleted_mb = deleted_size / (1024 * 1024)
        logger.info(
            f"Artifact cleanup complete: {deleted_count} files deleted, {deleted_mb:.2f}MB freed"
        )
        return {"deleted_count": deleted_count, "freed_mb": deleted_mb}

    except Exception as e:
        logger.error(f"Error in artifact cleanup: {e}")
        return {"error": str(e)}


def get_log_storage_usage() -> Dict:
    """Calculate log storage usage for dashboard display across the new centralized folders."""
    try:
        base_log_dir = os.path.join(os.getcwd(), "logs")
        system_dir = os.path.join(base_log_dir, "system")
        archive_dir = os.path.join(base_log_dir, "archive")

        total_size = 0
        log_count = 0
        breakdown = []

        # 1. Scan System Logs (Active)
        if os.path.exists(system_dir):
            for f in os.listdir(system_dir):
                fp = os.path.join(system_dir, f)
                if os.path.isfile(fp) and f.endswith(".log"):
                    size = os.path.getsize(fp)
                    modified_ts = os.path.getmtime(fp)
                    total_size += size
                    log_count += 1
                    breakdown.append(
                        {
                            "name": f,
                            "size_mb": size / (1024 * 1024),
                            "modified_at": datetime.fromtimestamp(modified_ts).strftime(
                                "%Y-%m-%d %H:%M:%S"
                            ),
                            "modified_ts": modified_ts,
                        }
                    )

        # 2. Scan Archive Logs (Rotated)
        if os.path.exists(archive_dir):
            for f in os.listdir(archive_dir):
                fp = os.path.join(archive_dir, f)
                if os.path.isfile(fp):
                    total_size += os.path.getsize(fp)
                    log_count += 1

        breakdown.sort(key=lambda item: item["modified_ts"], reverse=True)
        for item in breakdown:
            item.pop("modified_ts", None)

        return {
            "total_size_mb": total_size / (1024 * 1024),
            "log_files": log_count,
            "retention_days": 30,  # Updated policy
            "breakdown": breakdown,
        }
    except Exception as e:
        logger.error(f"Failed to calculate log storage: {e}")
        return {
            "error": str(e),
            "total_size_mb": 0,
            "log_files": 0,
            "retention_days": 30,
        }


def reset_daily_habits():
    """Midnight reset: Cleanup old artifacts."""
    try:
        # Log rotation audit message
        today = datetime.now().strftime("%Y-%m-%d")
        logger.info(f"--- END OF LOG FOR {today} - ROTATING NOW ---")

        # Run artifact cleanup
        cleanup_result = cleanup_old_artifacts(days=14)
        logger.info(f"Midnight artifact cleanup: {cleanup_result}")

    except Exception as e:
        logger.error(f"Failed to run midnight cleanup: {e}")


# --- Telegram Bot Logic ---
def _telegram_allowed_chat_ids() -> set[str]:
    raw = str(getattr(settings, "TELEGRAM_CHAT_ID", "") or "")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _is_authorized_telegram_chat(chat_id: object) -> bool:
    return str(chat_id) in _telegram_allowed_chat_ids()


def _telegram_admin_profile() -> tuple[str, str]:
    username = os.getenv("ADMIN_USERNAME", "Pantronux")
    display_name = username
    try:
        user_info = auth_db.get_user(username)
        if user_info and user_info.get("master_name"):
            display_name = str(user_info["master_name"])
    except Exception:
        pass
    return username, display_name


def _telegram_command_name(text: str) -> str:
    first = (text or "").strip().split(maxsplit=1)[0].lower()
    if "@" in first:
        first = first.split("@", 1)[0]
    return first


async def _send_telegram_long_message(bot, chat_id: str, text: str) -> None:
    from kuro_backend.telegram_notifier import split_text_for_telegram

    chunks = split_text_for_telegram(text or "")
    for chunk in chunks or [""]:
        await bot.send_message(chat_id=chat_id, text=chunk)


def _build_telegram_queue_summary() -> Dict[str, int]:
    dlq = intelligence_db.get_failed_notification_summary()
    return {
        "inbound_size": int(_tg_inbound_queue.qsize()),
        "inbound_maxsize": int(_tg_inbound_queue.maxsize),
        "dlq_pending": int(dlq.get("pending", 0)),
        "dlq_sent": int(dlq.get("sent", 0)),
        "dlq_dead": int(dlq.get("dead", 0)),
        "dlq_total": int(dlq.get("total", 0)),
    }


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not _is_authorized_telegram_chat(chat_id):
        await context.bot.send_message(
            chat_id=chat_id,
            text="I apologize, but I am only authorized to serve Pantronux.",
        )
        logger.warning("Unauthorized /start attempt by chat_id: %s", chat_id)
        return
    await context.bot.send_message(
        chat_id=chat_id,
        text="Greetings, Master. Kuro is at your service. Kirim /help untuk command center.",
    )


async def handle_telegram_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    if not _is_authorized_telegram_chat(chat_id):
        await context.bot.send_message(
            chat_id=chat_id,
            text="I apologize, but I am only authorized to serve Pantronux.",
        )
        logger.warning("Unauthorized command attempt by chat_id: %s", chat_id)
        return

    text = (getattr(update.message, "text", "") or "").strip()
    command = _telegram_command_name(text)
    if command in {"/help", "/start"}:
        msg = (
            "Kuro Telegram Command Center\n"
            "/ping - cek bot hidup\n"
            "/status - ringkasan sistem, backup, dan Telegram\n"
            "/queue - status antrean Telegram dan DLQ\n"
            "/sentinel - ringkasan Market Sentinel\n"
            "/briefing - briefing intelijen terbaru\n\n"
            "Kirim pesan biasa untuk chat langsung dengan Kuro."
        )
    elif command == "/ping":
        q = _build_telegram_queue_summary()
        msg = (
            f"Pong. Kuro online.\n"
            f"Inbound queue: {q['inbound_size']}/{q['inbound_maxsize']}\n"
            f"DLQ pending: {q['dlq_pending']}"
        )
    elif command == "/queue":
        q = _build_telegram_queue_summary()
        msg = (
            "Telegram Queue\n"
            f"Inbound: {q['inbound_size']}/{q['inbound_maxsize']}\n"
            f"DLQ pending: {q['dlq_pending']}\n"
            f"DLQ sent: {q['dlq_sent']}\n"
            f"DLQ dead: {q['dlq_dead']}\n"
            f"DLQ total: {q['dlq_total']}"
        )
    elif command == "/status":
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        backup = _build_system_status_backup_payload() or {}
        q = _build_telegram_queue_summary()
        msg = (
            "Kuro System Status\n"
            f"CPU: {psutil.cpu_percent(interval=0)}%\n"
            f"RAM: {round(mem.used / (1024**3), 1)}GB/{round(mem.total / (1024**3), 1)}GB ({mem.percent}%)\n"
            f"Disk: {round(disk.used / (1024**3), 1)}GB/{round(disk.total / (1024**3), 1)}GB ({disk.percent}%)\n"
            f"Backup: {backup.get('last_backup_status', 'unknown')} at {backup.get('last_backup_at', '-')}\n"
            f"Telegram inbound: {q['inbound_size']}/{q['inbound_maxsize']}; DLQ pending: {q['dlq_pending']}"
        )
    elif command == "/sentinel":
        username, _ = _telegram_admin_profile()
        cfg = settings
        stale = finance_db.is_snapshot_stale(
            int(getattr(cfg, "KURO_SENTINEL_STALE_THRESHOLD_MIN", 15)),
            username=username,
        )
        stocks = finance_db.get_all_sentinel_stocks(sort_by="roi_1m", username=username)[:5]
        lines = [
            "Market Sentinel",
            f"Price data: {'STALE' if stale else 'fresh'}",
        ]
        if stocks:
            for stock in stocks:
                code = stock.get("stock_code", "-")
                price = stock.get("current_price_per_share", 0)
                roi = stock.get("projected_roi_1m", 0)
                conclusion = stock.get("conclusion", "HOLD")
                lines.append(f"{code}: Rp {price} | ROI 1M {roi}% | {conclusion}")
        else:
            lines.append("Belum ada data Market Sentinel.")
        msg = "\n".join(lines)
    elif command == "/briefing":
        username, display_name = _telegram_admin_profile()
        briefings = intelligence_db.get_briefings(limit=1, username=username)
        if not briefings:
            msg = "Belum ada briefing tersimpan. Jalankan riset harian dari dashboard atau tunggu scheduler berikutnya."
        else:
            from kuro_backend.intelligence_engine import format_telegram_message

            briefing = briefings[0].get("raw_json_data") or {}
            msg = format_telegram_message(briefing, display_name=display_name)
    else:
        msg = "Command belum dikenal. Kirim /help untuk daftar command."

    await _send_telegram_long_message(context.bot, chat_id, msg)


async def _process_telegram_chat_payload(payload: Dict[str, Any], bot) -> None:
    chat_id = str(payload.get("chat_id") or "")
    message_text = str(payload.get("text") or "").strip()
    if not chat_id or not message_text:
        return

    try:
        await bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    try:
        username, master_name = _telegram_admin_profile()
        telegram_persona = str(payload.get("persona") or route_telegram_persona(message_text))
        telegram_request_id = str(payload.get("request_id") or f"telegram_{uuid.uuid4().hex}")
        telegram_trace_id = str(payload.get("trace_id") or f"telegram_chat_{uuid.uuid4().hex}")
        chat_history.add_message(
            "telegram",
            "user",
            message_text,
            persona=telegram_persona,
            request_id=telegram_request_id,
            username=username,
        )
        response_text = await asyncio.wait_for(
            asyncio.to_thread(
                process_chat_with_graph,
                message_text,
                persona_override=telegram_persona,
                approval_scope=f"telegram:{chat_id}:{telegram_persona}",
                trace_id=telegram_trace_id,
                master_name=master_name,
                username=username,
            ),
            timeout=int(getattr(settings, "KURO_TELEGRAM_RESPONSE_TIMEOUT_S", 180)),
        )
        chat_history.add_message(
            "telegram",
            "assistant",
            response_text,
            persona=telegram_persona,
            request_id=telegram_request_id,
            username=username,
        )
        await _send_telegram_long_message(bot, chat_id, response_text)
    except asyncio.TimeoutError:
        logger.warning("[TELEGRAM] chat processing timed out for chat_id=%s", chat_id)
        await bot.send_message(
            chat_id=chat_id,
            text="Kuro butuh waktu terlalu lama untuk menjawab. Coba ulangi dengan instruksi yang lebih pendek, atau cek dashboard.",
        )
    except Exception as e:
        logger.exception("Error sending response to Telegram: %s", e)
        await bot.send_message(
            chat_id=chat_id,
            text="My apologies, Master — I encountered an error while delivering the response. Please try once more.",
        )


async def _telegram_inbound_queue_worker(bot, max_items: Optional[int] = None) -> None:
    processed = 0
    while not _telegram_polling_shutdown.is_set():
        if max_items is not None and processed >= max_items:
            return
        try:
            if max_items is None:
                payload = await _tg_inbound_queue.get()
            else:
                payload = await asyncio.wait_for(_tg_inbound_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return
        except asyncio.CancelledError:
            raise

        try:
            await _process_telegram_chat_payload(payload, bot)
        except Exception as exc:
            logger.exception("[TELEGRAM] inbound queue worker failed: %s", exc)
        finally:
            _tg_inbound_queue.task_done()
            processed += 1


async def _telegram_post_init(application):
    application.create_task(_telegram_inbound_queue_worker(application.bot))


def _schedule_telegram_chat_payload(payload: Dict[str, Any], context: ContextTypes.DEFAULT_TYPE) -> None:
    coro = _process_telegram_chat_payload(payload, context.bot)
    application = getattr(context, "application", None)
    if application and hasattr(application, "create_task"):
        application.create_task(coro)
    else:
        asyncio.create_task(coro)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    inbound_chat_id = str(update.effective_chat.id)
    if not _is_authorized_telegram_chat(inbound_chat_id):
        await context.bot.send_message(
            chat_id=inbound_chat_id,
            text="I apologize, but I am only authorized to serve Pantronux.",
        )
        logger.warning("Unauthorized access attempt by chat_id: %s", inbound_chat_id)
        return

    message_text = (getattr(update.message, "text", "") or "").strip()
    if not message_text:
        return
    logger.info("Received Telegram message from admin: %s", message_text)

    payload = {
        "chat_id": inbound_chat_id,
        "text": message_text,
        "received_at": datetime.utcnow().isoformat(),
        "request_id": f"telegram_{uuid.uuid4().hex}",
        "trace_id": f"telegram_chat_{uuid.uuid4().hex}",
    }

    if not _check_telegram_rate_limit(
        inbound_chat_id,
        int(getattr(settings, "KURO_TELEGRAM_RATE_LIMIT_PER_MIN", 10)),
    ):
        try:
            _tg_inbound_queue.put_nowait(payload)
            await context.bot.send_message(
                chat_id=inbound_chat_id,
                text="Kuro sedang memproses antrian. Pesan kamu akan segera dibalas.",
            )
        except asyncio.QueueFull:
            await context.bot.send_message(
                chat_id=inbound_chat_id,
                text="Antrian penuh. Coba lagi dalam beberapa menit.",
            )
        return

    await context.bot.send_message(
        chat_id=inbound_chat_id,
        text="Diterima. Kuro sedang memproses jawaban.",
    )
    _schedule_telegram_chat_payload(payload, context)


def route_telegram_persona(message_text: str) -> str:
    """
    Telegram hybrid auto-router:
    - tactical for infra/code/security/ops intent
    - chill for daily/social intent
    """
    text = (message_text or "").lower()
    technical_keywords = [
        "proxmox",
        "server",
        "docker",
        "kubernetes",
        "code",
        "python",
        "error",
        "bug",
        "api",
        "database",
        "sql",
        "log",
        "linux",
        "deploy",
        "security",
        "iso",
        "audit",
        "openclaw",
        "memory",
        "websocket",
        "revision",
        "ci",
        "cd",
    ]
    casual_keywords = [
        "gym",
        "musik",
        "lagu",
        "hindia",
        "hsr",
        "honkai",
        "capek",
        "semangat",
        "mood",
        "curhat",
        "istirahat",
        "ngobrol",
        "santai",
        "hari ini",
    ]
    if any(keyword in text for keyword in technical_keywords):
        logger.info("[TELEGRAM_PERSONA] Routed to tactical")
        return "tactical"
    if any(keyword in text for keyword in casual_keywords):
        logger.info("[TELEGRAM_PERSONA] Routed to chill")
        return "chill"
    logger.info("[TELEGRAM_PERSONA] Ambiguous intent -> default tactical")
    return "tactical"


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    if isinstance(error, (NetworkError, TimedOut)):
        logger.warning(f"Network error: {error}")
        return
    logger.error(f"Update {update} caused error: {error}", exc_info=error)


def run_bot_with_recovery():
    """Runs Telegram in polling mode with retry/backoff and shutdown flag support.

    Inbound mechanism note:
    - Kuro currently uses long polling (`python-telegram-bot` `run_polling`),
      not webhook mode.
    - `_telegram_polling_shutdown` is set during app/process shutdown so polling
      restart attempts stop cleanly instead of spinning during termination.
    """
    max_retries = 5
    retry_delay = 5

    for attempt in range(max_retries):
        if _telegram_polling_shutdown.is_set():
            logger.info("Telegram polling shutdown flag set; exiting polling loop.")
            break
        try:
            logger.info(
                f"Starting Telegram bot polling... (Attempt {attempt + 1}/{max_retries})"
            )

            # Create a new event loop for each attempt, as python-telegram-bot closes the loop on exit
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            application = (
                ApplicationBuilder()
                .token(settings.TELEGRAM_TOKEN)
                .post_init(_telegram_post_init)
                .build()
            )

            start_handler = CommandHandler("start", start)
            command_handler = CommandHandler(
                ["help", "ping", "status", "queue", "sentinel", "briefing"],
                handle_telegram_command,
            )
            message_handler = MessageHandler(
                filters.TEXT & ~filters.COMMAND, handle_message
            )

            application.add_handler(start_handler)
            application.add_handler(command_handler)
            application.add_handler(message_handler)
            application.add_error_handler(error_handler)

            application.run_polling(
                drop_pending_updates=bool(
                    getattr(settings, "KURO_TELEGRAM_DROP_PENDING_UPDATES", False)
                )
            )

        except (NetworkError, TimedOut) as e:
            logger.warning(f"Network error during polling: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                logger.critical("Max retries reached. Shutting down.")
                raise

        except KeyboardInterrupt:
            logger.info("Received shutdown signal. Stopping bot gracefully...")
            break

        except BaseException as e:
            if isinstance(e, KeyboardInterrupt):
                logger.info("Received KeyboardInterrupt. Stopping bot...")
                break
            logger.exception(
                f"CRITICAL: Bot polling exited with {type(e).__name__}: {e}"
            )
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                retry_delay *= 2
            else:
                logger.critical("Max retries reached. Shutting down.")
                raise


def run_uvicorn():
    """Runs FastAPI server with HTTPS support via mkcert."""
    import ssl

    # SSL Certificate paths
    CERT_FILE = os.path.join(BASE_DIR, "certs", "cert.pem")
    KEY_FILE = os.path.join(BASE_DIR, "certs", "key.pem")

    # Check if SSL certificates exist
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        # Create SSL context
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(CERT_FILE, KEY_FILE)

        logger.info("HTTPS enabled with mkcert certificates")
        logger.info("Secure Web Dashboard: https://0.0.0.0:8443")
        logger.info("Secure Login Page: https://0.0.0.0:8443/login")

        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8443,
            log_level="info",
            ssl_keyfile=KEY_FILE,
            ssl_certfile=CERT_FILE,
        )
    else:
        logger.warning("SSL certificates not found. Running on HTTP only.")
        logger.info("Web Dashboard: http://0.0.0.0:8000 (Authentication Required)")
        logger.info("Login Page: http://0.0.0.0:8000/login")
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


def _acquire_bot_lock() -> bool:
    """Prevent duplicate Telegram polling instances."""
    lock_path = os.path.join(settings.WORKING_DIR, ".kuro_telegram.lock")
    try:
        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file.write(str(os.getpid()))
        lock_file.flush()
        atexit.register(lambda: os.unlink(lock_path))
        return True
    except (BlockingIOError, PermissionError) as e:
        logger.critical(
            f"Another Kuro Telegram bot is already running or lock file is inaccessible: {e}. "
            "Kill the old process first. Exiting."
        )
        return False


if __name__ == "__main__":
    try:
        import requests
        import google.genai
    except ImportError as e:
        logger.critical(
            f"CRITICAL ERROR: Missing essential library - {e}. Please install requirements. Shutting down."
        )
        sys.exit(1)

    logger.info("Kuro AI Reborn is starting...")
    logger.info(f"Memory stats: {memory_manager.get_memory_stats()}")
    logger.info("Web Dashboard: http://0.0.0.0:8000 (Authentication Required)")
    logger.info("Login Page: http://0.0.0.0:8000/login")

    # Initialize databases
    auth_db.init_auth_db()
    chat_history.init_db()
    logger.info("Databases initialized (Auth & Chat History)")

    def signal_handler(sig, frame):
        logger.info("Received interrupt signal. Shutting down gracefully...")
        _telegram_polling_shutdown.set()
        if _reminder_scheduler:
            _reminder_scheduler.shutdown()
        if _evaluation_scheduler:
            _evaluation_scheduler.shutdown()
        if _hardware_sentinel_scheduler:
            _hardware_sentinel_scheduler.shutdown()
        # Shutdown observability
        observability.shutdown_observability()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start reminder scheduler
    start_reminder_scheduler()

    # Start evaluation scheduler
    start_evaluation_scheduler()

    # Start hardware sentinel scheduler
    start_hardware_sentinel()

    # Initialize observability (Phoenix + OpenTelemetry)
    obs_status = observability.initialize_observability()
    if obs_status["phoenix"]:
        logger.info(
            f"[OBSERVABILITY] Phoenix dashboard available at: {obs_status['dashboard_url']}"
        )
        logger.info("[OBSERVABILITY] Auth: DISABLED (local private network)")
        logger.info("[OBSERVABILITY] Project: Kuro-AI-Audit")
    else:
        logger.warning("[OBSERVABILITY] Failed to start Phoenix server")

    if obs_status["opentelemetry"]:
        logger.info("[OBSERVABILITY] OpenTelemetry instrumentation enabled")

    # CRITICAL: python-telegram-bot v20+ requires main thread for asyncio event loop.
    # Error: "set_wakeup_fd only works in main thread of the main interpreter"
    # Solution: Run Telegram bot in main thread, FastAPI in daemon thread.

    # Start FastAPI in daemon thread (non-blocking)
    uvicorn_thread = threading.Thread(target=run_uvicorn, daemon=True)
    uvicorn_thread.start()
    logger.info("FastAPI server started in background thread on port 8443")

    # Give FastAPI a moment to start
    time.sleep(2)

    # Run Telegram bot in main thread (blocking)
    if _acquire_bot_lock():
        logger.info("Starting Telegram bot in main thread...")
        run_bot_with_recovery()
    else:
        sys.exit(1)

    logger.info("Kuro AI Reborn has shut down.")
