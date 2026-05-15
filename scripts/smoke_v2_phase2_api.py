#!/usr/bin/env python3
"""Daily smoke checks for V2 Phase 2 runtime/boundary contracts (mocked)."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("WORKING_DIR", str(PROJECT_ROOT))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if "mem0" not in sys.modules:
    fake_mem0 = types.ModuleType("mem0")

    class _FakeMemory:
        def __init__(self, *args, **kwargs):
            pass

    fake_mem0.Memory = _FakeMemory
    sys.modules["mem0"] = fake_mem0

if "phoenix" not in sys.modules:
    fake_phoenix = types.ModuleType("phoenix")

    class _FakePhoenixApp:
        url = "http://localhost:6006"

        def close(self):
            return None

    fake_phoenix.launch_app = lambda *args, **kwargs: _FakePhoenixApp()
    sys.modules["phoenix"] = fake_phoenix

import main


def _auth_client(username: str = "Pantronux") -> TestClient:
    main.validate_token = lambda token: {"username": username}
    return TestClient(main.app)


async def _ok_stream(*args, **kwargs):
    yield "ok"


def run() -> int:
    main.process_chat_with_graph_stream = _ok_stream
    client = _auth_client()

    checks = []

    resp = client.post(
        "/api/chat/stream",
        data={"message": "legacy smoke", "persona": "consultant"},
        headers={"X-Chat-Session": "smoke_legacy_001"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    checks.append(("legacy stream without runtime_id", resp.status_code == 200 and "event: complete" in resp.text))

    resp = client.post(
        "/api/chat/stream",
        data={
            "message": "form runtime",
            "persona": "consultant",
            "runtime_id": "qa",
            "chat_id": "smoke_form_runtime_001",
        },
        headers={"X-Chat-Session": "smoke_form_runtime_001"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    checks.append(("form runtime_id honored", resp.status_code == 200))

    resp = client.post(
        "/api/chat/stream?runtime_id=qa",
        data={"message": "mismatch", "persona": "consultant", "runtime_id": "sovereign"},
        headers={"X-Chat-Session": "smoke_mismatch_001"},
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    checks.append(("query/form runtime mismatch -> 400", resp.status_code == 400))

    resp = client.get("/api/runtimes")
    payload = resp.json() if resp.status_code == 200 else []
    hidden_ok = True
    for row in payload:
        if any(k in row for k in ("tools", "prompt_stack", "memory_namespace")):
            hidden_ok = False
            break
    checks.append(("public runtimes hide internal fields", resp.status_code == 200 and hidden_ok))

    resp = client.get(
        "/api/admin/runtimes/runtime_not_exist_smoke",
        cookies={main.COOKIE_NAME: "Bearer dummy"},
    )
    checks.append(("admin unknown runtime -> 404", resp.status_code == 404))

    passed = 0
    print("V2 PHASE2 API SMOKE")
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"- {status} :: {name}")
        if ok:
            passed += 1
    total = len(checks)
    print(f"RESULT: {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(run())
