"""Policy enforcement for Tool Runtime V2."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from kuro_backend.tools_v2.registry import ToolRegistry, get_tool_registry
from kuro_backend.tools_v2.schemas import ToolActor, ToolDefinition


class ToolPolicyError(PermissionError):
    def __init__(self, code: str, message: str, *, status_code: int = 403) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ToolPolicy:
    def __init__(self, registry: Optional[ToolRegistry] = None) -> None:
        self.registry = registry or get_tool_registry()

    def can_list_tool(self, definition: ToolDefinition, actor: ToolActor) -> bool:
        if not self.registry.is_enabled(definition):
            return False
        if definition.requires_admin and not actor.is_admin:
            return False
        if actor.runtime_id not in definition.allowed_runtime_ids:
            return False
        actor_roles = set(actor.roles or [])
        return not definition.allowed_roles or bool(actor_roles.intersection(definition.allowed_roles))

    def can_execute_tool(self, definition: ToolDefinition, actor: ToolActor) -> bool:
        try:
            self.enforce_runtime_boundary(definition, actor)
            self._enforce_enabled(definition)
            self._enforce_roles(definition, actor)
            self.enforce_rate_limit(definition, actor)
            return True
        except ToolPolicyError:
            return False

    def enforce_can_execute(self, definition: ToolDefinition, actor: ToolActor) -> None:
        self.enforce_runtime_boundary(definition, actor)
        self._enforce_enabled(definition)
        self._enforce_roles(definition, actor)
        self.enforce_rate_limit(definition, actor)

    def requires_approval(self, definition: ToolDefinition, input_payload: Dict[str, Any]) -> bool:
        if definition.requires_approval or definition.risk_level in {"high", "critical"}:
            return True
        text = json.dumps(input_payload or {}, ensure_ascii=False).lower()
        destructive_markers = ("delete", "drop table", "truncate", "rm -rf", "shutdown", "reboot")
        return any(marker in text for marker in destructive_markers)

    def validate_input(self, definition: ToolDefinition, input_payload: Dict[str, Any]) -> None:
        schema = definition.input_schema or {}
        errors: List[str] = []
        if schema.get("type") == "object" and not isinstance(input_payload, dict):
            errors.append("input must be an object")
        required = schema.get("required") or []
        for field_name in required:
            if field_name not in (input_payload or {}) or input_payload.get(field_name) in (None, ""):
                errors.append(f"{field_name} is required")
        properties = schema.get("properties") or {}
        for field_name, field_schema in properties.items():
            if field_name not in (input_payload or {}) or input_payload.get(field_name) is None:
                continue
            value = input_payload.get(field_name)
            expected = field_schema.get("type")
            if expected == "string":
                if not isinstance(value, str):
                    errors.append(f"{field_name} must be a string")
                    continue
                if "minLength" in field_schema and len(value) < int(field_schema["minLength"]):
                    errors.append(f"{field_name} is too short")
                if "maxLength" in field_schema and len(value) > int(field_schema["maxLength"]):
                    errors.append(f"{field_name} is too long")
                if "enum" in field_schema and value not in set(field_schema["enum"]):
                    errors.append(f"{field_name} is not allowed")
            elif expected == "integer":
                if not isinstance(value, int) or isinstance(value, bool):
                    errors.append(f"{field_name} must be an integer")
                    continue
                if "minimum" in field_schema and value < int(field_schema["minimum"]):
                    errors.append(f"{field_name} is too small")
                if "maximum" in field_schema and value > int(field_schema["maximum"]):
                    errors.append(f"{field_name} is too large")
            elif expected == "number":
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    errors.append(f"{field_name} must be a number")
            elif expected == "boolean" and not isinstance(value, bool):
                errors.append(f"{field_name} must be a boolean")
            elif expected == "object" and not isinstance(value, dict):
                errors.append(f"{field_name} must be an object")
            elif expected == "array" and not isinstance(value, list):
                errors.append(f"{field_name} must be an array")
        if errors:
            raise ToolPolicyError("invalid_input", "; ".join(errors), status_code=400)

    def enforce_runtime_boundary(self, definition: ToolDefinition, actor: ToolActor) -> None:
        if actor.runtime_id not in definition.allowed_runtime_ids:
            raise ToolPolicyError(
                "runtime_not_allowed",
                f"Runtime {actor.runtime_id!r} cannot execute {definition.tool_id!r}.",
                status_code=403,
            )
    def enforce_rate_limit(self, definition: ToolDefinition, actor: ToolActor) -> None:
        return None

    def _enforce_enabled(self, definition: ToolDefinition) -> None:
        if not self.registry.is_enabled(definition):
            raise ToolPolicyError(
                "tool_disabled",
                "Requested tool is disabled by enterprise feature flag.",
                status_code=404,
            )

    def _enforce_roles(self, definition: ToolDefinition, actor: ToolActor) -> None:
        if definition.requires_admin and not actor.is_admin:
            raise ToolPolicyError(
                "admin_required",
                "Requested tool requires admin approval and execution.",
                status_code=403,
            )
        actor_roles = set(actor.roles or [])
        if definition.allowed_roles and not actor_roles.intersection(definition.allowed_roles):
            raise ToolPolicyError(
                "role_not_allowed",
                "Actor role is not allowed to execute this tool.",
                status_code=403,
            )
