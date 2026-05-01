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
import uvicorn
from typing import Any, Dict, Optional
from datetime import date, datetime, timedelta
from fastapi import FastAPI, UploadFile, File, Form, Request, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse, StreamingResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from jose import JWTError, jwt
from passlib.context import CryptContext
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import NetworkError, TimedOut

# --- Early warning suppression (must run before heavy imports initialize) ---
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*Pydantic V1 style.*")
logging.getLogger("pydantic").setLevel(logging.ERROR)
logging.getLogger("opentelemetry").setLevel(logging.ERROR)

from kuro_backend.config import settings
from kuro_backend.core import process_chat
from kuro_backend.langgraph_core import process_chat_with_graph, process_chat_with_graph_stream
from kuro_backend import memory_manager
from kuro_backend import memory_coordinator
from kuro_backend import chat_history
from kuro_backend import tools
from kuro_backend import compliance_db

from kuro_backend import dashboard_broadcast
from kuro_backend.services import core_service as core_data
from kuro_backend.services.async_adapter import run_db
from kuro_backend.services.schemas import (
    ApiUsageDailyRecord,
    MarketHudChip,
    MonthlyBudgetRecord,
    PredictionWatchRecord,
    RecurringExpenseRecord,
    WatchedSymbolRecord,
)
from kuro_backend import finance_db
from kuro_backend import auth_db
from kuro_backend import observability
from kuro_backend import intelligence_db
from kuro_backend import persona_history_admin
from kuro_backend import version as kuro_version
from kuro_backend import proactive_greeting

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
    raise RuntimeError("JWT_SECRET_KEY environment variable is required. Set it in .env file.")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "12"))

# Admin credentials from .env
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "Pantronux")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")

# Secondary User: Faikhira (V7.2.2 Restricted Access)
FAIKHIRA_USERNAME = os.getenv("FAIKHIRA_USERNAME", "Faikhira")
FAIKHIRA_PASSWORD_HASH = os.getenv("FAIKHIRA_PASSWORD_HASH", "")
FAIKHIRA_MASTER_NAME = os.getenv("FAIKHIRA_MASTER_NAME", "Master Faikhira")

# Cookie name for JWT token
COOKIE_NAME = "kuro_access_token"
CHAT_SESSION_HEADER = "X-Chat-Session"
_CHAT_SESSION_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")

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


def api_success(data: Any = None, trace_id: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": "success", "data": data, "error": None, "trace_id": trace_id}
    payload.update(extra)
    return payload


def api_error(error: str, trace_id: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"status": "error", "data": None, "error": error, "trace_id": trace_id}
    payload.update(extra)
    return payload


def _resolve_chat_session_id(request: Request) -> str:
    raw = (request.headers.get(CHAT_SESSION_HEADER) or "").strip()
    if raw and _CHAT_SESSION_PATTERN.match(raw):
        return raw
    return f"fallback_{request.client.host}_default"

# --- FastAPI App ---
app = FastAPI(title="Kuro AI Web Dashboard")


@app.on_event("startup")
async def _register_dashboard_sync_loop():
    """Enable cross-thread revision bumps to schedule WebSocket REFRESH_NOW."""
    core_data.register_main_event_loop(asyncio.get_running_loop())


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
    remember_me: str = Form("false")
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
                "remaining_seconds": lockout_status['remaining_minutes'] * 60 + lockout_status['remaining_seconds']
            }
        )
    
    # Validate user existence (database-backed)
    user_info = auth_db.get_user(username)
    
    if not user_info:
        failed_count = auth_db.record_failed_attempt(username, client_ip, user_agent)
        if failed_count >= auth_db.MAX_FAILED_ATTEMPTS:
            auth_db.lock_account(username)
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": "Username atau password salah."}
        )
    
    # Use the correctly-cased username from DB
    username = user_info["username"]
    
    # Verify password
    if not verify_password(password, user_info["password_hash"]):
        failed_count = auth_db.record_failed_attempt(username, client_ip, user_agent)
        logger.warning(f"Failed login attempt {failed_count} for user: {username} from {client_ip}")
        
        if failed_count >= auth_db.MAX_FAILED_ATTEMPTS:
            auth_db.lock_account(username)
            logger.warning(f"ACCOUNT LOCKED: {username} - Too many failed attempts ({failed_count})")
            return JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": "Terlalu banyak percobaan login. Akun dikunci selama 15 menit untuk keamanan.",
                    "locked": True,
                    "remaining_seconds": auth_db.LOCKOUT_DURATION_MINUTES * 60
                }
            )
        
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "error": f"Username atau password salah. ({auth_db.MAX_FAILED_ATTEMPTS - failed_count} percobaan tersisa)",
                "attempts_remaining": auth_db.MAX_FAILED_ATTEMPTS - failed_count
            }
        )
    
    # Successful login
    auth_db.clear_failed_attempts(username)
    auth_db.record_successful_login(username, client_ip, user_agent)
    
    # Create access token
    access_token_expires = timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    access_token = create_access_token(
        data={"sub": username},
        expires_delta=access_token_expires
    )
    
    logger.info(f"Successful login: {username} from {client_ip}")
    
    # Set token in HttpOnly cookie
    response = JSONResponse(content={
        "success": True,
        "username": username
    })
    response.set_cookie(
        key=COOKIE_NAME,
        value=f"Bearer {access_token}",
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_HOURS * 3600,
        path="/"
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
        status_code=401,
        content={"success": False, "error": "Invalid or expired token"}
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
    response = JSONResponse(content={"success": True, "message": "Logged out successfully"})
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
            "custom_persona": user_info.get("custom_persona", "")
        }
    )

@app.post("/api/user/update")
async def update_profile(
    request: Request,
    username_new: str = Form(None),
    display_name: str = Form(...),
    email: str = Form(...)
):
    """Update user profile information."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "Unauthorized"})
    
    username = user.get("username")
    
    # Note: username_new is currently ignored to prevent complex session invalidation issues,
    # but could be implemented later if required.
    
    success = auth_db.update_user_profile(username, email, display_name)
    if success:
        return {"success": True, "message": "Profile updated successfully"}
    return JSONResponse(status_code=500, content={"success": False, "error": "Failed to update profile"})

@app.post("/api/user/change-password")
async def change_password(
    request: Request,
    old_password: str = Form(...),
    new_password: str = Form(...),
    repeat_password: str = Form(...)
):
    """Handle password change with old password verification."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "Unauthorized"})
    
    if new_password != repeat_password:
        return JSONResponse(status_code=400, content={"success": False, "error": "New passwords do not match"})
        
    username = user.get("username")
    user_info = auth_db.get_user(username)
    
    if not verify_password(old_password, user_info["password_hash"]):
        return JSONResponse(status_code=401, content={"success": False, "error": "Old password incorrect"})
    
    # Hash new password
    from passlib.hash import bcrypt
    new_hash = bcrypt.hash(new_password)
    
    success = auth_db.update_password(username, new_hash)
    if success:
        return {"success": True, "message": "Password changed successfully"}
    return JSONResponse(status_code=500, content={"success": False, "error": "Failed to update password"})

@app.post("/api/user/update-persona")
async def update_persona(
    request: Request,
    custom_persona: str = Form(...)
):
    """Update user's custom global persona instructions."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    if not user:
        return JSONResponse(status_code=401, content={"success": False, "error": "Unauthorized"})
    
    username = user.get("username")
    success = auth_db.update_custom_persona(username, custom_persona)
    if success:
        return {"success": True, "message": "Custom persona updated successfully"}
    return JSONResponse(status_code=500, content={"success": False, "error": "Failed to update persona"})

# CORS Middleware - SECURITY: Restrict to specific allowed origins
ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "https://localhost:8443,https://127.0.0.1:8443,http://localhost:8000"
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
app.mount("/static", StaticFiles(directory=os.path.join(WEB_DIR, "static")), name="static")
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
    ".pdf", ".csv", ".txt", ".md", ".rtf", ".doc", ".docx",
    ".xls", ".xlsx", ".ppt", ".pptx", ".json", ".yaml", ".yml",
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
    if ctype.startswith("text/") or ext in _DOC_EXTENSIONS or ctype in {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }:
        return "docs"
    return "misc"


def _build_unique_filename(original_name: str, timestamp: str, random_suffix: str = "") -> str:
    """Build storage filename with optional random suffix failsafe."""
    slug_base, ext = _slugify_filename_base(original_name)
    suffix = f"_{random_suffix}" if random_suffix else ""
    return f"{slug_base}_{timestamp}{suffix}{ext}"


async def save_upload_file(file: UploadFile) -> Dict[str, str]:
    """
    Save uploaded file with deterministic unique filename and category folder.
    Format: {slugified_original}_{YYYYMMDD_HHMMSS}.{ext}
    Failsafe: append random 4-digit suffix on collision.
    """
    original_name = (file.filename or "").strip() or "file"
    _, ext = _slugify_filename_base(original_name)
    subdir = _resolve_upload_subdir(file.content_type or "", ext)
    target_dir = os.path.join(UPLOAD_DIR, subdir)
    os.makedirs(target_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_name = _build_unique_filename(original_name, timestamp)
    target_path = os.path.join(target_dir, unique_name)
    collision_used = False

    if os.path.exists(target_path):
        collision_used = True
        # Very rare same-second collision; use 4-digit random suffix as failsafe.
        for _ in range(10):
            suffix = f"{random.randint(1000, 9999)}"
            unique_name = _build_unique_filename(original_name, timestamp, random_suffix=suffix)
            target_path = os.path.join(target_dir, unique_name)
            if not os.path.exists(target_path):
                break

    content = await file.read()
    with open(target_path, "wb") as f:
        f.write(content)
    sha256_hash = hashlib.sha256(content).hexdigest()
    size_bytes = len(content)

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
PUBLIC_API_ROUTES = ["/api/login", "/api/auth/verify", "/api/auth/stats", "/api/auth/logout"]

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
    
    if path == "/" or path in ["/chat"] :
        if not is_authenticated:
            logger.info(f"Unauthenticated access to {path} from {request.client.host}, redirecting to /login")
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
                content=api_error("Authentication required. Please log in.")
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
            "restricted_persona": user_info.get("restricted_persona") or "",
            "master_name": user_info.get("master_name", f"Master {username}")
        }
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
            "restricted_persona": user_info.get("restricted_persona") or "",
            "master_name": user_info.get("master_name", f"Master {username}")
        }
    )

@app.get("/api/history")
async def get_chat_history(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    platform: str = None,
    persona: str = None
):
    """Get chat history from database with pagination for infinite scroll.
    
    Args:
        limit: Number of messages to return
        offset: Pagination offset
        platform: Filter by platform ('web', 'telegram', or None for all)
        persona: Filter by persona mode (defaults to active persona)
    """
    token = get_token_from_cookie(request)
    user = validate_token(token)
    username = user.get("username") if user else ADMIN_USERNAME
    user_info = auth_db.get_user(username) or {}
    
    # Persona restriction enforcement
    restricted_persona = user_info.get("restricted_persona")
    if restricted_persona:
        resolved_persona = restricted_persona
    else:
        resolved_persona = memory_manager.normalize_persona(persona or memory_manager.get_active_persona())

    history = chat_history.get_history(
        limit=limit,
        offset=offset,
        platform=platform,
        persona=resolved_persona,
        username=username,
    )
    total = chat_history.get_total_count(platform=platform, persona=resolved_persona, username=username)
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
    username = user.get("username") if user else ADMIN_USERNAME
    
    chat_history.clear_history(username=username, persona=persona)
    target = f"persona '{persona}'" if persona else "all personas"
    return api_success(data={"message": f"Chat history for {target} cleared for {username}"}, message=f"Chat history for {target} cleared for {username}")


@app.get("/api/chat/search")
async def search_chat_history(request: Request, q: str, persona: Optional[str] = None):
    """Search chat history for a keyword."""
    token = get_token_from_cookie(request)
    user = validate_token(token)
    username = user.get("username") if user else ADMIN_USERNAME
    
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
            "disk": _psutil.disk_usage('/').percent,
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
):
    """Handle chat requests from the web interface with vision and file reading support. (Non-streaming fallback)"""
    try:
        # Resolve user context
        token = get_token_from_cookie(request)
        user = validate_token(token)
        username = user.get("username") if user else ADMIN_USERNAME
        user_info = auth_db.get_user(username) or {}
        master_name = user_info.get("master_name", "Master Pantronux")
        
        trace_id = f"chat_{uuid.uuid4().hex}"
        
        # Persona restriction
        restricted_persona = user_info.get("restricted_persona")
        if restricted_persona:
            resolved_persona = restricted_persona
        else:
            resolved_persona = memory_manager.normalize_persona(
                persona or request.query_params.get("persona") or memory_manager.get_active_persona()
            )
            
        request_id = f"web_{uuid.uuid4().hex}"
        session_scope = _resolve_chat_session_id(request)

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
                    "web", "user", message, [],
                    persona=resolved_persona, request_id=request_id,
                )
                chat_history.add_message(
                    "web", "assistant", ack,
                    persona=resolved_persona, request_id=request_id,
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
                saved_file = await save_upload_file(file)
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
                )
                
                # Check if it's an image for vision processing
                if file.content_type and file.content_type.startswith("image/"):
                    image_paths.append(file_path)
                    file_attachments.append({
                        "type": "image",
                        "original_filename": saved_file["original_filename"],
                        "stored_filename": stored_filename,
                        "path": file_path,
                    })
                    file_contents.append(f"\n--- Gambar Dilampirkan: {saved_file['original_filename']} ---\n(Gambar ini telah diteruskan ke modul Vision Anda untuk dianalisis)")
                else:
                    # Use smart_read facade for Office/PDF/text/log files
                    read_result = tools.smart_read(file_ref=file_path, instruction="ekstrak konten utama file ini", max_chars=10000)
                    parsed_content = read_result.get("summary") or read_result.get("content")
                    if parsed_content:
                        file_contents.append(f"\n--- File: {saved_file['original_filename']} ---\n{parsed_content}")
                    session_extractions.append({
                        "original_filename": saved_file["original_filename"],
                        "stored_filename": stored_filename,
                        "path": file_path,
                        "extracted_content": (parsed_content or "")[:5000],
                    })
                    
                    file_attachments.append({
                        "type": "file",
                        "original_filename": saved_file["original_filename"],
                        "stored_filename": stored_filename,
                        "path": file_path,
                    })
                
                logger.info(f"File saved: {file_path}")
        
        # Build enhanced message with file contents
        enhanced_message = message
        if file_contents:
            enhanced_message += "\n\n[Attached Files Content:]\n" + "\n".join(file_contents)
        att_idx = memory_coordinator.format_same_turn_attachment_index(file_attachments)
        if att_idx:
            enhanced_message += "\n\n" + att_idx
        if image_paths:
            memory_manager.set_runtime_context_value("last_accessed_file", image_paths[-1])
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
                    content=ex.get("extracted_content", "")
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
        )
        
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
        )
        
        # Save AI response to chat history
        chat_history.add_message("web", "assistant", response, persona=resolved_persona, request_id=request_id, username=username)
        
        return api_success(
            data={"response": response},
            trace_id=trace_id,
            response=response,  # backward compatibility for current frontend
        )
        
    except Exception as e:
        logger.exception(f"Error in chat endpoint: {e}")
        return api_error(f"My apologies, {master_name} — an error occurred: {e}")


@app.post("/api/chat/stream")
async def chat_stream_endpoint(
    request: Request,
    message: str = Form(""),
    files: list[UploadFile] = File([]),
    persona: str = Form(None),
):
    """V6.0 STREAMING: Handle chat requests with Server-Sent Events (SSE) streaming."""
    from fastapi.responses import StreamingResponse
    
    async def event_generator():
        """Generate SSE events for streaming response."""
        request_started = time.perf_counter()
        trace_id = f"chatstream_{uuid.uuid4().hex}"
        request_id = trace_id
        first_chunk_ms = None
        stream_metrics: Dict[str, Any] = {}
        try:
            yield f"event: meta\ndata: {json.dumps({'trace_id': trace_id, 'phase': 'started'}, ensure_ascii=False)}\n\n"
            # Resolve user context
            token = get_token_from_cookie(request)
            user = validate_token(token)
            username = user.get("username") if user else ADMIN_USERNAME
            user_info = auth_db.get_user(username) or {}
            master_name = user_info.get("master_name", "Master Pantronux")
            
            session_scope = _resolve_chat_session_id(request)
            
            # Persona restriction
            restricted_persona = user_info.get("restricted_persona")
            if restricted_persona:
                resolved_persona = restricted_persona
            else:
                resolved_persona = memory_manager.normalize_persona(
                    persona or request.query_params.get("persona") or memory_manager.get_active_persona()
                )

            # UI mode router gate — broadcast the UI command and short-
            # circuit the SSE stream when the user's message is purely a
            # mode switch. The frontend receives a normal token stream
            # containing only the acknowledgement.
            user_message = message
            if user_message and not files:
                mode_envelope = await _maybe_handle_ui_mode_command(user_message)
                if mode_envelope and not (mode_envelope.get("cleaned_text") or "").strip():
                    ack = mode_envelope["acknowledgement"]
                    chat_history.add_message(
                        "web", "user", user_message, [],
                        persona=resolved_persona, request_id=request_id,
                        username=username,
                    )
                    chat_history.add_message(
                        "web", "assistant", ack,
                        persona=resolved_persona, request_id=request_id,
                        username=username,
                    )
                    yield (
                        "event: meta\n"
                        f"data: {json.dumps({'ui_command': mode_envelope['command']}, ensure_ascii=False)}\n\n"
                    )
                    yield (
                        "event: chunk\n"
                        f"data: {json.dumps({'text': ack, 'chunk': ack}, ensure_ascii=False)}\n\n"
                    )
                    yield (
                        "event: complete\n"
                        f"data: {json.dumps({'trace_id': trace_id, 'response': ack, 'ui_command': mode_envelope['command']}, ensure_ascii=False)}\n\n"
                    )
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
                    saved_file = await save_upload_file(file)
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
                    )
                    
                    if file.content_type and file.content_type.startswith("image/"):
                        image_paths.append(file_path)
                        # FIX: Store image metadata separately, don't send raw metadata in text chunks
                        file_attachments.append({
                            "type": "image",
                            "original_filename": saved_file["original_filename"],
                            "stored_filename": stored_filename,
                            "path": file_path,
                        })
                        file_contents.append(f"\n--- Gambar Dilampirkan: {saved_file['original_filename']} ---\n(Gambar ini telah diteruskan ke modul Vision Anda untuk dianalisis)")
                    else:
                        read_result = tools.smart_read(file_ref=file_path, instruction="ekstrak konten utama file ini", max_chars=10000)
                        parsed_content = read_result.get("summary") or read_result.get("content")
                        if parsed_content:
                            file_contents.append(f"\n--- File: {saved_file['original_filename']} ---\n{parsed_content}")
                        session_extractions.append({
                            "original_filename": saved_file["original_filename"],
                            "stored_filename": stored_filename,
                            "path": file_path,
                            "extracted_content": (parsed_content or "")[:5000],
                        })
                        file_attachments.append({
                            "type": "file",
                            "original_filename": saved_file["original_filename"],
                            "stored_filename": stored_filename,
                            "path": file_path,
                        })
            
            # Build enhanced message - image paths are passed separately to LangGraph
            # Image metadata is NOT injected into the text message to prevent raw metadata in chunks
            enhanced_message = user_message
            if file_contents:
                enhanced_message += "\n\n[Attached Files Content:]\n" + "\n".join(file_contents)
            att_idx = memory_coordinator.format_same_turn_attachment_index(file_attachments)
            if att_idx:
                enhanced_message += "\n\n" + att_idx
            if image_paths:
                memory_manager.set_runtime_context_value("last_accessed_file", image_paths[-1])
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
                        content=ex.get("extracted_content", "")
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
            )
            
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
            ):
                full_response.append(chunk)
                if first_chunk_ms is None:
                    first_chunk_ms = round((time.perf_counter() - request_started) * 1000, 2)
                # SSE: UI accepts `text` (preferred) or `chunk`; ensure_ascii=False for Indonesian / markdown
                payload = json.dumps({"text": chunk, "chunk": chunk}, ensure_ascii=False)
                yield f"event: chunk\ndata: {payload}\n\n"
            
            # Send completion event
            response_text = "".join(full_response)
            chat_history.add_message(
                "web",
                "assistant",
                response_text,
                persona=resolved_persona,
                request_id=request_id,
                username=username,
            )
            total_ms = round((time.perf_counter() - request_started) * 1000, 2)
            observability.record_latency_metric("chat_stream_total_ms", total_ms)
            if first_chunk_ms is not None:
                observability.record_latency_metric("chat_stream_ttfb_ms", first_chunk_ms)
            if stream_metrics.get("guardrail_input_ms") is not None:
                observability.record_latency_metric("chat_stream_guardrail_input_ms", stream_metrics["guardrail_input_ms"])
            if stream_metrics.get("guardrail_output_ms") is not None:
                observability.record_latency_metric("chat_stream_guardrail_output_ms", stream_metrics["guardrail_output_ms"])
            if stream_metrics.get("graph_collect_ms") is not None:
                observability.record_latency_metric("chat_stream_graph_collect_ms", stream_metrics["graph_collect_ms"])
            if stream_metrics.get("sse_chunk_count") is not None:
                observability.record_latency_metric("chat_stream_sse_chunk_count", stream_metrics["sse_chunk_count"])

            complete_payload = api_success(
                data={"response": response_text},
                trace_id=trace_id,
                response=response_text,  # backward compatibility
                meta={
                    "trace_id": trace_id,
                    "ttfb_ms": first_chunk_ms,
                    "total_ms": total_ms,
                    "timings": stream_metrics,
                },
            )
            yield f"event: complete\ndata: {json.dumps(complete_payload, ensure_ascii=False)}\n\n"
            
        except Exception as e:
            logger.exception(f"Error in streaming endpoint: {e}")
            yield f"event: error\ndata: {json.dumps(api_error(f'Maaf, {master_name} — ' + str(e), trace_id=trace_id), ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )

@app.get("/api/system-status")
async def system_status():
    """Get real-time system status."""
    return api_success(data=tools.get_system_status())



@app.get("/api/log-storage")
async def log_storage():
    """Get log storage usage information."""
    usage = get_log_storage_usage()
    return api_success(data=usage)

@app.get("/api/proxmox-status")
async def proxmox_status():
    """Get Proxmox infrastructure status."""
    return api_success(data=tools.check_proxmox_infrastructure())

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return api_success(data={"health": "healthy", "memory_stats": memory_manager.get_memory_stats()})

@app.get("/api/observability/status")
async def observability_status():
    """Get observability status including Phoenix and OpenTelemetry."""
    return {
        "status": "success",
        "data": {
            "phoenix_running": observability._phoenix_app is not None,
            "opentelemetry_enabled": observability.get_tracer() is not None,
            "dashboard_url": observability._phoenix_app.url if observability._phoenix_app else None,
            "phoenix_port": observability.PHOENIX_PORT,
        }
    }

@app.get("/api/observability/tokens")
async def token_usage(session_id: str = None):
    """Get token usage for sessions."""
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
            }
        }


@app.get("/api/observability/latency")
async def latency_metrics():
    """Get aggregated latency metrics snapshot."""
    return {
        "status": "success",
        "data": observability.get_latency_metrics_snapshot(),
    }

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
async def system_analysis():
    """Full system health analysis from /var/log."""
    return {"status": "success", "data": tools.analyze_system_health()}

@app.post("/api/index-path")
async def index_path(path: str = Form("/home/kuro/projects/")):
    """Index a system path recursively."""
    # Security: only allow whitelisted paths, prevent path traversal
    path = os.path.abspath(path)
    is_whitelisted = any(path.startswith(wp) for wp in tools.WHITELIST_PATHS)
    if not is_whitelisted:
        return {"status": "error", "message": "Path not in whitelist"}
    
    result = tools.index_system_path(path)
    return result

@app.post("/api/memory/reindex")
async def memory_reindex(source: str = Form("uploaded_files")):
    """
    V3.0 CONTEXTUAL RAG RE-INDEXING:
    Clear old ChromaDB and re-index files with contextual enrichment.
    
    source: "uploaded_files" (default) or "all" (includes system paths)
    """
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
                            if ext in ['.txt', '.md', '.py', '.js', '.json', '.log', '.csv', '.yaml', '.yml']:
                                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                                    file_texts[filename] = f.read()[:100000]  # Limit to 100k chars
                        except Exception as e:
                            logger.warning(f"Could not read {filepath}: {e}")
        
        if not file_texts:
            return {
                "status": "error",
                "message": "No files found to re-index",
                "source": source
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
            "elapsed_seconds": round(elapsed, 2)
        }
        
    except Exception as e:
        logger.error(f"Memory re-indexing failed: {e}")
        return {
            "status": "error",
            "message": str(e)
        }

@app.get("/api/memory/stats")
async def memory_stats():
    """V3.0 Enhanced memory statistics."""
    return {
        "status": "success",
        "data": memory_manager.get_memory_stats()
    }

@app.post("/api/compliance/ingest")
async def compliance_ingest(clear: bool = Form(False)):
    return JSONResponse(status_code=410, content={"status": "disabled", "message": "Compliance module purged in KURO V7.2.1"})

@app.get("/api/compliance/stats")
async def compliance_stats():
    return JSONResponse(status_code=410, content={"status": "disabled", "message": "Compliance module purged in KURO V7.2.1"})

@app.get("/api/compliance/search")
async def compliance_search(query: str):
    return JSONResponse(status_code=410, content={"status": "disabled", "message": "Compliance module purged in KURO V7.2.1"})

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
            "search_query": search
        }
    
    briefings = intelligence_db.get_briefings(limit=limit, offset=offset)
    total = intelligence_db.get_total_count()
    
    return {
        "status": "success",
        "briefings": briefings,
        "total": total,
        "has_more": offset + len(briefings) < total
    }

@app.get("/api/intelligence/latest")
async def intelligence_latest():
    """Get the latest intelligence briefing."""
    briefings = intelligence_db.get_briefings(limit=1)
    if briefings:
        return {"status": "success", "briefing": briefings[0]}
    return {"status": "success", "briefing": None, "message": "No briefings available yet"}

@app.get("/api/intelligence/run")
async def intelligence_run():
    """Manually trigger daily intelligence research."""
    try:
        from kuro_backend.intelligence_engine import run_daily_research
        briefing = run_daily_research()
        return {"status": "success", "briefing": briefing}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/intelligence", response_class=HTMLResponse)
async def intelligence_dashboard():
    """Serve the intelligence hub dashboard."""
    return FileResponse(os.path.join(WEB_DIR, "templates", "intelligence.html"))

@app.post("/api/read-file")
async def read_file(file_path: str = Form("")):
    """Read a file using universal parser."""
    if not file_path:
        return {"status": "error", "message": "No file path provided"}
    result = tools.universal_read(file_path)
    return result

@app.get("/api/list-files")
async def list_files(directory: str = None):
    """List all files in a directory (reality check - no memory reliance)."""
    result = tools.list_my_files(directory)
    return {"status": "success", "data": result}

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

# --- Compliance Routes ---
@app.get("/compliance")
async def compliance_dashboard():
    return RedirectResponse(url="/tutorial")

@app.get("/api/compliance/progress/{standard}")
async def compliance_progress(standard: str):
    return JSONResponse(status_code=410, content={"status": "disabled", "message": "Compliance module purged in KURO V7.2.1"})

@app.get("/api/compliance/evidence")
async def compliance_evidence(standard: str = None):
    return JSONResponse(status_code=410, content={"status": "disabled", "message": "Compliance module purged in KURO V7.2.1"})

@app.get("/api/compliance/search")
async def compliance_search(query: str, standard: str = None):
    return JSONResponse(status_code=410, content={"status": "disabled", "message": "Compliance module purged in KURO V7.2.1"})

@app.post("/api/compliance/analyze")
async def compliance_analyze(document: str = Form(""), standard: str = Form("iso27001")):
    return JSONResponse(status_code=410, content={"status": "disabled", "message": "Compliance module purged in KURO V7.2.1"})

@app.get("/api/compliance/audit-trail")
async def audit_trail(limit: int = 50):
    return JSONResponse(status_code=410, content={"status": "disabled", "message": "Compliance module purged in KURO V7.2.1"})


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
                websocket, token_info.get("username"),
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
    username = user.get("username") if user else "Pantronux"
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
        username = user.get("username") if user else "Pantronux"
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
    username = user.get("username") if user else "Pantronux"
    rows = await run_db(finance_db.list_recurring_expenses, True, username)
    out = [RecurringExpenseRecord.model_validate(dict(r)).model_dump(mode="json") for r in rows]
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
        username = user.get("username") if user else "Pantronux"
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
        username = user.get("username") if user else "Pantronux"
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
    username = user.get("username") if user else "Pantronux"
    rows = await run_db(finance_db.get_last_n_days_spend, max(1, min(int(days), 90)), username)
    out = [ApiUsageDailyRecord.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return {"status": "success", "usage": out}


# --- Market Sentinel (Chancellor + OpenClaw cache) ---
@app.get("/api/market/watch")
async def market_list_watch(request: Request):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    username = user.get("username") if user else "Pantronux"
    rows = await run_db(finance_db.list_watched_symbols, True, username)
    out = [WatchedSymbolRecord.model_validate(dict(r)).model_dump(mode="json") for r in rows]
    return {"status": "success", "symbols": out}


@app.post("/api/market/watch")
async def market_add_watch(request: Request, symbol: str = Form(...), label: str = Form("")):
    try:
        token = get_token_from_cookie(request)
        user = validate_token(token)
        username = user.get("username") if user else "Pantronux"
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
        username = user.get("username") if user else "Pantronux"
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
    username = user.get("username") if user else "Pantronux"
    raw = await run_db(finance_db.get_market_hud_items, username)
    items = [MarketHudChip.model_validate(x).model_dump(mode="json") for x in raw]
    return {"status": "success", "items": items}


@app.get("/api/market/brief")
async def market_brief(request: Request):
    token = get_token_from_cookie(request)
    user = validate_token(token)
    username = user.get("username") if user else "Pantronux"
    parts = await run_db(finance_db.get_market_brief_parts, username)
    brief = (parts.get("brief_text") or "").strip()
    if not brief:
        brief = (
            (parts.get("last_sentinel_note") or "").strip()
            or "No market briefing cached yet. The nightly sentinel will populate this."
        )
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
        persona = body.get('persona', 'consultant')
        
        # Enforce restriction
        if restricted_persona and persona != restricted_persona:
            return {"status": "error", "message": f"Unauthorized. Your account is restricted to the {restricted_persona} persona."}
            
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
async def persona_history_stats():
    """Get persona distribution and available backup snapshots."""
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
async def persona_history_preview(limit_turns: int = 30):
    """Preview consultant/advisor turn classification without writing data."""
    try:
        preview = persona_history_admin.preview_reclassify(limit_turns=limit_turns)
        return {"status": "success", "preview": preview}
    except Exception as e:
        logger.exception("persona_history_preview failed: %s", e)
        return {"status": "error", "message": str(e)}


@app.post("/api/persona/history/reclassify")
async def persona_history_reclassify(request: Request):
    """Reclassify consultant/advisor history into separated persona buckets."""
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
    try:
        body = await request.json()
        row_ids = body.get("row_ids", [])
        persona = body.get("persona", "")
        result = persona_history_admin.override_persona(row_ids=row_ids, persona=persona)
        return {"status": "success", "result": result}
    except Exception as e:
        logger.exception("persona_history_override failed: %s", e)
        return {"status": "error", "message": str(e)}


@app.post("/api/persona/history/restore")
async def persona_history_restore(request: Request):
    """Restore persona labels from a selected DB backup snapshot."""
    try:
        body = await request.json()
        backup_file = body.get("backup_file", "")
        result = persona_history_admin.restore_persona_from_backup(backup_file=backup_file)
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
        'interval',
        seconds=30,
        id='hardware_sentinel',
        replace_existing=True
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
        disk = psutil.disk_usage('/')
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
                alert_specs.append((
                    "warning",
                    f"RAM usage {ram_percent}%",
                    (
                        f"Master, Kuro's VM memory utilisation has reached "
                        f"{ram_percent}%. Kindly review the active processes."
                    ),
                    f"hw:ram:{int(ram_percent)//5*5}",
                ))
            if cpu_percent > 85:
                alert_specs.append((
                    "warning",
                    f"CPU usage {cpu_percent}%",
                    (
                        f"Master, Kuro's VM CPU utilisation has reached "
                        f"{cpu_percent}%. An intensive workload has been detected."
                    ),
                    f"hw:cpu:{int(cpu_percent)//5*5}",
                ))
            if disk_percent > 85:
                alert_specs.append((
                    "critical" if disk_percent > 95 else "warning",
                    f"Disk usage {disk_percent}%",
                    (
                        f"Master, disk utilisation has reached {disk_percent}%. "
                        f"Do consider pruning any files that are no longer required."
                    ),
                    f"hw:disk:{int(disk_percent)//5*5}",
                ))

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

def start_reminder_scheduler():
    """Start the background scheduler for automated intelligence cycles."""
    global _reminder_scheduler
    from apscheduler.schedulers.background import BackgroundScheduler
    
    _reminder_scheduler = BackgroundScheduler(daemon=True)
    
    # Daily intelligence briefing at 08:00 AM
    _reminder_scheduler.add_job(
        send_daily_intelligence_briefing,
        'cron',
        hour=8,
        minute=0,
        id='daily_intelligence_briefing',
        replace_existing=True
    )

    # Autonomous memory dreaming cycle (Kuro AI V6.0 Sovereign).
    if os.getenv("KURO_DREAMING_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on"):
        try:
            from kuro_backend import dreaming_worker
            dreaming_cron_hour = int(os.getenv("KURO_DREAMING_CRON_HOUR", "3"))
        except Exception as dreaming_exc:
            logger.warning(f"Dreaming worker hook skipped: {dreaming_exc}")
        else:
            _reminder_scheduler.add_job(
                dreaming_worker.run_dreaming_cycle,
                'cron',
                hour=dreaming_cron_hour,
                minute=0,
                id='kuro_dreaming_cycle',
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                f"Autonomous dreaming cycle scheduled at {dreaming_cron_hour:02d}:00 daily."
            )

    # Fitness anomaly sentinel (Kuro AI V6.0 Sovereign).
    if os.getenv("KURO_FITNESS_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on"):
        try:
            from kuro_backend import fitness_service
            fitness_interval = int(os.getenv("KURO_FITNESS_INTERVAL_MIN", "30"))
        except Exception as fitness_exc:
            logger.warning(f"Fitness sentinel hook skipped: {fitness_exc}")
        else:
            _reminder_scheduler.add_job(
                fitness_service.run_fitness_sentinel,
                'interval',
                minutes=max(5, fitness_interval),
                id='kuro_fitness_sentinel',
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            logger.info(
                f"Fitness anomaly sentinel scheduled every {fitness_interval} minute(s)."
            )

    _reminder_scheduler.start()
    logger.info("Intelligence scheduler started.")


def send_daily_intelligence_briefing():
    """Send daily intelligence briefing to Telegram at 08:00 AM for all users."""
    try:
        from kuro_backend.intelligence_engine import run_daily_research, format_telegram_message
        from kuro_backend import telegram_notifier, memory_manager
        
        # Get all users to process
        all_usernames = auth_db.get_all_users()
        if not all_usernames:
            all_usernames = ["Pantronux"]

        for username in all_usernames:
            try:
                logger.info(f"[INTELLIGENCE] Running daily research for {username} (08:00 AM briefing)...")
                briefing = run_daily_research(username=username)
                
                # Get display name for message
                display_name = username
                try:
                    user_info = auth_db.get_user(username)
                    display_name = user_info.get("master_name", username) if user_info else username
                except:
                    pass

                # Format for Telegram
                telegram_message = format_telegram_message(briefing, display_name=display_name)
                
                # Send to Telegram (Note: telegram_notifier might need user-specific chat_id in future, 
                # but for now it sends to the configured admin bot)
                telegram_notifier.send_message(telegram_message)
                
                logger.info(f"[INTELLIGENCE] Daily briefing sent to Telegram for {username}")
            except Exception as user_exc:
                logger.error(f"[INTELLIGENCE] Failed to send briefing for {username}: {user_exc}")
                
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
                        logger.info(f"Deleted old artifact: {filename} ({file_size / 1024:.1f}KB, {days}+ days old)")
                    except Exception as e:
                        logger.warning(f"Failed to delete {filename}: {e}")
        
        # Clean __pycache__ directories
        for root, dirs, files in os.walk('/home/kuro/projects/kuro'):
            if '__pycache__' in dirs:
                cache_dir = os.path.join(root, '__pycache__')
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
        logger.info(f"Artifact cleanup complete: {deleted_count} files deleted, {deleted_mb:.2f}MB freed")
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
        breakdown = {}
        
        # 1. Scan System Logs (Active)
        if os.path.exists(system_dir):
            for f in os.listdir(system_dir):
                fp = os.path.join(system_dir, f)
                if os.path.isfile(fp) and f.endswith(".log"):
                    size = os.path.getsize(fp)
                    total_size += size
                    log_count += 1
                    breakdown[f] = size / (1024 * 1024)
                    
        # 2. Scan Archive Logs (Rotated)
        if os.path.exists(archive_dir):
            for f in os.listdir(archive_dir):
                fp = os.path.join(archive_dir, f)
                if os.path.isfile(fp):
                    total_size += os.path.getsize(fp)
                    log_count += 1
        
        return {
            "total_size_mb": total_size / (1024 * 1024),
            "log_files": log_count,
            "retention_days": 30,  # Updated policy
            "breakdown": breakdown
        }
    except Exception as e:
        logger.error(f"Failed to calculate log storage: {e}")
        return {"error": str(e), "total_size_mb": 0, "log_files": 0, "retention_days": 30}

def reset_daily_habits():
    """Midnight reset: Cleanup old artifacts."""
    try:
        # Log rotation audit message
        today = datetime.now().strftime('%Y-%m-%d')
        logger.info(f"--- END OF LOG FOR {today} - ROTATING NOW ---")
        
        # Run artifact cleanup
        cleanup_result = cleanup_old_artifacts(days=14)
        logger.info(f"Midnight artifact cleanup: {cleanup_result}")
        
    except Exception as e:
        logger.error(f"Failed to run midnight cleanup: {e}")

# --- Telegram Bot Logic ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="Greetings, Master. Kuro is at your service."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_chat.id) != settings.TELEGRAM_CHAT_ID:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="I apologize, but I am only authorized to serve Pantronux."
        )
        logger.warning(f"Unauthorized access attempt by chat_id: {update.effective_chat.id}")
        return

    message_text = update.message.text
    logger.info(f"Received message from Pantronux: {message_text}")

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        telegram_persona = route_telegram_persona(message_text)
        telegram_request_id = f"telegram_{uuid.uuid4().hex}"
        telegram_trace_id = f"telegram_chat_{uuid.uuid4().hex}"
        chat_history.add_message(
            "telegram",
            "user",
            message_text,
            persona=telegram_persona,
            request_id=telegram_request_id,
        )
        response_text = process_chat_with_graph(
            message_text,
            persona_override=telegram_persona,
            approval_scope=f"telegram:{settings.TELEGRAM_CHAT_ID}:{telegram_persona}",
            trace_id=telegram_trace_id,
            master_name="Pantronux",
            username="Pantronux",
        )
        chat_history.add_message(
            "telegram",
            "assistant",
            response_text,
            persona=telegram_persona,
            request_id=telegram_request_id,
        )

        if len(response_text) > 4096:
            for i in range(0, len(response_text), 4000):
                chunk = response_text[i:i+4000]
                await context.bot.send_message(
                    chat_id=settings.TELEGRAM_CHAT_ID,
                    text=chunk
                )
        else:
            await context.bot.send_message(
                chat_id=settings.TELEGRAM_CHAT_ID,
                text=response_text
            )
    except Exception as e:
        logger.exception(f"Error sending response to Telegram: {e}")
        await context.bot.send_message(
            chat_id=settings.TELEGRAM_CHAT_ID,
            text="My apologies, Master — I encountered an error while delivering the response. Please try once more."
        )


def route_telegram_persona(message_text: str) -> str:
    """
    Telegram hybrid auto-router:
    - tactical for infra/code/security/ops intent
    - chill for daily/social intent
    """
    text = (message_text or "").lower()
    technical_keywords = [
        "proxmox", "server", "docker", "kubernetes", "code", "python", "error", "bug",
        "api", "database", "sql", "log", "linux", "deploy", "security", "iso", "audit",
        "openclaw", "memory", "websocket", "revision", "ci", "cd",
    ]
    casual_keywords = [
        "gym", "musik", "lagu", "hindia", "hsr", "honkai", "capek", "semangat",
        "mood", "curhat", "istirahat", "ngobrol", "santai", "hari ini",
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
    """Runs the Telegram bot with automatic recovery on network failures."""
    max_retries = 5
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            logger.info(f"Starting Telegram bot polling... (Attempt {attempt + 1}/{max_retries})")

            # Create a new event loop for each attempt, as python-telegram-bot closes the loop on exit
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            application = ApplicationBuilder().token(settings.TELEGRAM_TOKEN).build()

            start_handler = CommandHandler('start', start)
            message_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)

            application.add_handler(start_handler)
            application.add_handler(message_handler)
            application.add_error_handler(error_handler)

            application.run_polling(drop_pending_updates=True)

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

        except Exception as e:
            logger.exception(f"Unexpected error in bot polling: {e}")
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
        logger.info(f"Secure Web Dashboard: https://0.0.0.0:8443")
        logger.info(f"Secure Login Page: https://0.0.0.0:8443/login")
        
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8443,
            log_level="info",
            ssl_keyfile=KEY_FILE,
            ssl_certfile=CERT_FILE
        )
    else:
        logger.warning("SSL certificates not found. Running on HTTP only.")
        logger.info(f"Web Dashboard: http://0.0.0.0:8000 (Authentication Required)")
        logger.info(f"Login Page: http://0.0.0.0:8000/login")
        uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")


if __name__ == "__main__":
    try:
        import requests
        import google.genai
    except ImportError as e:
        logger.critical(f"CRITICAL ERROR: Missing essential library - {e}. Please install requirements. Shutting down.")
        sys.exit(1)

    logger.info("Kuro AI Reborn is starting...")
    logger.info(f"Memory stats: {memory_manager.get_memory_stats()}")
    logger.info(f"Web Dashboard: http://0.0.0.0:8000 (Authentication Required)")
    logger.info(f"Login Page: http://0.0.0.0:8000/login")
    logger.info(f"Reminder Dashboard: http://0.0.0.0:8000/reminders")
    logger.info(f"Habits Dashboard: http://0.0.0.0:8000/habits")
    
    # Initialize auth database
    auth_db.init_auth_db()
    logger.info("Auth database initialized for brute force protection")

    def signal_handler(sig, frame):
        logger.info("Received interrupt signal. Shutting down gracefully...")
        if _reminder_scheduler:
            _reminder_scheduler.shutdown()
        if _hardware_sentinel_scheduler:
            _hardware_sentinel_scheduler.shutdown()
        # Shutdown observability
        observability.shutdown_observability()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start reminder scheduler
    start_reminder_scheduler()
    
    # Start hardware sentinel scheduler
    start_hardware_sentinel()
    
    # Initialize observability (Phoenix + OpenTelemetry)
    obs_status = observability.initialize_observability()
    if obs_status["phoenix"]:
        logger.info(f"[OBSERVABILITY] Phoenix dashboard available at: {obs_status['dashboard_url']}")
        logger.info(f"[OBSERVABILITY] Auth: DISABLED (local private network)")
        logger.info(f"[OBSERVABILITY] Project: Kuro-AI-Audit")
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
    logger.info("Starting Telegram bot in main thread...")
    run_bot_with_recovery()

    logger.info("Kuro AI Reborn has shut down.")
