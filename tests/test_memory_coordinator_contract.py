"""Contract tests for unified memory coordinator (habits + OpenClaw revision bump).

--- Header Doc ---
Purpose: Verify memory_coordinator post-response fan-out + revision semantics.
Covers: memory_coordinator.post_response_memory_writes, build_context_for_llm (chancellor market block).
Fixtures: tmp sqlite DBs + monkeypatched Mem0 + finance_db stubs.
"""
import sys
import types
from pathlib import Path

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

from kuro_backend import memory_coordinator
from kuro_backend.services import core_service


def test_habit_create_via_coordinator_calls_svc(monkeypatch):
    calls = {"n": 0}

    def _fake_add(title: str, scheduled_time: str, category: str = "General"):
        calls["n"] += 1
        assert title == "Water"
        assert scheduled_time == "07:00"
        assert category == "Health"
        return 501

    monkeypatch.setattr(core_service, "add_habit_svc", _fake_add)
    monkeypatch.setattr(core_service, "get_data_revision", lambda: 1)

    hid = memory_coordinator.habit_create("Water", "07:00", category="Health", source="pytest")
    assert hid == 501
    assert calls["n"] == 1


def test_habit_create_then_list_validated_and_revision_increases(monkeypatch):
    """After coordinator create, outbound list is non-empty and revision counter rises."""
    rows = []
    revision = {"v": 10}

    def _add_svc(title: str, scheduled_time: str, category: str = "General"):
        rows.append({"title": title, "scheduled_time": scheduled_time, "category": category})
        revision["v"] += 1
        return len(rows)

    def _list_validated():
        return [{"id": i + 1, **r} for i, r in enumerate(rows)]

    def _get_rev():
        return revision["v"]

    monkeypatch.setattr(core_service, "add_habit_svc", _add_svc)
    monkeypatch.setattr(core_service, "list_habits_validated", _list_validated)
    monkeypatch.setattr(core_service, "get_data_revision", _get_rev)

    before = core_service.get_data_revision()
    assert core_service.list_habits_validated() == []

    memory_coordinator.habit_create("Run", "06:00", source="pytest")

    habits = core_service.list_habits_validated()
    assert len(habits) == 1
    assert habits[0]["title"] == "Run"
    assert core_service.get_data_revision() == before + 1


def test_openclaw_touched_habits_bumps_revision(monkeypatch):
    bumps = []

    monkeypatch.setattr(core_service, "bump_data_revision", lambda: bumps.append(1))
    monkeypatch.setattr(core_service, "get_data_revision", lambda: len(bumps))

    meta = memory_coordinator.apply_openclaw_execution_result(
        success=True,
        skill_name="some_skill",
        raw={"touched_habits": True},
    )
    assert meta["should_bump_revision"] is True
    assert meta["revision_bumped"] is True
    assert meta["revision_error"] is None
    assert len(bumps) == 1


def test_openclaw_success_without_flags_does_not_bump(monkeypatch):
    bumps = []

    monkeypatch.setattr(core_service, "bump_data_revision", lambda: bumps.append(1))

    meta = memory_coordinator.apply_openclaw_execution_result(
        success=True,
        skill_name="noop",
        raw={},
    )
    assert meta["should_bump_revision"] is False
    assert meta["revision_bumped"] is False
    assert len(bumps) == 0


def test_harvest_gemini_share_success_always_requests_bump(monkeypatch):
    bumps = []

    monkeypatch.setattr(core_service, "bump_data_revision", lambda: bumps.append(1))

    meta = memory_coordinator.apply_openclaw_execution_result(
        success=True,
        skill_name="harvest_gemini_share",
        raw={},
    )
    assert meta["should_bump_revision"] is True
    assert meta["revision_bumped"] is True
    assert len(bumps) == 1
