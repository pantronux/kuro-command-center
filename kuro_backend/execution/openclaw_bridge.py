"""
OpenClaw bridge client for external execution handover.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import uuid
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)
logger.propagate = False

DEFAULT_OPENCLAW_BASE_URL = "http://localhost:8000"
DEFAULT_OPENCLAW_EXECUTE_PATH = "/execute"
DEFAULT_OPENCLAW_TIMEOUT_SECONDS = 45.0
OPENCLAW_CIRCUIT_BREAKER_THRESHOLD = 3
OPENCLAW_UNAVAILABLE_FEEDBACK = (
    "Maaf Master, otot eksekusi (OpenClaw) sedang tidak tersedia. "
    "Saya akan tetap mencatat instruksi ini di memori sementara."
)
_circuit_breaker_lock = threading.Lock()
_consecutive_unavailable_failures = 0
_circuit_open = False
_DANGEROUS_COMMAND_KEYWORDS = (
    "shutdown",
    "poweroff",
    "reboot",
    "halt",
    "init 0",
    "rm -rf /",
)


def is_command_safe(command: Optional[str]) -> bool:
    """Return False when command contains blocked destructive keywords."""
    if not isinstance(command, str):
        return True
    normalized = " ".join(command.lower().split())
    return not any(keyword in normalized for keyword in _DANGEROUS_COMMAND_KEYWORDS)


def _extract_command_for_safety_check(params: Dict[str, Any]) -> Optional[str]:
    """Best-effort extraction of command text from OpenClaw payload params."""
    for key in ("command", "cmd", "shell_command", "task_description", "task"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _record_availability_failure() -> int:
    global _consecutive_unavailable_failures, _circuit_open
    with _circuit_breaker_lock:
        _consecutive_unavailable_failures += 1
        if _consecutive_unavailable_failures >= OPENCLAW_CIRCUIT_BREAKER_THRESHOLD:
            _circuit_open = True
        return _consecutive_unavailable_failures


def _reset_circuit_breaker() -> None:
    global _consecutive_unavailable_failures, _circuit_open
    with _circuit_breaker_lock:
        _consecutive_unavailable_failures = 0
        _circuit_open = False


def _is_circuit_open() -> bool:
    with _circuit_breaker_lock:
        return _circuit_open


def _build_circuit_open_response(request_id: str, raw_error: Optional[str] = None) -> Dict[str, Any]:
    return {
        "success": False,
        "error": OPENCLAW_UNAVAILABLE_FEEDBACK,
        "status_code": None,
        "request_id": request_id,
        "raw_response": None,
        "memory_fallback_required": True,
        "circuit_breaker": {
            "open": True,
            "threshold": OPENCLAW_CIRCUIT_BREAKER_THRESHOLD,
            "reason": raw_error or "openclaw_unavailable",
        },
    }


class OpenClawBridgeClient:
    """Lightweight HTTP client for OpenClaw daemon API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        execute_path: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        raw_base_url = base_url or os.getenv("OPENCLAW_BASE_URL", DEFAULT_OPENCLAW_BASE_URL)
        raw_execute_path = execute_path or os.getenv(
            "OPENCLAW_EXECUTE_PATH", DEFAULT_OPENCLAW_EXECUTE_PATH
        )
        raw_timeout = timeout_seconds or float(
            os.getenv("OPENCLAW_TIMEOUT_SECONDS", str(DEFAULT_OPENCLAW_TIMEOUT_SECONDS))
        )

        self.base_url = raw_base_url.rstrip("/")
        self.execute_path = raw_execute_path if raw_execute_path.startswith("/") else f"/{raw_execute_path}"
        self.timeout_seconds = raw_timeout

    @property
    def execute_url(self) -> str:
        return f"{self.base_url}{self.execute_path}"

    async def execute_skill(self, skill_name: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute an OpenClaw skill through daemon HTTP endpoint."""
        return await execute_openclaw_skill(skill_name, params or {}, client=self)


async def execute_openclaw_skill(
    skill_name: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    client: Optional[OpenClawBridgeClient] = None,
) -> Dict[str, Any]:
    """
    Async handover to OpenClaw daemon.

    Returns a normalized payload to simplify usage from tool callers.
    """
    if not skill_name or not skill_name.strip():
        return {
            "success": False,
            "error": "OpenClaw skill_name is required.",
            "status_code": None,
            "request_id": None,
            "raw_response": None,
        }

    bridge = client or OpenClawBridgeClient()
    request_id = str(uuid.uuid4())
    normalized_params = params if isinstance(params, dict) else {"payload": params}
    command_candidate = _extract_command_for_safety_check(normalized_params)

    if _is_circuit_open():
        logger.warning("[OPENCLAW] Circuit open; skipping request request_id=%s", request_id)
        return _build_circuit_open_response(request_id, raw_error="circuit_open")

    if command_candidate is not None:
        # Keep exact model-sent command for incident/audit traces.
        logger.info("[OPENCLAW] Gemini command request_id=%s command=%r", request_id, command_candidate)
        if not is_command_safe(command_candidate):
            logger.warning(
                "[OPENCLAW] Blocked destructive command request_id=%s command=%r",
                request_id,
                command_candidate,
            )
            return {
                "success": False,
                "error": "Eksekusi ditolak: Perintah ini berisiko mematikan sistem Master.",
                "status_code": None,
                "request_id": request_id,
                "raw_response": None,
            }

    payload = {
        "skill_name": skill_name.strip(),
        "params": normalized_params,
        "request_id": request_id,
        "source": "kuro_openclaw_bridge",
    }

    def _post() -> Dict[str, Any]:
        response = requests.post(
            bridge.execute_url,
            json=payload,
            timeout=bridge.timeout_seconds,
        )
        parsed_body: Any
        try:
            parsed_body = response.json()
        except ValueError:
            parsed_body = {"text": response.text}

        return {
            "status_code": response.status_code,
            "ok": response.ok,
            "body": parsed_body,
        }

    try:
        result = await asyncio.to_thread(_post)
    except requests.Timeout:
        failures = _record_availability_failure()
        logger.warning(
            "[OPENCLAW] Timeout request_id=%s endpoint=%s failures=%s",
            request_id,
            bridge.execute_url,
            failures,
        )
        if failures >= OPENCLAW_CIRCUIT_BREAKER_THRESHOLD:
            return _build_circuit_open_response(
                request_id,
                raw_error=f"timeout_after_{bridge.timeout_seconds:.1f}s",
            )
        return {
            "success": False,
            "error": f"OpenClaw daemon timeout after {bridge.timeout_seconds:.1f}s.",
            "status_code": None,
            "request_id": request_id,
            "raw_response": None,
            "memory_fallback_required": False,
            "circuit_breaker": {
                "open": False,
                "failures": failures,
                "threshold": OPENCLAW_CIRCUIT_BREAKER_THRESHOLD,
            },
        }
    except requests.ConnectionError as exc:
        failures = _record_availability_failure()
        logger.error("[OPENCLAW] Connection failed request_id=%s failures=%s error=%s", request_id, failures, exc)
        if failures >= OPENCLAW_CIRCUIT_BREAKER_THRESHOLD:
            return _build_circuit_open_response(request_id, raw_error=f"connection_error:{exc}")
        return {
            "success": False,
            "error": f"OpenClaw connection failed: {exc}",
            "status_code": None,
            "request_id": request_id,
            "raw_response": None,
            "memory_fallback_required": False,
            "circuit_breaker": {
                "open": False,
                "failures": failures,
                "threshold": OPENCLAW_CIRCUIT_BREAKER_THRESHOLD,
            },
        }
    except requests.RequestException as exc:
        logger.error("[OPENCLAW] Request failed request_id=%s error=%s", request_id, exc)
        return {
            "success": False,
            "error": f"OpenClaw request failed: {exc}",
            "status_code": None,
            "request_id": request_id,
            "raw_response": None,
        }
    except Exception as exc:
        logger.exception("[OPENCLAW] Unexpected error request_id=%s", request_id)
        return {
            "success": False,
            "error": f"Unexpected OpenClaw bridge error: {exc}",
            "status_code": None,
            "request_id": request_id,
            "raw_response": None,
        }

    body = result.get("body")
    status_code = result.get("status_code")
    ok = bool(result.get("ok"))

    if not ok:
        return {
            "success": False,
            "error": f"OpenClaw returned HTTP {status_code}",
            "status_code": status_code,
            "request_id": request_id,
            "raw_response": body,
        }

    _reset_circuit_breaker()
    return {
        "success": True,
        "status_code": status_code,
        "request_id": request_id,
        "result": body,
        "raw_response": body,
    }
