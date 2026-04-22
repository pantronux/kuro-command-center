"""Tests for Kuro AI V6.0 Sovereign proactive_greeting.

Covers the once-per-calendar-day cooldown, the kill-switch, the custom-text
override, and the targeted-WS send path. The SQLite ledger is redirected
to a tmp_path DB so the tests never touch the real ``kuro_auth.db``.

--- Header Doc ---
Purpose: Verify one-per-day greeting cooldown + kill-switch + text override.
Covers: kuro_backend.proactive_greeting.maybe_send_greeting.
Fixtures: tmp_path SQLite + fake WebSocket send spy.
"""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# The module graph pulls in voice_service / memory_manager transitively
# only if imported; we stub the optional deps the same way the other test
# files do so the fresh conftest still boots cleanly.
if "mem0" not in sys.modules:
    fake_mem0 = types.ModuleType("mem0")

    class _FakeMemory:
        def __init__(self, *a, **kw):
            pass

    fake_mem0.Memory = _FakeMemory
    sys.modules["mem0"] = fake_mem0


class _FakeWebSocket:
    """Minimal stand-in for starlette WebSocket used by send_ui_command_to.

    We only need the two state properties the real code probes plus a
    ``send_text`` recorder.
    """

    def __init__(self, *, connected: bool = True):
        from starlette.websockets import WebSocketState

        self.client_state = WebSocketState.CONNECTED if connected else WebSocketState.DISCONNECTED
        self.application_state = WebSocketState.CONNECTED if connected else WebSocketState.DISCONNECTED
        self.sent: list[str] = []

    async def send_text(self, data: str) -> None:
        self.sent.append(data)


@pytest.fixture
def isolated_auth_db(tmp_path, monkeypatch):
    """Redirect auth_db.DB_PATH to a private file and re-init the schema.

    Importing fresh each test guarantees the ledger is empty and the new
    ``proactive_greetings`` table is created.
    """
    import importlib

    import kuro_backend.auth_db as auth_db
    monkeypatch.setattr(auth_db, "DB_PATH", str(tmp_path / "auth.db"))
    auth_db.init_auth_db()

    import kuro_backend.proactive_greeting as pg
    importlib.reload(pg)
    return auth_db, pg


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_first_call_sends_and_records(isolated_auth_db, monkeypatch):
    auth_db, pg = isolated_auth_db
    monkeypatch.setenv("KURO_PROACTIVE_GREETING_ENABLED", "true")
    monkeypatch.setenv("KURO_PROACTIVE_GREETING_TEXT", "Welcome back.")
    monkeypatch.setenv("KURO_PROACTIVE_GREETING_COOLDOWN_DAYS", "1")

    ws = _FakeWebSocket()
    delivered = _run(pg.maybe_send(ws, "pantronux"))

    assert delivered is True
    assert len(ws.sent) == 1
    assert '"GREETING"' in ws.sent[0]
    assert '"Welcome back."' in ws.sent[0]
    # Ledger is now populated.
    assert auth_db.greeting_sent_within("pantronux", 1) is True


def test_second_call_same_day_is_silent(isolated_auth_db, monkeypatch):
    auth_db, pg = isolated_auth_db
    monkeypatch.setenv("KURO_PROACTIVE_GREETING_ENABLED", "true")
    monkeypatch.setenv("KURO_PROACTIVE_GREETING_COOLDOWN_DAYS", "1")

    ws1 = _FakeWebSocket()
    assert _run(pg.maybe_send(ws1, "pantronux")) is True

    ws2 = _FakeWebSocket()
    assert _run(pg.maybe_send(ws2, "pantronux")) is False
    assert ws2.sent == []


def test_disabled_env_never_sends(isolated_auth_db, monkeypatch):
    auth_db, pg = isolated_auth_db
    monkeypatch.setenv("KURO_PROACTIVE_GREETING_ENABLED", "false")

    ws = _FakeWebSocket()
    assert _run(pg.maybe_send(ws, "pantronux")) is False
    assert ws.sent == []
    assert auth_db.greeting_sent_within("pantronux", 1) is False


def test_cooldown_zero_always_sends(isolated_auth_db, monkeypatch):
    auth_db, pg = isolated_auth_db
    monkeypatch.setenv("KURO_PROACTIVE_GREETING_ENABLED", "true")
    monkeypatch.setenv("KURO_PROACTIVE_GREETING_COOLDOWN_DAYS", "0")

    ws1 = _FakeWebSocket()
    ws2 = _FakeWebSocket()
    assert _run(pg.maybe_send(ws1, "pantronux")) is True
    assert _run(pg.maybe_send(ws2, "pantronux")) is True


def test_missing_username_short_circuits(isolated_auth_db, monkeypatch):
    auth_db, pg = isolated_auth_db
    monkeypatch.setenv("KURO_PROACTIVE_GREETING_ENABLED", "true")

    ws = _FakeWebSocket()
    assert _run(pg.maybe_send(ws, None)) is False
    assert _run(pg.maybe_send(ws, "   ")) is False
    assert ws.sent == []


def test_disconnected_ws_does_not_record(isolated_auth_db, monkeypatch):
    auth_db, pg = isolated_auth_db
    monkeypatch.setenv("KURO_PROACTIVE_GREETING_ENABLED", "true")
    monkeypatch.setenv("KURO_PROACTIVE_GREETING_COOLDOWN_DAYS", "1")

    ws = _FakeWebSocket(connected=False)
    delivered = _run(pg.maybe_send(ws, "pantronux"))

    # send fails silently; cooldown must NOT be marked so master still
    # gets a greeting on the next (healthy) connection.
    assert delivered is False
    assert auth_db.greeting_sent_within("pantronux", 1) is False
