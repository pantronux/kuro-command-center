import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient

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
from kuro_backend import memory_coordinator
from kuro_backend import reminder_service
from kuro_backend.services import core_service


def _auth_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": "tester"})
    return TestClient(main.app)


def test_habit_write_endpoints_use_memory_coordinator_gateway(monkeypatch):
    calls = {"add": 0, "update": 0, "delete": 0}

    def _habit_create(title: str, scheduled_time: str, category: str = "General", source: str = ""):
        calls["add"] += 1
        assert title == "Gym"
        assert scheduled_time == "15:00"
        assert category == "Health"
        assert source == "web_api"
        return 99

    def _habit_update(habit_id: int, source: str = "", **kwargs):
        calls["update"] += 1
        assert habit_id == 99
        assert source == "web_api"
        assert kwargs["title"] == "Gym Updated"
        assert kwargs["target_per_week"] == 4

    def _habit_delete(habit_id: int, source: str = ""):
        calls["delete"] += 1
        assert habit_id == 99
        assert source == "web_api"

    monkeypatch.setattr(memory_coordinator, "habit_create", _habit_create)
    monkeypatch.setattr(memory_coordinator, "habit_update", _habit_update)
    monkeypatch.setattr(memory_coordinator, "habit_delete", _habit_delete)

    client = _auth_client(monkeypatch)
    cookies = {main.COOKIE_NAME: "Bearer dummy"}

    create_resp = client.post(
        "/api/habits",
        data={"title": "Gym", "scheduled_time": "15:00", "category": "Health"},
        cookies=cookies,
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["status"] == "success"
    assert create_resp.json()["habit_id"] == 99

    update_resp = client.put(
        "/api/habits/99",
        data={"title": "Gym Updated", "target_per_week": 4},
        cookies=cookies,
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "success"

    delete_resp = client.delete("/api/habits/99", cookies=cookies)
    assert delete_resp.status_code == 200
    assert delete_resp.json()["status"] == "success"

    assert calls == {"add": 1, "update": 1, "delete": 1}


def test_reminder_service_mark_notified_routes_to_svc(monkeypatch):
    called = {"n10": 0, "evt": 0}

    def _mark_10m_svc(reminder_id: int):
        called["n10"] += 1
        assert reminder_id == 7

    def _mark_event_svc(reminder_id: int):
        called["evt"] += 1
        assert reminder_id == 8

    monkeypatch.setattr(reminder_service.cs, "mark_notified_10m_svc", _mark_10m_svc)
    monkeypatch.setattr(reminder_service.cs, "mark_notified_event_svc", _mark_event_svc)

    reminder_service.mark_notified_10m(7)
    reminder_service.mark_notified_event(8)

    assert called == {"n10": 1, "evt": 1}


def test_core_service_notified_svc_bumps_revision(monkeypatch):
    calls = {"mark_10": 0, "mark_evt": 0, "bump": 0}

    def _mark_10(reminder_id: int):
        calls["mark_10"] += 1
        assert reminder_id == 10

    def _mark_evt(reminder_id: int):
        calls["mark_evt"] += 1
        assert reminder_id == 11

    def _bump():
        calls["bump"] += 1

    monkeypatch.setattr(core_service, "mark_notified_10m", _mark_10)
    monkeypatch.setattr(core_service, "mark_notified_event", _mark_evt)
    monkeypatch.setattr(core_service, "bump_data_revision", _bump)

    core_service.mark_notified_10m_svc(10)
    core_service.mark_notified_event_svc(11)

    assert calls == {"mark_10": 1, "mark_evt": 1, "bump": 2}
