"""Tool Registry V2 definitions and lookup helpers."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from kuro_backend.enterprise_flags import is_enabled
from kuro_backend.tools_v2.schemas import ToolActor, ToolDefinition


def _object_schema(required: List[str], properties: Dict[str, Dict]) -> Dict:
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": True,
    }


DEFAULT_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        tool_id="web_search",
        display_name="Web Search",
        description="Search the web through the configured Serper adapter and return normalized sources.",
        category="search",
        risk_level="low",
        requires_approval=False,
        requires_admin=False,
        allowed_runtime_ids=["sovereign", "research"],
        allowed_roles=["user", "admin"],
        input_schema=_object_schema(
            ["query"],
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 1000},
                "search_type": {"type": "string", "enum": ["search", "news", "scholar"]},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        ),
        output_schema={"type": "object"},
        timeout_s=30,
        budget_cost=1,
        enabled_flag="KURO_WEB_SEARCH_V2_ENABLED",
    ),
    ToolDefinition(
        tool_id="deep_research",
        display_name="Deep Research",
        description="Create and run a Kuro-native research job with source provenance.",
        category="research",
        risk_level="medium",
        requires_approval=False,
        requires_admin=False,
        allowed_runtime_ids=["sovereign", "research"],
        allowed_roles=["user", "admin"],
        input_schema=_object_schema(
            ["query"],
            {
                "query": {"type": "string", "minLength": 1, "maxLength": 2000},
                "workspace_id": {"type": "string", "maxLength": 128},
                "max_sources": {"type": "integer", "minimum": 1, "maximum": 20},
            },
        ),
        output_schema={"type": "object"},
        timeout_s=120,
        budget_cost=3,
        enabled_flag="KURO_DEEP_RESEARCH_V2_ENABLED",
    ),
    ToolDefinition(
        tool_id="create_task",
        display_name="Create Task",
        description="Create a clean Tasks V2 record for the current user.",
        category="productivity",
        risk_level="low",
        requires_approval=False,
        requires_admin=False,
        allowed_runtime_ids=["sovereign"],
        allowed_roles=["user", "admin"],
        input_schema=_object_schema(
            ["title"],
            {
                "title": {"type": "string", "minLength": 1, "maxLength": 500},
                "description": {"type": "string", "maxLength": 4000},
                "due_at": {"type": "string", "maxLength": 128},
                "recurrence_rule": {"type": "string", "maxLength": 256},
                "source_chat_id": {"type": "string", "maxLength": 128},
                "source_message_id": {"type": "string", "maxLength": 128},
                "metadata": {"type": "object"},
            },
        ),
        output_schema={"type": "object"},
        timeout_s=10,
        budget_cost=1,
        enabled_flag="KURO_TASKS_V2_ENABLED",
    ),
    ToolDefinition(
        tool_id="create_reminder",
        display_name="Create Reminder",
        description="Create a clean Reminders V2 record without using the removed legacy module.",
        category="productivity",
        risk_level="medium",
        requires_approval=False,
        requires_admin=False,
        allowed_runtime_ids=["sovereign"],
        allowed_roles=["user", "admin"],
        input_schema=_object_schema(
            ["remind_at"],
            {
                "remind_at": {"type": "string", "minLength": 1, "maxLength": 128},
                "task_id": {"type": "string", "maxLength": 128},
                "channel": {"type": "string", "enum": ["web", "telegram", "both"]},
                "metadata": {"type": "object"},
            },
        ),
        output_schema={"type": "object"},
        timeout_s=10,
        budget_cost=1,
        enabled_flag="KURO_TASKS_V2_ENABLED",
    ),
    ToolDefinition(
        tool_id="agent_mode",
        display_name="Agent Mode",
        description="Run a limited, traceable multi-step planning loop governed by tool policy.",
        category="agent",
        risk_level="high",
        requires_approval=True,
        requires_admin=False,
        allowed_runtime_ids=["sovereign", "research"],
        allowed_roles=["user", "admin"],
        input_schema=_object_schema(
            ["goal"],
            {
                "goal": {"type": "string", "minLength": 1, "maxLength": 4000},
                "requested_steps": {"type": "integer", "minimum": 1, "maximum": 50},
                "allowed_tool_ids": {"type": "array"},
            },
        ),
        output_schema={"type": "object"},
        timeout_s=60,
        budget_cost=5,
        enabled_flag="KURO_AGENT_TOOLS_V2_ENABLED",
    ),
    ToolDefinition(
        tool_id="openclaw_bridge",
        display_name="OpenClaw Bridge",
        description="Delegate explicitly approved execution to the existing OpenClaw bridge and safety circuit.",
        category="execution",
        risk_level="critical",
        requires_approval=True,
        requires_admin=True,
        allowed_runtime_ids=["sovereign", "research", "forensic"],
        allowed_roles=["admin"],
        input_schema=_object_schema(
            ["skill_name"],
            {
                "skill_name": {"type": "string", "minLength": 1, "maxLength": 128},
                "params": {"type": "object"},
            },
        ),
        output_schema={"type": "object"},
        timeout_s=60,
        budget_cost=10,
        enabled_flag="KURO_AGENT_TOOLS_V2_ENABLED",
    ),
)


class ToolRegistry:
    def __init__(self, definitions: Optional[Iterable[ToolDefinition]] = None) -> None:
        self._definitions: Dict[str, ToolDefinition] = {
            definition.tool_id: definition
            for definition in (definitions or DEFAULT_TOOL_DEFINITIONS)
        }

    def get(self, tool_id: str) -> Optional[ToolDefinition]:
        return self._definitions.get(str(tool_id or "").strip())

    def all(self) -> List[ToolDefinition]:
        return list(self._definitions.values())

    def is_enabled(self, definition: ToolDefinition) -> bool:
        if not definition.enabled_flag:
            return True
        return is_enabled(definition.enabled_flag)

    def list_visible(self, actor: ToolActor) -> List[ToolDefinition]:
        visible: List[ToolDefinition] = []
        actor_roles = set(actor.roles or [])
        for definition in self.all():
            if not self.is_enabled(definition):
                continue
            if definition.requires_admin and not actor.is_admin:
                continue
            if actor.runtime_id not in definition.allowed_runtime_ids:
                continue
            if definition.allowed_roles and not actor_roles.intersection(definition.allowed_roles):
                continue
            visible.append(definition)
        return visible


_REGISTRY: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ToolRegistry()
    return _REGISTRY


def reset_tool_registry_for_tests(registry: Optional[ToolRegistry] = None) -> None:
    global _REGISTRY
    _REGISTRY = registry
