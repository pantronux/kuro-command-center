#!/usr/bin/env python3
"""Smoke test OpenClaw bridge + SSoT revision bump contract."""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("smoke_openclaw")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class MockOpenClawHandler(BaseHTTPRequestHandler):
    """Minimal mock daemon that emulates OpenClaw execute endpoint."""

    server_version = "MockOpenClaw/0.1"

    def log_message(self, fmt: str, *args):  # noqa: A003
        log.info("mock_server: " + fmt, *args)

    def do_POST(self):  # noqa: N802
        if self.path != "/execute":
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"not_found"}')
            return

        length = int(self.headers.get("Content-Length", "0"))
        body_raw = self.rfile.read(length)
        try:
            body = json.loads(body_raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":false,"error":"invalid_json"}')
            return

        payload = {
            "ok": True,
            "skill_name": body.get("skill_name", "unknown"),
            "echo_task": (body.get("params") or {}).get("task_description", ""),
            "ssot_bump_required": True,
            "touched_reminders": True,
        }
        data = json.dumps(payload).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _start_mock_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 8000), MockOpenClawHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main() -> None:
    # Ensure core_service logs are visible in smoke output.
    core_logger = logging.getLogger("kuro_backend.services.core_service")
    core_logger.setLevel(logging.INFO)
    if not core_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        core_logger.addHandler(handler)

    from kuro_backend.tools.base_tools import advanced_execution_tool

    log.info("Starting mock OpenClaw daemon on http://127.0.0.1:8000")
    server = _start_mock_server()
    time.sleep(0.15)
    try:
        result = advanced_execution_tool(
            task_description="Kuro, tolong bersihkan log lama di Proxmox pake OpenClaw",
            params={"target_node": "pve-master"},
        )
        assert result.get("success") is True, f"Tool should succeed: {result}"
        assert result.get("ssot_sync", {}).get("revision_bumped") is True, (
            "SSoT revision should be bumped when mock returns ssot_bump_required=True"
        )
        log.info("advanced_execution_tool result: %s", json.dumps(result, ensure_ascii=False))
        log.info("Smoke test passed. Check terminal output for '[SYNC] Revision bumped'.")
        log.info("No JSONDecodeError occurred while processing mock server response.")
    finally:
        server.shutdown()
        server.server_close()
        log.info("Mock OpenClaw daemon stopped")

    # Circuit breaker smoke: daemon is down, trigger 3 availability failures.
    log.info("Starting circuit-breaker fallback scenario (daemon intentionally down)")
    start = time.time()
    failure_results = []
    for idx in range(3):
        r = advanced_execution_tool(
            task_description=f"Test fallback command #{idx + 1}",
            params={"mode": "fallback-test"},
        )
        failure_results.append(r)
        log.info("failure attempt #%s -> success=%s", idx + 1, r.get("success"))

    # Third failure should open breaker and trigger user-friendly fallback message.
    breaker_result = failure_results[-1]
    assert breaker_result.get("success") is False, f"Expected failure on breaker path: {breaker_result}"
    assert (
        "otot eksekusi (OpenClaw) sedang tidak tersedia" in (breaker_result.get("message") or "")
        or "otot eksekusi (OpenClaw) sedang tidak tersedia" in (breaker_result.get("error") or "")
    ), f"Expected unavailable feedback message: {breaker_result}"
    assert breaker_result.get("execution_result", {}).get("memory_fallback_required") is True, (
        "Circuit breaker should ask for memory fallback."
    )
    assert breaker_result.get("memory_fallback", {}).get("saved") is True, (
        "Fallback instruction should be saved to memory."
    )

    # Additional call should fail fast while circuit remains open (no hanging behavior).
    fast_result = advanced_execution_tool(
        task_description="Test fallback command fast-path",
        params={"mode": "fallback-fast"},
    )
    elapsed = time.time() - start
    assert elapsed < 10, f"Circuit-breaker flow took too long ({elapsed:.2f}s), expected fast-fail."
    assert fast_result.get("execution_result", {}).get("circuit_breaker", {}).get("open") is True, (
        "Circuit should stay open for fast-fail behavior."
    )
    log.info("Circuit breaker fallback scenario passed in %.2fs", elapsed)


if __name__ == "__main__":
    main()
