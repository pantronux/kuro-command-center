"""Tool Runtime V2 executor and additive FastAPI routes."""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from kuro_backend.enterprise_flags import is_enabled
from kuro_backend.enterprise_observability.metrics import record_tool_call_if_enabled
from kuro_backend.enterprise_observability.security_events import record_tool_denied_if_enabled
from kuro_backend.tools_v2.agent_mode import AgentModeRunner
from kuro_backend.tools_v2.approvals import ToolApprovalStore
from kuro_backend.tools_v2.audit import ToolAuditStore
from kuro_backend.tools_v2.deep_research import DeepResearchService
from kuro_backend.tools_v2.policy import ToolPolicy, ToolPolicyError
from kuro_backend.tools_v2.registry import ToolRegistry, get_tool_registry
from kuro_backend.tools_v2.reminders import ReminderStore
from kuro_backend.tools_v2.schemas import (
    DeepResearchJobRequest,
    ReminderCreateRequest,
    ReminderPatchRequest,
    TaskCreateRequest,
    TaskPatchRequest,
    ToolActor,
    ToolExecutionRequest,
    ToolExecutionResult,
)
from kuro_backend.tools_v2.tasks import TaskStore
from kuro_backend.tools_v2.web_search import WebSearchV2


def _success(data: Any = None, **extra: Any) -> Dict[str, Any]:
    payload = {"status": "success", "data": data, "error": None}
    payload.update(extra)
    return payload


class ToolExecutor:
    def __init__(
        self,
        *,
        registry: Optional[ToolRegistry] = None,
        policy: Optional[ToolPolicy] = None,
        approvals: Optional[ToolApprovalStore] = None,
        audit: Optional[ToolAuditStore] = None,
        web_search: Optional[WebSearchV2] = None,
        deep_research: Optional[DeepResearchService] = None,
        tasks: Optional[TaskStore] = None,
        reminders: Optional[ReminderStore] = None,
        agent_runner: Optional[AgentModeRunner] = None,
    ) -> None:
        self.registry = registry or get_tool_registry()
        self.policy = policy or ToolPolicy(self.registry)
        self.approvals = approvals or ToolApprovalStore()
        self.audit = audit or ToolAuditStore()
        self.web_search = web_search or WebSearchV2()
        self.tasks = tasks or TaskStore()
        self.reminders = reminders or ReminderStore()
        self.deep_research = deep_research or DeepResearchService(web_search=self.web_search)
        self.agent_runner = agent_runner or AgentModeRunner()

    def execute(
        self,
        *,
        tool_id: str,
        request: ToolExecutionRequest,
        actor: ToolActor,
    ) -> ToolExecutionResult:
        trace_id = request.trace_id or f"tool_{uuid.uuid4().hex}"
        actor = actor.model_copy(
            update={
                "runtime_id": request.runtime_id or actor.runtime_id,
                "workspace_id": request.workspace_id or actor.workspace_id,
            }
        )
        record_tool_call_if_enabled(
            tool_id=tool_id,
            username=actor.username,
            runtime_id=actor.runtime_id,
            workspace_id=actor.workspace_id,
            trace_id=trace_id,
        )
        definition = self.registry.get(tool_id)
        started = time.monotonic()
        if definition is None:
            audit_id = self.audit.log_event(
                event_type="tool_not_found",
                tool_id=tool_id,
                username=actor.username,
                runtime_id=actor.runtime_id,
                workspace_id=actor.workspace_id,
                trace_id=trace_id,
                status="not_found",
                error="unknown tool_id",
            )
            return ToolExecutionResult(
                ok=False,
                tool_id=tool_id,
                trace_id=trace_id,
                status="not_found",
                error={"code": "tool_not_found", "message": "Unknown tool_id."},
                audit_id=audit_id,
            )

        try:
            self.policy.enforce_can_execute(definition, actor)
            self.policy.validate_input(definition, request.input)
            if self.policy.requires_approval(definition, request.input) and not self.approvals.is_approved_for(
                request.approval_id,
                tool_id=definition.tool_id,
                username=actor.username,
            ):
                approval = self.approvals.create_request(
                    definition=definition,
                    username=actor.username,
                    runtime_id=actor.runtime_id,
                    workspace_id=actor.workspace_id,
                    input_payload=request.input,
                    reason=f"{definition.display_name} requires approval.",
                )
                audit_id = self.audit.log_event(
                    event_type="tool_approval_required",
                    tool_id=definition.tool_id,
                    username=actor.username,
                    runtime_id=actor.runtime_id,
                    workspace_id=actor.workspace_id,
                    trace_id=trace_id,
                    risk_level=definition.risk_level,
                    status="approval_required",
                    approval_id=approval.approval_id,
                    payload={"input": request.input},
                )
                return ToolExecutionResult(
                    ok=False,
                    tool_id=definition.tool_id,
                    trace_id=trace_id,
                    status="approval_required",
                    approval_required=True,
                    approval_id=approval.approval_id,
                    audit_id=audit_id,
                    duration_ms=self._duration_ms(started),
                )

            output = self._dispatch(definition.tool_id, request.input, actor)
            sources = output.pop("sources", []) if isinstance(output, dict) else []
            audit_id = self.audit.log_event(
                event_type="tool_execution",
                tool_id=definition.tool_id,
                username=actor.username,
                runtime_id=actor.runtime_id,
                workspace_id=actor.workspace_id,
                trace_id=trace_id,
                risk_level=definition.risk_level,
                status="success",
                approval_id=request.approval_id,
                payload={"input_keys": sorted((request.input or {}).keys())},
            )
            return ToolExecutionResult(
                ok=True,
                tool_id=definition.tool_id,
                trace_id=trace_id,
                status="success",
                output=output if isinstance(output, dict) else {"value": output},
                sources=sources,
                approval_id=request.approval_id,
                audit_id=audit_id,
                duration_ms=self._duration_ms(started),
            )
        except ToolPolicyError as exc:
            record_tool_denied_if_enabled(
                definition.tool_id,
                actor_username=actor.username,
                runtime_id=actor.runtime_id,
                workspace_id=actor.workspace_id,
                trace_id=trace_id,
                reason=exc.code,
                metadata={"message": exc.message},
            )
            audit_id = self.audit.log_event(
                event_type="tool_blocked",
                tool_id=definition.tool_id,
                username=actor.username,
                runtime_id=actor.runtime_id,
                workspace_id=actor.workspace_id,
                trace_id=trace_id,
                risk_level=definition.risk_level,
                status="blocked",
                payload={"code": exc.code},
                error=exc.message,
            )
            return ToolExecutionResult(
                ok=False,
                tool_id=definition.tool_id,
                trace_id=trace_id,
                status="blocked",
                error={"code": exc.code, "message": exc.message},
                audit_id=audit_id,
                duration_ms=self._duration_ms(started),
            )
        except Exception as exc:
            audit_id = self.audit.log_event(
                event_type="tool_error",
                tool_id=definition.tool_id,
                username=actor.username,
                runtime_id=actor.runtime_id,
                workspace_id=actor.workspace_id,
                trace_id=trace_id,
                risk_level=definition.risk_level,
                status="error",
                error=str(exc),
            )
            return ToolExecutionResult(
                ok=False,
                tool_id=definition.tool_id,
                trace_id=trace_id,
                status="error",
                error={"code": "tool_execution_error", "message": str(exc)[:500]},
                audit_id=audit_id,
                duration_ms=self._duration_ms(started),
            )

    def _dispatch(self, tool_id: str, input_payload: Dict[str, Any], actor: ToolActor) -> Dict[str, Any]:
        if tool_id == "web_search":
            result = self.web_search.search(
                query=str(input_payload.get("query") or ""),
                search_type=str(input_payload.get("search_type") or "search"),
                max_results=int(input_payload.get("max_results") or 5),
            )
            if not result.get("ok"):
                raise RuntimeError(str(result.get("error") or "web_search_failed"))
            return result
        if tool_id == "deep_research":
            job = self.deep_research.create_job(
                username=actor.username,
                workspace_id=actor.workspace_id,
                query=str(input_payload.get("query") or ""),
            )
            completed = self.deep_research.run_job(job.job_id) or job
            return {"job": completed.model_dump()}
        if tool_id == "create_task":
            task = self.tasks.create_task(
                username=actor.username,
                workspace_id=actor.workspace_id,
                title=str(input_payload.get("title") or ""),
                description=str(input_payload.get("description") or ""),
                due_at=input_payload.get("due_at"),
                recurrence_rule=input_payload.get("recurrence_rule"),
                source_chat_id=input_payload.get("source_chat_id"),
                source_message_id=input_payload.get("source_message_id"),
                metadata=input_payload.get("metadata") if isinstance(input_payload.get("metadata"), dict) else {},
            )
            return {"task": task}
        if tool_id == "create_reminder":
            reminder = self.reminders.create_reminder(
                username=actor.username,
                workspace_id=actor.workspace_id,
                remind_at=str(input_payload.get("remind_at") or ""),
                task_id=input_payload.get("task_id"),
                channel=str(input_payload.get("channel") or "web"),
                metadata=input_payload.get("metadata") if isinstance(input_payload.get("metadata"), dict) else {},
            )
            return {"reminder": reminder}
        if tool_id == "agent_mode":
            return self.agent_runner.run(
                goal=str(input_payload.get("goal") or ""),
                requested_steps=input_payload.get("requested_steps"),
                allowed_tool_ids=input_payload.get("allowed_tool_ids") if isinstance(input_payload.get("allowed_tool_ids"), list) else [],
            )
        if tool_id == "openclaw_bridge":
            from kuro_backend.execution.service import execute_openclaw_skill_sync

            return {
                "openclaw": execute_openclaw_skill_sync(
                    str(input_payload.get("skill_name") or ""),
                    input_payload.get("params") if isinstance(input_payload.get("params"), dict) else {},
                )
            }
        raise RuntimeError(f"No handler registered for {tool_id}")

    def _duration_ms(self, started: float) -> float:
        return round((time.monotonic() - started) * 1000.0, 3)


def _actor_from_user(user: Dict[str, str], *, runtime_id: str = "sovereign", workspace_id: str = "default") -> ToolActor:
    username = str(user.get("username") or "")
    is_admin = username == os.getenv("ADMIN_USERNAME", "Pantronux")
    roles = ["user", "admin"] if is_admin else ["user"]
    return ToolActor(
        username=username,
        roles=roles,
        runtime_id=runtime_id,
        workspace_id=workspace_id,
        is_admin=is_admin,
    )


def create_tools_v2_router(
    *,
    auth_dependency: Callable[..., Dict[str, str]],
    admin_dependency: Callable[..., Dict[str, str]],
    executor: Optional[ToolExecutor] = None,
) -> APIRouter:
    router = APIRouter()
    service_instance = executor

    def _service() -> ToolExecutor:
        nonlocal service_instance
        if service_instance is None:
            service_instance = ToolExecutor()
        return service_instance

    def _require_flag(flag_name: str, label: str) -> None:
        if not is_enabled(flag_name):
            raise HTTPException(status_code=404, detail=f"{label} is disabled")

    @router.get("/api/tools")
    async def list_tools(
        runtime_id: str = Query("sovereign"),
        workspace_id: str = Query("default"),
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        actor = _actor_from_user(user, runtime_id=runtime_id, workspace_id=workspace_id)
        service = _service()
        return _success([definition.model_dump() for definition in service.registry.list_visible(actor)])

    @router.post("/api/tools/{tool_id}/execute")
    async def execute_tool(
        tool_id: str,
        payload: ToolExecutionRequest,
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        actor = _actor_from_user(user, runtime_id=payload.runtime_id, workspace_id=payload.workspace_id)
        service = _service()
        result = service.execute(tool_id=tool_id, request=payload, actor=actor)
        return _success(result.model_dump())

    @router.post("/api/deep-research/jobs")
    async def create_deep_research_job(
        payload: DeepResearchJobRequest,
        background_tasks: BackgroundTasks,
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_flag("KURO_DEEP_RESEARCH_V2_ENABLED", "Deep Research V2")
        service = _service()
        job = service.deep_research.create_job(
            username=user["username"],
            workspace_id=payload.workspace_id,
            query=payload.query,
        )
        background_tasks.add_task(service.deep_research.run_job, job.job_id)
        return _success(job.model_dump())

    @router.get("/api/deep-research/jobs/{job_id}")
    async def get_deep_research_job(
        job_id: str,
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_flag("KURO_DEEP_RESEARCH_V2_ENABLED", "Deep Research V2")
        service = _service()
        job = service.deep_research.get_job(job_id=job_id, username=user["username"])
        if job is None:
            raise HTTPException(status_code=404, detail="Research job not found")
        return _success(job.model_dump())

    @router.get("/api/deep-research/jobs")
    async def list_deep_research_jobs(
        workspace_id: Optional[str] = Query(default=None),
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_flag("KURO_DEEP_RESEARCH_V2_ENABLED", "Deep Research V2")
        service = _service()
        jobs = service.deep_research.list_jobs(username=user["username"], workspace_id=workspace_id)
        return _success([job.model_dump() for job in jobs])

    @router.post("/api/tasks")
    async def create_task(
        payload: TaskCreateRequest,
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_flag("KURO_TASKS_V2_ENABLED", "Tasks V2")
        service = _service()
        task = service.tasks.create_task(username=user["username"], **payload.model_dump(exclude={"metadata"}), metadata=payload.metadata)
        return _success(task)

    @router.get("/api/tasks")
    async def list_tasks(
        workspace_id: Optional[str] = Query(default=None),
        status: Optional[str] = Query(default=None),
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_flag("KURO_TASKS_V2_ENABLED", "Tasks V2")
        service = _service()
        return _success(service.tasks.list_tasks(username=user["username"], workspace_id=workspace_id, status=status))

    @router.patch("/api/tasks/{task_id}")
    async def patch_task(
        task_id: str,
        payload: TaskPatchRequest,
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_flag("KURO_TASKS_V2_ENABLED", "Tasks V2")
        service = _service()
        try:
            task = service.tasks.update_task(
                task_id=task_id,
                username=user["username"],
                patch=payload.model_dump(exclude_none=True),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return _success(task)

    @router.delete("/api/tasks/{task_id}")
    async def delete_task(
        task_id: str,
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_flag("KURO_TASKS_V2_ENABLED", "Tasks V2")
        service = _service()
        deleted = service.tasks.delete_task(task_id=task_id, username=user["username"])
        if not deleted:
            raise HTTPException(status_code=404, detail="Task not found")
        return _success({"deleted": True, "task_id": task_id})

    @router.post("/api/reminders")
    async def create_reminder(
        payload: ReminderCreateRequest,
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_flag("KURO_TASKS_V2_ENABLED", "Reminders V2")
        service = _service()
        reminder = service.reminders.create_reminder(
            username=user["username"],
            workspace_id=payload.workspace_id,
            remind_at=payload.remind_at,
            task_id=payload.task_id,
            channel=payload.channel,
            metadata=payload.metadata,
        )
        return _success(reminder)

    @router.get("/api/reminders")
    async def list_reminders(
        workspace_id: Optional[str] = Query(default=None),
        status: Optional[str] = Query(default=None),
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_flag("KURO_TASKS_V2_ENABLED", "Reminders V2")
        service = _service()
        return _success(service.reminders.list_reminders(username=user["username"], workspace_id=workspace_id, status=status))

    @router.patch("/api/reminders/{reminder_id}")
    async def patch_reminder(
        reminder_id: str,
        payload: ReminderPatchRequest,
        user: Dict[str, str] = Depends(auth_dependency),
    ):
        _require_flag("KURO_TASKS_V2_ENABLED", "Reminders V2")
        service = _service()
        try:
            reminder = service.reminders.update_reminder(
                reminder_id=reminder_id,
                username=user["username"],
                patch=payload.model_dump(exclude_none=True),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if reminder is None:
            raise HTTPException(status_code=404, detail="Reminder not found")
        return _success(reminder)

    @router.get("/api/admin/tools/audit")
    async def list_tool_audit(
        limit: int = Query(default=100, ge=1, le=500),
        _admin: Dict[str, str] = Depends(admin_dependency),
    ):
        service = _service()
        return _success([event.model_dump() for event in service.audit.list_events(limit=limit)])

    @router.get("/api/admin/tools/approvals")
    async def list_tool_approvals(
        limit: int = Query(default=100, ge=1, le=500),
        _admin: Dict[str, str] = Depends(admin_dependency),
    ):
        service = _service()
        return _success([approval.model_dump() for approval in service.approvals.list_pending(limit=limit)])

    @router.post("/api/admin/tools/approvals/{approval_id}/approve")
    async def approve_tool_request(
        approval_id: str,
        admin: Dict[str, str] = Depends(admin_dependency),
    ):
        service = _service()
        approval = service.approvals.approve(approval_id, decided_by=admin["username"])
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval request not found")
        service.audit.log_event(
            event_type="tool_approval_decision",
            tool_id=approval.tool_id,
            username=approval.username,
            runtime_id=approval.runtime_id,
            workspace_id=approval.workspace_id,
            status=approval.status,
            approval_id=approval.approval_id,
            payload={"decided_by": admin["username"]},
        )
        return _success(approval.model_dump())

    @router.post("/api/admin/tools/approvals/{approval_id}/deny")
    async def deny_tool_request(
        approval_id: str,
        admin: Dict[str, str] = Depends(admin_dependency),
    ):
        service = _service()
        approval = service.approvals.deny(approval_id, decided_by=admin["username"])
        if approval is None:
            raise HTTPException(status_code=404, detail="Approval request not found")
        service.audit.log_event(
            event_type="tool_approval_decision",
            tool_id=approval.tool_id,
            username=approval.username,
            runtime_id=approval.runtime_id,
            workspace_id=approval.workspace_id,
            status=approval.status,
            approval_id=approval.approval_id,
            payload={"decided_by": admin["username"]},
        )
        return _success(approval.model_dump())

    return router
