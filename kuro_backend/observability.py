"""
Kuro AI V6.0 Sovereign - Observability with Arize Phoenix & OpenTelemetry
================================================================================
Black Box System for Tracing, Guardrails Validation, and Performance Monitoring
Port 6006 - Phoenix Dashboard with Simple Auth

--- Header Doc ---
Purpose: OpenTelemetry tracing + Phoenix integration + token/cost accounting.
Caller: main.py startup, langgraph_core nodes, core.py, tools (via @traced), dreaming_worker.
Dependencies: arize-phoenix, opentelemetry, google-genai usage metadata, kuro_backend.pricing, finance_db.
Main Functions: init_observability(), traced(), track_token_usage(), log_event().
Side Effects: Spins up Phoenix OTel collector threads, writes to phoenix sqlite, persists daily api_usage via finance_db.
"""
import logging
import os
import time
import threading
import json
import uuid
from datetime import datetime, date
from contextlib import contextmanager
from typing import Any, Dict, Optional, Generator

# ============================================
# PHOENIX PERSISTENT DATABASE CONFIGURATION
# MUST be set BEFORE importing phoenix module
# ============================================
_PHOENIX_DB_PATH = os.getenv(
    "PHOENIX_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "phoenix_data", "phoenix.db")
)
# Ensure directory exists before Phoenix reads the env var
os.makedirs(os.path.dirname(_PHOENIX_DB_PATH), exist_ok=True)

# Set environment variables for Phoenix (must be before import)
# VM configuration note: phoenix_data/ must be on a persistent volume in the VM (not tmpfs/RAM disk).
# OpenTelemetry imports
from opentelemetry import trace, context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Status, StatusCode

# App Configuration
from kuro_backend.config import settings
from kuro_backend import finance_db

# Ensure Phoenix persistence directories and environment are primed before launch
_PHOENIX_DIR = os.path.abspath(settings.PHOENIX_WORKING_DIR)
os.environ["PHOENIX_WORKING_DIR"] = _PHOENIX_DIR
if settings.PHOENIX_SQL_DATABASE_URL:
    os.environ["PHOENIX_SQL_DATABASE_URL"] = settings.PHOENIX_SQL_DATABASE_URL

# Phoenix imports (after PHOENIX_SQL_DATABASE_URL is set)
import phoenix as px

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

# ============================================
# CONFIGURATION
# ============================================

PHOENIX_PORT = 6006
PHOENIX_HOST = "0.0.0.0"

# Global state
_tracer = None
_token_tracker = {}
_phoenix_app = None

MASTER_USER_ID = "Pantronux"

def create_session_context(user_id: str = MASTER_USER_ID, session_id: str = None) -> Dict[str, Any]:
    """
    Create a trace context with user_id, session_id, and thread_id.
    Returns context attributes for enrichment.
    """
    if session_id is None:
        session_id = str(uuid.uuid4())
    
    thread_id = str(threading.current_thread().ident)
    
    return {
        "kuro.username": user_id,
        "kuro.session_id": session_id,
        "kuro.thread_id": thread_id,
        "kuro.timestamp": datetime.now().isoformat(),
    }
_latency_metrics: Dict[str, Dict[str, float]] = {}

# ============================================
# PHOENIX SERVER INITIALIZATION
# ============================================

def start_phoenix_server() -> Optional[str]:
    """
    Start Phoenix as a background server on port 6006.
    Returns the dashboard URL if successful.
    """
    global _phoenix_app
    
    try:
        # Check if Phoenix is already running
        if _phoenix_app is not None:
            logger.info("[OBSERVABILITY] Phoenix server already running")
            return f"http://localhost:{PHOENIX_PORT}"
        
        logger.info(f"[OBSERVABILITY] Starting Phoenix server on port {PHOENIX_PORT}...")
        
        # Launch Phoenix with OTLP receiver enabled for trace ingestion
        px_session = px.launch_app(
            port=PHOENIX_PORT,
            host=PHOENIX_HOST,
            run_in_thread=True,
            use_temp_dir=False,
        )
        _phoenix_app = px_session
        
        # Wait for server to be ready
        time.sleep(2)
        
        logger.info(f"Arize Phoenix dashboard: {px_session.url}")
        if settings.PHOENIX_SQL_DATABASE_URL:
            logger.info(f"Phoenix Persist Mode: SQL ({settings.PHOENIX_SQL_DATABASE_URL})")
        else:
            logger.info(f"Phoenix Persist Mode: LOCAL ({_PHOENIX_DIR})")
        
        return px_session.url
        
    except Exception as e:
        logger.error(f"[OBSERVABILITY] Failed to start Phoenix server: {e}")
        return None


def stop_phoenix_server():
    """Stop the Phoenix server gracefully."""
    global _phoenix_app
    
    if _phoenix_app is not None:
        try:
            _phoenix_app.stop()
            _phoenix_app = None
            logger.info("[OBSERVABILITY] Phoenix server stopped")
        except Exception as e:
            logger.error(f"[OBSERVABILITY] Error stopping Phoenix: {e}")


# ============================================
# OPENTELEMETRY SETUP
# ============================================

def setup_opentelemetry():
    """Bootstrap OpenTelemetry with Phoenix-compatible resource attributes."""
    global _tracer
    try:
        # Use semantic conventions for project naming
        resource = Resource(
            attributes={
                "project_name": "kuro-ai",
                "service.name": "kuro-backend",
            }
        )
        
        provider = TracerProvider(resource=resource)
        
        # Phoenix local OTLP collector endpoint (default)
        exporter = OTLPSpanExporter(endpoint="http://localhost:6006/v1/traces")
        
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        
        _tracer = trace.get_tracer("kuro-ai")
        logger.info("OpenTelemetry bootstrap complete (Project: kuro-ai)")
        return _tracer
    except Exception as e:
        logger.error(f"Failed to setup OpenTelemetry: {e}")
        return None


def get_tracer() -> Optional[trace.Tracer]:
    """Get the global tracer instance."""
    return _tracer


# ============================================
# TRACE CONTEXT MANAGEMENT
# ============================================

@contextmanager
def trace_node(node_name: str, attributes: Optional[Dict[str, Any]] = None) -> Generator[trace.Span, None, None]:
    """
    Context manager for tracing a reasoning node with a safety timeout.
    Ensures spans are closed and exceptions are recorded correctly.
    """
    tracer = get_tracer()
    if tracer is None:
        yield None
        return

    attrs = attributes or {}
    
    # Standardize Kuro attributes for Phoenix filtering
    span_attrs = {
        "kuro.node_name": node_name,
        "kuro.persona": attrs.get("persona", attrs.get("kuro.persona", "unknown")),
        "kuro.username": attrs.get("username", attrs.get("kuro.username", "unknown")),
        "kuro.chat_id": attrs.get("chat_id", attrs.get("kuro.chat_id", "")),
    }
    # Include all other attributes
    for k, v in attrs.items():
        if k not in span_attrs:
            span_attrs[k] = str(v)

    with tracer.start_as_current_span(node_name, attributes=span_attrs) as span:
        start_time = time.time()
        
        # SAFETY: Set a timer to ensure the span is closed if the logic hangs indefinitely.
        timeout_s = settings.KURO_TRACE_SPAN_TIMEOUT_S
        timer = threading.Timer(timeout_s, lambda: span.end() if span.is_recording() else None)
        timer.start()
        
        try:
            yield span
        except Exception as e:
            # FIX: Set ERROR status so Phoenix shows red immediately
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            logger.error(f"Error in traced node {node_name}: {e}")
            raise
        finally:
            timer.cancel()
            latency = (time.time() - start_time) * 1000
            span.set_attribute("latency_ms", latency)
            record_latency_metric(node_name, latency)


# ============================================
# TOKEN USAGE MONITORING
# ============================================

def track_token_usage(session_id: str, prompt_tokens: int, completion_tokens: int, total_tokens: int, username: str = "Pantronux"):
    """
    Track token usage per session and alert if threshold exceeded.
    """
    global _token_tracker
    
    if session_id not in _token_tracker:
        _token_tracker[session_id] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "start_time": datetime.now().isoformat(),
        }
    
    _token_tracker[session_id]["prompt_tokens"] += prompt_tokens
    _token_tracker[session_id]["completion_tokens"] += completion_tokens
    _token_tracker[session_id]["total_tokens"] += total_tokens

    # Chancellor / finances: persist daily API cost rollup (best-effort).
    if os.getenv("KURO_FINANCE_TRACKING_ENABLED", "true").strip().lower() in (
        "1", "true", "yes", "on",
    ):
        try:
            from kuro_backend import finance_db, pricing
            from kuro_backend.config import PRIMARY_MODEL

            model = os.getenv("MODEL_NAME", PRIMARY_MODEL)
            cost = pricing.estimate_cost_usd(
                model, prompt_tokens, completion_tokens,
            )
            finance_db.add_api_usage(
                date.today().isoformat(),
                model,
                prompt_tokens,
                completion_tokens,
                cost,
                username,
            )
        except Exception as exc:
            logger.debug("[OBS] api_usage rollup skipped: %s", exc)
    
    # V5.5: Token threshold alert disabled. Only tracking for observability.
    return _token_tracker[session_id]


def get_session_token_usage(session_id: str) -> Dict[str, Any]:
    """Get token usage for a specific session."""
    return _token_tracker.get(session_id, {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "start_time": None,
    })


def cleanup_old_sessions(max_age_hours: int = 24):
    """Clean up session token tracking older than max_age_hours."""
    global _token_tracker
    
    cutoff = datetime.now()
    from datetime import timedelta
    cutoff = cutoff - timedelta(hours=max_age_hours)
    
    sessions_to_remove = []
    for session_id, data in _token_tracker.items():
        if data.get("start_time"):
            start_time = datetime.fromisoformat(data["start_time"])
            if start_time < cutoff:
                sessions_to_remove.append(session_id)
    
    for session_id in sessions_to_remove:
        del _token_tracker[session_id]
    
    if sessions_to_remove:
        logger.info(f"[OBSERVABILITY] Cleaned up {len(sessions_to_remove)} old sessions")


def record_latency_metric(metric_name: str, value_ms: float):
    """
    Record lightweight in-memory latency metric aggregates.
    Useful for quick operational checks without external TSDB.
    """
    try:
        key = str(metric_name or "").strip()
        if not key:
            return
        value = float(value_ms)
    except (TypeError, ValueError):
        return

    bucket = _latency_metrics.get(key)
    if bucket is None:
        bucket = {
            "count": 0.0,
            "sum_ms": 0.0,
            "min_ms": value,
            "max_ms": value,
            "last_ms": value,
        }
        _latency_metrics[key] = bucket

    bucket["count"] += 1.0
    bucket["sum_ms"] += value
    bucket["last_ms"] = value
    if value < bucket["min_ms"]:
        bucket["min_ms"] = value
    if value > bucket["max_ms"]:
        bucket["max_ms"] = value


def get_latency_metrics_snapshot() -> Dict[str, Dict[str, float]]:
    """Return aggregated latency metrics with average."""
    snapshot: Dict[str, Dict[str, float]] = {}
    for name, bucket in _latency_metrics.items():
        count = max(1.0, float(bucket.get("count", 0.0)))
        avg = float(bucket.get("sum_ms", 0.0)) / count
        snapshot[name] = {
            "count": float(bucket.get("count", 0.0)),
            "avg_ms": round(avg, 2),
            "min_ms": round(float(bucket.get("min_ms", 0.0)), 2),
            "max_ms": round(float(bucket.get("max_ms", 0.0)), 2),
            "last_ms": round(float(bucket.get("last_ms", 0.0)), 2),
        }
    return snapshot


# ============================================
# CLIENT DATA TRACKING
# ============================================

def is_client_query(query: str) -> bool:
    """
    Detect if query is related to client data for special labeling.
    """
    client_keywords = [
        "klien", "client", "medco", "audit", "compliance",
        "iso", "isms", "sertifikasi", "sertifikasi",
    ]
    query_lower = query.lower()
    return any(keyword in query_lower for keyword in client_keywords)


def add_client_label(attributes: Dict[str, str], query: str) -> Dict[str, str]:
    """
    Add client data label to trace attributes if applicable.
    """
    if is_client_query(query):
        attributes["data_classification"] = "client_data"
        attributes["requires_audit"] = "true"
    return attributes


# ============================================
# INITIALIZATION
# ============================================

def initialize_observability() -> Dict[str, Any]:
    """
    Initialize all observability components.
    Returns status dict.
    """
    status = {
        "phoenix": False,
        "opentelemetry": False,
        "dashboard_url": None,
    }
    
    # Start Phoenix
    dashboard_url = start_phoenix_server()
    if dashboard_url:
        status["phoenix"] = True
        status["dashboard_url"] = dashboard_url
    
    # Setup OpenTelemetry
    tracer = setup_opentelemetry()
    if tracer:
        status["opentelemetry"] = True
    
    # Initialize LangChain Instrumentor for LangGraph tracing
    try:
        from langchain_core.callbacks import BaseCallbackHandler
        from opentelemetry.instrumentation.langchain import LangchainInstrumentor
        
        LangchainInstrumentor().instrument()
        logger.info("[OBSERVABILITY] LangChain instrumentor initialized")
    except Exception as e:
        logger.warning(f"[OBSERVABILITY] Failed to initialize LangChain instrumentor: {e}")
    
    logger.info(f"[OBSERVABILITY] Initialization complete: {status}")
    return status


def shutdown_observability():
    """Shutdown all observability components."""
    # Force flush all pending spans before shutdown
    tracer_provider = trace.get_tracer_provider()
    if hasattr(tracer_provider, 'force_flush'):
        tracer_provider.force_flush(timeout_millis=5000)
        logger.info("[OBSERVABILITY] Forced flush of pending spans")
    
    stop_phoenix_server()
    logger.info("[OBSERVABILITY] Shutdown complete")
