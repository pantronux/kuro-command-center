"""
Kuro AI V4.8 - Observability with Arize Phoenix & OpenTelemetry
================================================================================
Black Box System for Tracing, Guardrails Validation, and Performance Monitoring
Port 6006 - Phoenix Dashboard with Simple Auth
"""
import logging
import os
import uuid
import threading
import time
from typing import Optional, Dict, Any
from datetime import datetime
from contextlib import contextmanager

# OpenTelemetry imports
from opentelemetry import trace, context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Status, StatusCode

# Phoenix imports
import phoenix as px

logger = logging.getLogger(__name__)

# ============================================
# CONFIGURATION
# ============================================

PHOENIX_PORT = 6006
PHOENIX_HOST = "0.0.0.0"
PHOENIX_AUTH_USERNAME = os.getenv("PHOENIX_USERNAME", "pantronux")
PHOENIX_AUTH_PASSWORD = os.getenv("PHOENIX_PASSWORD", "Noobcry17!")

OTLP_ENDPOINT = os.getenv("OTLP_ENDPOINT", "http://localhost:6006/v1/traces")

MASTER_USER_ID = "master_irfan"
TOKEN_ALERT_THRESHOLD = 5000

# Global state
_phoenix_session = None
_tracer = None
_token_tracker = {}
_phoenix_app = None

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
        
        # Launch Phoenix with minimal config
        _phoenix_app = px.launch_app(
            port=PHOENIX_PORT,
            host=PHOENIX_HOST,
            run_in_thread=True,
        )
        
        # Wait for server to be ready
        import time
        time.sleep(2)
        
        dashboard_url = f"http://localhost:{PHOENIX_PORT}"
        logger.info(f"[OBSERVABILITY] Phoenix dashboard available at: {dashboard_url}")
        logger.info(f"[OBSERVABILITY] Auth: username={PHOENIX_AUTH_USERNAME}")
        
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
        # Create resource with service info
        resource = Resource.create({
            "service.name": "kuro-ai",
            "service.version": "4.8",
            "deployment.environment": "production",
        })
        
        # Create tracer provider
        tracer_provider = TracerProvider(resource=resource)
        
        # Add OTLP exporter (points to Phoenix)
        otlp_exporter = OTLPSpanExporter(
            endpoint=OTLP_ENDPOINT,
            insecure=True,
        )
        span_processor = BatchSpanProcessor(otlp_exporter)
        tracer_provider.add_span_processor(span_processor)
        
        # Also add console exporter for debugging (optional)
        # console_exporter = ConsoleSpanExporter()
        # tracer_provider.add_span_processor(BatchSpanProcessor(console_exporter))
        
        # Set as global provider
        trace.set_tracer_provider(tracer_provider)
        
        # Get tracer
        _tracer = trace.get_tracer("kuro-ai")
        
        logger.info("[OBSERVABILITY] OpenTelemetry initialized with Phoenix exporter")
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
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise
        finally:
            # Record duration
            duration = time.time() - start_time
            span.set_attribute(f"{node_name}.duration_ms", round(duration * 1000, 2))


# ============================================
# GUARDRAILS TRACKING
# ============================================

def log_guardrails_validation(
    guardrail_type: str,
    is_valid: bool,
    original_response: str = None,
    corrected_response: str = None,
    failures: list = None,
    reask_count: int = 0,
    session_id: str = None,
):
    """
    Log guardrails validation results with re-ask tracking.
    Records both the original (failed) and corrected responses.
    """
    tracer = get_tracer()
    
    if tracer is None:
        return
    
    attributes = {
        "guardrail.type": guardrail_type,
        "guardrail.is_valid": is_valid,
        "guardrail.reask_count": reask_count,
        "guardrail.session_id": session_id or "unknown",
    }
    
    if failures:
        for i, failure in enumerate(failures):
            attributes[f"guardrail.failure.{i}.rule"] = getattr(failure, 'rule_violated', 'unknown')
            attributes[f"guardrail.failure.{i}.severity"] = getattr(failure, 'severity', 'unknown')
            attributes[f"guardrail.failure.{i}.detail"] = str(getattr(failure, 'detail', ''))
    
    with tracer.start_as_current_span(f"kuro.guardrails.{guardrail_type}") as span:
        for key, value in attributes.items():
            span.set_attribute(key, str(value))
        
        # Log original vs corrected response
        if original_response:
            span.set_attribute("guardrail.original_response", original_response[:1000])
        
        if corrected_response:
            span.set_attribute("guardrail.corrected_response", corrected_response[:1000])
        
        if not is_valid:
            span.set_status(Status(StatusCode.ERROR, f"Guardrail validation failed: {guardrail_type}"))
        else:
            span.set_status(Status(StatusCode.OK))
    
    logger.info(
        f"[GUARDRAILS] {guardrail_type}: valid={is_valid}, reasks={reask_count}, "
        f"failures={len(failures) if failures else 0}"
    )


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
    
    # Check threshold
    if _token_tracker[session_id]["total_tokens"] > TOKEN_ALERT_THRESHOLD:
        logger.warning(
            f"[TOKEN ALERT] Session {session_id} exceeded threshold: "
            f"{_token_tracker[session_id]['total_tokens']} tokens used "
            f"(threshold: {TOKEN_ALERT_THRESHOLD})"
        )
        
        # Log to tracer
        tracer = get_tracer()
        if tracer:
            with tracer.start_as_current_span("kuro.token_alert") as span:
                span.set_attribute("session_id", session_id)
                span.set_attribute("total_tokens", _token_tracker[session_id]["total_tokens"])
                span.set_attribute("threshold", TOKEN_ALERT_THRESHOLD)
                span.set_status(Status(StatusCode.WARNING, "Token threshold exceeded"))
    
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
    
    logger.info(f"[OBSERVABILITY] Initialization complete: {status}")
    return status


def shutdown_observability():
    """Shutdown all observability components."""
    stop_phoenix_server()
    logger.info("[OBSERVABILITY] Shutdown complete")
