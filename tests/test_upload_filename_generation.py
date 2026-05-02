"""Upload filename generation tests.

Purpose: Ensure uploaded-file names are sanitised + deterministic hashed.
Covers: main.py upload pipeline helpers.
Fixtures: asyncio event loop + temp dirs.
"""
import asyncio
import hashlib
import re
import sys
import types
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.datastructures import Headers, UploadFile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
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

    def _launch_app(*args, **kwargs):
        return _FakePhoenixApp()

    fake_phoenix.launch_app = _launch_app
    sys.modules["phoenix"] = fake_phoenix

import main


def _auth_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": "tester"})
    return TestClient(main.app)


def test_resolve_upload_subdir_categories():
    assert main._resolve_upload_subdir("image/png", ".png") == "images"
    assert main._resolve_upload_subdir("application/pdf", ".pdf") == "docs"
    assert main._resolve_upload_subdir("text/plain", ".txt") == "docs"
    assert main._resolve_upload_subdir("text/plain", ".log") == "logs"
    assert main._resolve_upload_subdir("", ".bin") == "misc"


def test_save_upload_file_collision_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", str(tmp_path))

    class _FakeDatetime:
        @classmethod
        def now(cls):
            class _Ts:
                def strftime(self, fmt):
                    return "20260415_203000"

            return _Ts()

    monkeypatch.setattr(main, "datetime", _FakeDatetime)
    monkeypatch.setattr(main.random, "randint", lambda a, b: 4242)

    f1 = UploadFile(
        filename="My Report.txt",
        file=BytesIO(b"hello"),
        headers=Headers({"content-type": "text/plain"}),
    )
    r1 = asyncio.run(main.save_upload_file(f1))
    assert r1["stored_filename"] == "my_report_20260415_203000.txt"
    assert r1["sha256"] == hashlib.sha256(b"hello").hexdigest()
    assert r1["size_bytes"] == 5

    f2 = UploadFile(
        filename="My Report.txt",
        file=BytesIO(b"world"),
        headers=Headers({"content-type": "text/plain"}),
    )
    r2 = asyncio.run(main.save_upload_file(f2))
    assert r2["stored_filename"] == "my_report_20260415_203000_4242.txt"
    assert Path(r2["stored_path"]).exists()


def test_chat_history_records_unique_filenames(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(main.tools, "smart_read", lambda **kwargs: {"summary": "content", "file_type": "text"})
    monkeypatch.setattr(main, "process_chat_with_graph", lambda *args, **kwargs: "ok")

    captured = []
    integrity_rows = []

    def _capture_add_message(platform, role, content, attachments=None, persona=None, request_id=None, username=None):
        captured.append(
            {
                "platform": platform,
                "role": role,
                "content": content,
                "attachments": attachments or [],
            }
        )

    def _capture_integrity(**kwargs):
        integrity_rows.append(kwargs)

    monkeypatch.setattr(main.chat_history, "add_message", _capture_add_message)
    monkeypatch.setattr(main.chat_history, "record_uploaded_file_integrity", _capture_integrity)
    client = _auth_client(monkeypatch)
    cookies = {main.COOKIE_NAME: "Bearer dummy"}

    response = client.post(
        "/api/chat",
        data={"message": "test upload", "persona": "consultant"},
        files=[
            ("files", ("My File.txt", b"A", "text/plain")),
            ("files", ("My File.txt", b"B", "text/plain")),
        ],
        headers={"X-Chat-Session": "session_upload_12345"},
        cookies=cookies,
    )
    assert response.status_code == 200

    user_rows = [row for row in captured if row["role"] == "user"]
    assert len(user_rows) == 1
    attachments = user_rows[0]["attachments"]
    assert len(attachments) == 2
    assert attachments[0] != "My File.txt"
    assert attachments[0] != attachments[1]
    assert all(
        re.match(r"^my_file_\d{8}_\d{6}(_\d{4})?\.txt$", name)
        for name in attachments
    )
    assert len(integrity_rows) == 2
    assert {row["stored_filename"] for row in integrity_rows} == set(attachments)
    assert all(row["sha256"] for row in integrity_rows)
