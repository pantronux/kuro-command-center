"""
Kuro AI V6.0 Sovereign — OpenClaw bridge client for external execution handover.

--- Header Doc ---
Purpose: HTTP client + circuit breaker to the OpenClaw external execution daemon.
Caller: tools/base_tools (advanced_execution_tool, market tools), execution/service, dreaming_worker market + prediction scans.
Dependencies: requests, stdlib threading/time/asyncio.
Main Functions: call_skill(name, payload), healthcheck(), _circuit_state(), _should_trip().
Side Effects: Outbound HTTPS/HTTP to OpenClaw host, background state for circuit breaker, logs retries + trip events.
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)
logger.propagate = False

DEFAULT_OPENCLAW_BASE_URL = "http://localhost:8000"
DEFAULT_OPENCLAW_EXECUTE_PATH = "/execute"
DEFAULT_OPENCLAW_TIMEOUT_SECONDS = 45.0
OPENCLAW_CIRCUIT_BREAKER_THRESHOLD = 3
OPENCLAW_CIRCUIT_BREAKER_COOLDOWN_SECONDS = 30.0
OPENCLAW_UNAVAILABLE_FEEDBACK = (
    "Maaf Master, otot eksekusi (OpenClaw) sedang tidak tersedia. "
    "Saya akan tetap mencatat instruksi ini di memori sementara."
)
_circuit_breaker_lock = threading.Lock()
_consecutive_unavailable_failures = 0
_circuit_open = False
_circuit_opened_at = 0.0
_half_open_probe_inflight = False
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


def _normalize_execution_mode(params: Dict[str, Any]) -> str:
    mode = str(params.get("execution_mode", "mutating")).strip().lower()
    return "readonly" if mode == "readonly" else "mutating"


def _record_availability_failure() -> int:
    global _consecutive_unavailable_failures, _circuit_open, _circuit_opened_at, _half_open_probe_inflight
    with _circuit_breaker_lock:
        _consecutive_unavailable_failures += 1
        if _consecutive_unavailable_failures >= OPENCLAW_CIRCUIT_BREAKER_THRESHOLD:
            _circuit_open = True
            _circuit_opened_at = time.monotonic()
            _half_open_probe_inflight = False
        return _consecutive_unavailable_failures


def _mark_bridge_failure(was_probe: bool) -> int:
    """
    Atomic single-lock failure bookkeeping.

    - `was_probe=True`  -> this request originated from the half-open probe slot.
      We clear `_half_open_probe_inflight` and re-open the circuit (push cooldown).
      Failure counter is NOT incremented again (the circuit is already open).
    - `was_probe=False` -> normal closed-circuit failure. Increment counter and
      open circuit if threshold hit.

    Returns current consecutive failure count (post-mutation).
    """
    global _consecutive_unavailable_failures, _circuit_open, _circuit_opened_at, _half_open_probe_inflight
    with _circuit_breaker_lock:
        if was_probe:
            _half_open_probe_inflight = False
            _circuit_open = True
            _circuit_opened_at = time.monotonic()
            return _consecutive_unavailable_failures
        _consecutive_unavailable_failures += 1
        if _consecutive_unavailable_failures >= OPENCLAW_CIRCUIT_BREAKER_THRESHOLD:
            _circuit_open = True
            _circuit_opened_at = time.monotonic()
            _half_open_probe_inflight = False
        return _consecutive_unavailable_failures


def _mark_bridge_success(was_probe: bool) -> None:
    """Atomic single-lock success bookkeeping (closes circuit)."""
    global _consecutive_unavailable_failures, _circuit_open, _circuit_opened_at, _half_open_probe_inflight
    with _circuit_breaker_lock:
        _consecutive_unavailable_failures = 0
        _circuit_open = False
        _circuit_opened_at = 0.0
        if was_probe:
            _half_open_probe_inflight = False


def _reset_circuit_breaker() -> None:
    global _consecutive_unavailable_failures, _circuit_open, _circuit_opened_at, _half_open_probe_inflight
    with _circuit_breaker_lock:
        _consecutive_unavailable_failures = 0
        _circuit_open = False
        _circuit_opened_at = 0.0
        _half_open_probe_inflight = False


def _is_circuit_open() -> bool:
    with _circuit_breaker_lock:
        return _circuit_open


def _try_begin_half_open_probe() -> bool:
    global _half_open_probe_inflight
    with _circuit_breaker_lock:
        if not _circuit_open:
            return True
        now = time.monotonic()
        cooldown_ok = (now - _circuit_opened_at) >= OPENCLAW_CIRCUIT_BREAKER_COOLDOWN_SECONDS
        if not cooldown_ok or _half_open_probe_inflight:
            return False
        # Atomic transition: claim single half-open probe slot here.
        _half_open_probe_inflight = True
        return True


def _finish_half_open_probe(success: bool) -> None:
    global _half_open_probe_inflight, _circuit_open, _circuit_opened_at
    with _circuit_breaker_lock:
        _half_open_probe_inflight = False
        if success:
            _circuit_open = False
            _circuit_opened_at = 0.0
        else:
            _circuit_open = True
            _circuit_opened_at = time.monotonic()


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


def _build_bridge_request(
    skill_name: str,
    params: Optional[Dict[str, Any]],
    client: Optional[OpenClawBridgeClient],
) -> Dict[str, Any]:
    """
    Shared pre-flight (validation + circuit breaker claim + payload build).

    Returns either:
      - {"short_circuit": <response_dict>} when caller should return immediately, OR
      - {"bridge": ..., "payload": ..., "request_id": ..., "was_probe": bool}
    """
    if not skill_name or not skill_name.strip():
        return {
            "short_circuit": {
                "success": False,
                "error": "OpenClaw skill_name is required.",
                "status_code": None,
                "request_id": None,
                "raw_response": None,
            }
        }

    bridge = client or OpenClawBridgeClient()
    request_id = str(uuid.uuid4())
    normalized_params = params if isinstance(params, dict) else {"payload": params}
    command_candidate = _extract_command_for_safety_check(normalized_params)
    execution_mode = _normalize_execution_mode(normalized_params)

    circuit_was_open = _is_circuit_open()
    if circuit_was_open and not _try_begin_half_open_probe():
        logger.warning("[OPENCLAW] Circuit open; skipping request request_id=%s", request_id)
        return {"short_circuit": _build_circuit_open_response(request_id, raw_error="circuit_open")}
    was_probe = circuit_was_open

    if execution_mode != "readonly" and command_candidate is None:
        return {
            "short_circuit": {
                "success": False,
                "error": "Eksekusi ditolak: execution_mode mutating wajib menyertakan command/task_description eksplisit.",
                "status_code": None,
                "request_id": request_id,
                "raw_response": None,
            }
        }

    if command_candidate is not None:
        logger.info("[OPENCLAW] Gemini command request_id=%s command=%r", request_id, command_candidate)
        if not is_command_safe(command_candidate):
            logger.warning(
                "[OPENCLAW] Blocked destructive command request_id=%s command=%r",
                request_id,
                command_candidate,
            )
            return {
                "short_circuit": {
                    "success": False,
                    "error": "Eksekusi ditolak: Perintah ini berisiko mematikan sistem Master.",
                    "status_code": None,
                    "request_id": request_id,
                    "raw_response": None,
                }
            }

    payload = {
        "skill_name": skill_name.strip(),
        "params": normalized_params,
        "request_id": request_id,
        "source": "kuro_openclaw_bridge",
        "execution_mode": execution_mode,
    }
    return {
        "bridge": bridge,
        "payload": payload,
        "request_id": request_id,
        "was_probe": was_probe,
    }


def _post_openclaw_blocking(bridge: "OpenClawBridgeClient", payload: Dict[str, Any]) -> Dict[str, Any]:
    response = requests.post(
        bridge.execute_url,
        json=payload,
        timeout=bridge.timeout_seconds,
    )
    try:
        parsed_body: Any = response.json()
    except ValueError:
        parsed_body = {"text": response.text}
    return {"status_code": response.status_code, "ok": response.ok, "body": parsed_body}


def _handle_bridge_response(
    result: Dict[str, Any],
    request_id: str,
    was_probe: bool,
) -> Dict[str, Any]:
    body = result.get("body")
    status_code = result.get("status_code")
    ok = bool(result.get("ok"))

    if not ok:
        _mark_bridge_failure(was_probe)
        return {
            "success": False,
            "error": f"OpenClaw returned HTTP {status_code}",
            "status_code": status_code,
            "request_id": request_id,
            "raw_response": body,
        }

    _mark_bridge_success(was_probe)
    return {
        "success": True,
        "status_code": status_code,
        "request_id": request_id,
        "result": body,
        "raw_response": body,
    }


def _build_exception_response(
    exc: BaseException,
    request_id: str,
    bridge: "OpenClawBridgeClient",
    was_probe: bool,
) -> Dict[str, Any]:
    if isinstance(exc, requests.Timeout):
        failures = _mark_bridge_failure(was_probe)
        logger.warning(
            "[OPENCLAW] Timeout request_id=%s endpoint=%s failures=%s was_probe=%s",
            request_id, bridge.execute_url, failures, was_probe,
        )
        if was_probe or failures >= OPENCLAW_CIRCUIT_BREAKER_THRESHOLD:
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
    if isinstance(exc, requests.ConnectionError):
        failures = _mark_bridge_failure(was_probe)
        logger.error(
            "[OPENCLAW] Connection failed request_id=%s failures=%s was_probe=%s error=%s",
            request_id, failures, was_probe, exc,
        )
        if was_probe or failures >= OPENCLAW_CIRCUIT_BREAKER_THRESHOLD:
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
    if isinstance(exc, requests.RequestException):
        _mark_bridge_failure(was_probe)
        logger.error("[OPENCLAW] Request failed request_id=%s error=%s", request_id, exc)
        return {
            "success": False,
            "error": f"OpenClaw request failed: {exc}",
            "status_code": None,
            "request_id": request_id,
            "raw_response": None,
        }
    _mark_bridge_failure(was_probe)
    logger.exception("[OPENCLAW] Unexpected error request_id=%s", request_id)
    return {
        "success": False,
        "error": f"Unexpected OpenClaw bridge error: {exc}",
        "status_code": None,
        "request_id": request_id,
        "raw_response": None,
    }


def execute_openclaw_skill_blocking(
    skill_name: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    client: Optional[OpenClawBridgeClient] = None,
) -> Dict[str, Any]:
    """
    Pure synchronous variant for sync callers (tool thread, CLI, tests).

    Does NOT spawn a nested asyncio event loop — uses `requests.post` directly.
    Async callers should keep using `execute_openclaw_skill`.
    """
    pre = _build_bridge_request(skill_name, params, client)
    if "short_circuit" in pre:
        return pre["short_circuit"]

    bridge = pre["bridge"]
    payload = pre["payload"]
    request_id = pre["request_id"]
    was_probe = pre["was_probe"]

    try:
        result = _post_openclaw_blocking(bridge, payload)
    except BaseException as exc:  # noqa: BLE001 - needs full matrix for circuit breaker
        return _build_exception_response(exc, request_id, bridge, was_probe)

    return _handle_bridge_response(result, request_id, was_probe)


async def execute_openclaw_skill(
    skill_name: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    client: Optional[OpenClawBridgeClient] = None,
) -> Dict[str, Any]:
    """
    Async handover to OpenClaw daemon. Offloads blocking HTTP to a worker thread.
    """
    pre = _build_bridge_request(skill_name, params, client)
    if "short_circuit" in pre:
        return pre["short_circuit"]

    bridge = pre["bridge"]
    payload = pre["payload"]
    request_id = pre["request_id"]
    was_probe = pre["was_probe"]

    try:
        result = await asyncio.to_thread(_post_openclaw_blocking, bridge, payload)
    except BaseException as exc:  # noqa: BLE001 - matrix handled by _build_exception_response
        return _build_exception_response(exc, request_id, bridge, was_probe)

    return _handle_bridge_response(result, request_id, was_probe)
