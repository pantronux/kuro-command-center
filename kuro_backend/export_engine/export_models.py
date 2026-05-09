from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ExportTarget(str, Enum):
    CHAT_SESSION = "chat_session"
    SELECTED_MESSAGES = "selected_messages"
    INTELLIGENCE_REPORT = "intelligence_report"
    COMPLIANCE_REPORT = "compliance_report"
    MARKET_SNAPSHOT = "market_snapshot"


class ExportFormat(str, Enum):
    MD = "md"
    TXT = "txt"
    JSON = "json"
    PDF = "pdf"
    CSV = "csv"
    XLSX = "xlsx"
    DOCX = "docx"


class ExportStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ExportRequest(BaseModel):
    target: ExportTarget
    format: ExportFormat
    chat_id: str | None = None
    message_ids: list[int] = Field(default_factory=list)
    include_metadata: bool = True
    briefing_date: str | None = None
    standard: str | None = None


class ExportSection(BaseModel):
    heading: str
    body: str


class ExportTable(BaseModel):
    title: str
    columns: list[str]
    rows: list[list[str]]


class ExportPayload(BaseModel):
    title: str
    export_type: str
    username: str
    source_chat_id: str | None
    metadata: dict[str, Any]
    sections: list[ExportSection] = Field(default_factory=list)
    tables: list[ExportTable] = Field(default_factory=list)
    transcript: list[dict[str, Any]] = Field(default_factory=list)
