"""
Playground API schemas.

--- Header Doc ---
Purpose: Request/response contracts for KPR FastAPI routes.
Caller: playground_runtime.api.router.
Dependencies: pydantic.
Main Functions: Pydantic schema classes.
Side Effects: None.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    mode: str = Field(default="research")
    runtime_config_override: Optional[dict[str, Any]] = None
    session_id: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9._:-]{3,80}$")


class ExecuteRequest(BaseModel):
    session_id: str
    provider_id: str
    prompt: str
    dataset_version: Optional[str] = None
    model_override: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ComparativeExecuteRequest(BaseModel):
    session_id: str
    provider_ids: list[str]
    prompt: str
    dataset_version: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class OntologyRequest(BaseModel):
    session_id: str


class ReportRequest(BaseModel):
    session_id: str
    output_path: Optional[str] = None
