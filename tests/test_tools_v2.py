"""Tool Runtime V2 policy, execution, API, and safety tests."""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
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

from kuro_backend.config import settings
from kuro_backend.tools_v2.agent_mode import AgentModeRunner
from kuro_backend.tools_v2.approvals import ToolApprovalStore
from kuro_backend.tools_v2.audit import ToolAuditStore
from kuro_backend.tools_v2.deep_research import DeepResearchService, DeepResearchStore
from kuro_backend.tools_v2.executor import ToolExecutor, create_tools_v2_router
from kuro_backend.tools_v2.policy import ToolPolicy
from kuro_backend.tools_v2.registry import ToolRegistry
from kuro_backend.tools_v2.reminders import ReminderStore
from kuro_backend.tools_v2.schemas import ToolActor, ToolExecutionRequest
from kuro_backend.tools_v2.tasks import TaskStore
from kuro_backend.tools_v2.web_search import WebSearchV2


TOOL_FLAGS = (
    "KURO_AGENT_TOOLS_V2_ENABLED",
    "KURO_WEB_SEARCH_V2_ENABLED",
    "KURO_DEEP_RESEARCH_V2_ENABLED",
    "KURO_TASKS_V2_ENABLED",
)


def _fake_serper(query: str, search_type: str, num_results: int):
    return {
        "query": query,
        "search_type": search_type,
        "organic_results": [
            {
                "title": "Kuro source",
                "link": "https://example.com/kuro",
                "snippet": "Grounded source snippet for Kuro.",
                "date": "2026-05-22",
            },
            {
                "title": "Second source",
                "link": "https://research.example.edu/report",
                "snippet": "Academic source snippet.",
            },
        ][:num_results],
    }


@pytest.fixture
def tool_stack(tmp_path, monkeypatch):
    for flag in TOOL_FLAGS:
        monkeypatch.setattr(settings, flag, False, raising=False)
    db_path = tmp_path / "tools_v2.db"
    registry = ToolRegistry()
    approvals = ToolApprovalStore(db_path)
    audit = ToolAuditStore(db_path)
    web_search = WebSearchV2(search_callable=_fake_serper)
    research = DeepResearchService(
        store=DeepResearchStore(db_path),
        web_search=web_search,
    )
    executor = ToolExecutor(
        registry=registry,
        policy=ToolPolicy(registry),
        approvals=approvals,
        audit=audit,
        web_search=web_search,
        deep_research=research,
        tasks=TaskStore(db_path),
        reminders=ReminderStore(db_path),
        agent_runner=AgentModeRunner(max_steps=2),
    )
    return {
        "db_path": db_path,
        "registry": registry,
        "approvals": approvals,
        "audit": audit,
        "web_search": web_search,
        "research": research,
        "executor": executor,
    }


def _actor(username: str = "Pantronux", runtime_id: str = "sovereign", is_admin: bool = True) -> ToolActor:
    return ToolActor(
        username=username,
        runtime_id=runtime_id,
        workspace_id="default",
        roles=["user", "admin"] if is_admin else ["user"],
        is_admin=is_admin,
    )


def test_tools_disabled_by_default(tool_stack):
    actor = _actor(is_admin=False)
    registry = tool_stack["registry"]
    executor = tool_stack["executor"]

    assert registry.list_visible(actor) == []

    result = executor.execute(
        tool_id="web_search",
        request=ToolExecutionRequest(input={"query": "kuro"}),
        actor=actor,
    )

    assert result.ok is False
    assert result.status == "blocked"
    assert result.error["code"] == "tool_disabled"


def test_tool_list_safe_when_enabled(tool_stack, monkeypatch):
    monkeypatch.setattr(settings, "KURO_WEB_SEARCH_V2_ENABLED", True, raising=False)
    tools = tool_stack["registry"].list_visible(_actor(is_admin=False, runtime_id="research"))

    assert [tool.tool_id for tool in tools] == ["web_search"]
    serialized = str([tool.model_dump() for tool in tools]).lower()
    assert "api_key" not in serialized
    assert "secret" not in serialized


def test_high_risk_agent_mode_requires_approval_then_runs(tool_stack, monkeypatch):
    monkeypatch.setattr(settings, "KURO_AGENT_TOOLS_V2_ENABLED", True, raising=False)
    executor = tool_stack["executor"]
    actor = _actor(is_admin=False)
    request = ToolExecutionRequest(input={"goal": "prepare a bounded plan", "requested_steps": 10})

    blocked = executor.execute(tool_id="agent_mode", request=request, actor=actor)

    assert blocked.approval_required is True
    assert blocked.approval_id

    tool_stack["approvals"].approve(blocked.approval_id, decided_by="Pantronux")
    approved = executor.execute(
        tool_id="agent_mode",
        request=request.model_copy(update={"approval_id": blocked.approval_id}),
        actor=actor,
    )

    assert approved.ok is True
    assert approved.output["executed_steps"] == 2
    assert approved.output["max_steps_enforced"] is True


def test_web_search_uses_mocked_serper_and_normalizes_sources(tool_stack, monkeypatch):
    monkeypatch.setattr(settings, "KURO_WEB_SEARCH_V2_ENABLED", True, raising=False)
    result = tool_stack["executor"].execute(
        tool_id="web_search",
        request=ToolExecutionRequest(input={"query": "kuro ai", "max_results": 2}, runtime_id="research"),
        actor=_actor(runtime_id="research", is_admin=False),
    )

    assert result.ok is True
    assert result.output["total_results"] == 2
    assert result.sources[0].title == "Kuro source"
    assert result.sources[0].url == "https://example.com/kuro"


def test_deep_research_mocked_job_lifecycle(tool_stack, monkeypatch):
    monkeypatch.setattr(settings, "KURO_DEEP_RESEARCH_V2_ENABLED", True, raising=False)
    service = tool_stack["research"]

    queued = service.create_job(username="Pantronux", workspace_id="default", query="Kuro research")
    completed = service.run_job(queued.job_id)

    assert completed is not None
    assert completed.status == "completed"
    assert completed.sources
    assert "Deep Research Report" in completed.report_markdown
    assert completed.exportable_report["source_count"] == 2


def test_tasks_create_list_update_delete_and_user_isolation(tool_stack, monkeypatch):
    monkeypatch.setattr(settings, "KURO_TASKS_V2_ENABLED", True, raising=False)
    tasks = tool_stack["executor"].tasks

    task = tasks.create_task(username="Pantronux", title="Write tests", workspace_id="default")

    assert tasks.list_tasks(username="Pantronux")[0]["task_id"] == task["task_id"]
    assert tasks.list_tasks(username="Faikhira") == []

    updated = tasks.update_task(
        task_id=task["task_id"],
        username="Pantronux",
        patch={"status": "completed", "metadata": {"done_by": "test"}},
    )
    assert updated["status"] == "completed"
    assert updated["completed_at"]
    assert updated["metadata"]["done_by"] == "test"

    assert tasks.delete_task(task_id=task["task_id"], username="Faikhira") is False
    assert tasks.delete_task(task_id=task["task_id"], username="Pantronux") is True
    assert tasks.list_tasks(username="Pantronux") == []


def test_reminder_create_list_update(tool_stack, monkeypatch):
    monkeypatch.setattr(settings, "KURO_TASKS_V2_ENABLED", True, raising=False)
    reminders = tool_stack["executor"].reminders

    reminder = reminders.create_reminder(
        username="Pantronux",
        remind_at="2026-05-23T09:00:00+07:00",
        channel="web",
        metadata={"message": "standup"},
    )

    assert reminders.list_reminders(username="Pantronux")[0]["reminder_id"] == reminder["reminder_id"]
    updated = reminders.update_reminder(
        reminder_id=reminder["reminder_id"],
        username="Pantronux",
        patch={"status": "sent", "attempt_count": 1},
    )
    assert updated["status"] == "sent"
    assert updated["sent_at"]
    assert updated["attempt_count"] == 1


def test_agent_mode_max_steps_enforced():
    result = AgentModeRunner(max_steps=3).run(goal="ship safely", requested_steps=10)

    assert result["executed_steps"] == 3
    assert result["max_steps_enforced"] is True


def test_openclaw_bridge_safety_not_bypassed(tool_stack, monkeypatch):
    monkeypatch.setattr(settings, "KURO_AGENT_TOOLS_V2_ENABLED", True, raising=False)
    from kuro_backend.execution import openclaw_bridge

    def _fail_post(*args, **kwargs):
        raise AssertionError("OpenClaw HTTP should not be called for a blocked command")

    monkeypatch.setattr(openclaw_bridge, "is_openclaw_enabled", lambda: True)
    monkeypatch.setattr(openclaw_bridge.requests, "post", _fail_post)

    executor = tool_stack["executor"]
    actor = _actor(is_admin=True)
    request = ToolExecutionRequest(
        input={
            "skill_name": "shell",
            "params": {
                "command": "rm -rf /",
                "execution_mode": "mutating",
            },
        },
    )
    approval_required = executor.execute(tool_id="openclaw_bridge", request=request, actor=actor)
    tool_stack["approvals"].approve(approval_required.approval_id, decided_by="Pantronux")

    result = executor.execute(
        tool_id="openclaw_bridge",
        request=request.model_copy(update={"approval_id": approval_required.approval_id}),
        actor=actor,
    )

    assert result.ok is True
    assert result.output["openclaw"]["success"] is False
    assert "ditolak" in result.output["openclaw"]["error"]


def test_tools_v2_api_tasks_and_approval_flow(tool_stack, monkeypatch):
    monkeypatch.setattr(settings, "KURO_TASKS_V2_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KURO_AGENT_TOOLS_V2_ENABLED", True, raising=False)

    def auth_dep():
        return {"username": "Pantronux"}

    def admin_dep():
        return {"username": "Pantronux"}

    app = FastAPI()
    app.include_router(
        create_tools_v2_router(
            auth_dependency=auth_dep,
            admin_dependency=admin_dep,
            executor=tool_stack["executor"],
        )
    )
    client = TestClient(app)

    created = client.post("/api/tasks", json={"title": "API task"})
    assert created.status_code == 200
    task_id = created.json()["data"]["task_id"]
    assert client.get("/api/tasks").json()["data"][0]["task_id"] == task_id
    assert client.patch(f"/api/tasks/{task_id}", json={"status": "completed"}).json()["data"]["status"] == "completed"
    assert client.delete(f"/api/tasks/{task_id}").json()["data"]["deleted"] is True

    approval = client.post(
        "/api/tools/agent_mode/execute",
        json={"input": {"goal": "bounded api plan", "requested_steps": 9}},
    ).json()["data"]
    assert approval["approval_required"] is True
    approval_id = approval["approval_id"]
    assert client.post(f"/api/admin/tools/approvals/{approval_id}/approve").status_code == 200

    approved = client.post(
        "/api/tools/agent_mode/execute",
        json={
            "approval_id": approval_id,
            "input": {"goal": "bounded api plan", "requested_steps": 9},
        },
    ).json()["data"]
    assert approved["ok"] is True
    assert approved["output"]["executed_steps"] == 2
