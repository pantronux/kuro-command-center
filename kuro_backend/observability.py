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
import uuid
import threading
import time
from typing import Optional, Dict, Any
from datetime import date, datetime
from contextlib import contextmanager

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
os.environ["PHOENIX_SQL_DATABASE_URL"] = f"sqlite:///{_PHOENIX_DB_PATH}"
os.environ["PHOENIX_ENABLE_AUTH"] = "false"  # Disable auth for local private network
os.environ["PHOENIX_PROJECT_NAME"] = "Kuro-AI-Audit"  # Force project identity

# OpenTelemetry imports
from opentelemetry import trace, context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Status, StatusCode

# Phoenix imports (after PHOENIX_SQL_DATABASE_URL is set)
import phoenix as px

logger = logging.getLogger(__name__)
logger.propagate = False  # Prevent double-reporting to root logger

# ============================================
# CONFIGURATION
# ============================================

PHOENIX_PORT = 6006
PHOENIX_HOST = "0.0.0.0"
PHOENIX_ENABLE_AUTH = False  # Auth disabled for local private network

# Phoenix OTLP HTTP endpoint (Phoenix UI port 6006 also serves OTLP on /v1/traces)
OTLP_ENDPOINT = os.getenv("OTLP_ENDPOINT", "http://127.0.0.1:6006/v1/traces")

# Expose DB path for logging
PHOENIX_DB_PATH = _PHOENIX_DB_PATH

MASTER_USER_ID = "master_irfan"
TOKEN_ALERT_THRESHOLD = 999999999  # Disabled - no alerting in production

# Global state
_phoenix_session = None
_tracer = None
_token_tracker = {}
_phoenix_app = None
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
        logger.info(f"[OBSERVABILITY] Database path: {PHOENIX_DB_PATH}")
        
        # Launch Phoenix with OTLP receiver enabled for trace ingestion
        # PHOENIX_SQL_DATABASE_URL is already set at module level
        # use_temp_dir=False ensures Phoenix uses the configured database path
        _phoenix_app = px.launch_app(
            port=PHOENIX_PORT,
            host=PHOENIX_HOST,
            run_in_thread=True,
            use_temp_dir=False,
        )
        
        # Wait for server to be ready
        import time
        time.sleep(2)
        
        dashboard_url = f"http://localhost:{PHOENIX_PORT}"
        logger.info(f"[OBSERVABILITY] Phoenix dashboard available at: {dashboard_url}")
        logger.info(f"[OBSERVABILITY] Auth: DISABLED (local private network)")
        logger.info(f"[OBSERVABILITY] Project name: Kuro-AI-Audit")
        
        return dashboard_url
        
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

def setup_opentelemetry() -> Optional[trace.Tracer]:
    """
    Setup OpenTelemetry with Phoenix as the OTLP endpoint.
    Returns the tracer instance.
    """
    global _tracer
    
    try:
        # Import propagators for proper trace context propagation
        from opentelemetry.propagate import set_global_textmap
        from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
        
        # Set global propagator for trace context (W3C standard)
        set_global_textmap(TraceContextTextMapPropagator())
        
        # Create resource with service info - SPECIFIC PROJECT NAME for Phoenix
        resource = Resource.create({
            "service.name": "Kuro-AI-Audit",
            "service.version": "5.5",
            "deployment.environment": "production",
        })
        
        # Create tracer provider
        tracer_provider = TracerProvider(resource=resource)
        
        # Add OTLP exporter (points to Phoenix HTTP endpoint)
        otlp_exporter = OTLPSpanExporter(
            endpoint=OTLP_ENDPOINT,
            timeout=10,  # 10 second timeout
        )
        span_processor = BatchSpanProcessor(
            otlp_exporter,
            schedule_delay_millis=1000,  # Export every second
            max_export_batch_size=10,
        )
        tracer_provider.add_span_processor(span_processor)
        
        # Set as global provider
        trace.set_tracer_provider(tracer_provider)
        
        # Get tracer
        _tracer = trace.get_tracer("kuro-ai")
        
        logger.info("[OBSERVABILITY] OpenTelemetry initialized with Phoenix exporter")
        logger.info("[OBSERVABILITY] Global propagator: TraceContextTextMapPropagator (W3C)")
        return _tracer
        
    except Exception as e:
        logger.error(f"[OBSERVABILITY] Failed to setup OpenTelemetry: {e}")
        return None


def get_tracer() -> Optional[trace.Tracer]:
    """Get the global tracer instance."""
    return _tracer


# ============================================
# TRACE CONTEXT MANAGEMENT
# ============================================

def create_session_context(user_id: str = MASTER_USER_ID, session_id: str = None) -> Dict[str, str]:
    """
    Create a trace context with user_id, session_id, and thread_id.
    Returns context attributes for enrichment.
    """
    if session_id is None:
        session_id = str(uuid.uuid4())
    
    thread_id = str(threading.current_thread().ident)
    
    return {
        "user_id": user_id,
        "session_id": session_id,
        "thread_id": thread_id,
        "timestamp": datetime.now().isoformat(),
    }


@contextmanager
def trace_node(node_name: str, attributes: Dict[str, str] = None):
    """
    Context manager for tracing LangGraph node execution.
    Records duration, input/output, and status.
    
    Usage:
        with trace_node("supervisor_node", {"user_id": "master_irfan"}) as span:
            # node logic
            span.set_attribute("output.next_step", "compliance_node")
    """
    tracer = get_tracer()
    
    if tracer is None:
        # No tracer, just yield empty context
        yield None
        return
    
    with tracer.start_as_current_span(f"kuro.{node_name}") as span:
        # Add default attributes
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, str(value))
        
        # Record start time
        start_time = time.time()
        
        try:
            yield span
            # FIX: Set OK status explicitly so Phoenix shows green
            span.set_status(Status(StatusCode.OK, f"Node {node_name} completed successfully"))
        except Exception as e:
            # FIX: Set ERROR status so Phoenix shows red
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise
        finally:
            # Record duration
            duration = time.time() - start_time
            span.set_attribute(f"{node_name}.duration_ms", round(duration * 1000, 2))


# V5.5: Guardrails tracking removed. Environment is trusted (Local + VPN + Auth).
# ============================================
# TOKEN USAGE MONITORING
# ============================================

def track_token_usage(session_id: str, prompt_tokens: int, completion_tokens: int, total_tokens: int):
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
