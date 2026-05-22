"""Data catalog registry for known Kuro SQLite stores."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from kuro_backend.config import settings
from kuro_backend.storage.connection import resolve_sqlite_path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class StorageCatalogEntry:
    logical_store_id: str
    db_path: str
    owner_module: str
    tables: tuple[str, ...]
    pii_level: str
    retention_policy: str
    backup_tier: str
    enterprise_notes: str

    @property
    def required_for_runtime(self) -> bool:
        return self.backup_tier != "future"

    def resolved_path(self) -> Path:
        return resolve_sqlite_path(self.db_path)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["tables"] = list(self.tables)
        payload["required_for_runtime"] = self.required_for_runtime
        return payload


def _working_dir() -> Path:
    return Path(getattr(settings, "WORKING_DIR", "") or REPO_ROOT).expanduser().resolve()


def _path_in_working_dir(filename: str) -> str:
    return str(_working_dir() / filename)


def _finance_path() -> str:
    configured = getattr(settings, "KURO_FINANCE_DB_PATH", "") or ""
    if configured:
        return str(Path(configured).expanduser())
    return str(REPO_ROOT / "kuro_finances.db")


def list_catalog_entries() -> List[StorageCatalogEntry]:
    """Return the curated catalog of current and future SQLite stores."""
    return [
        StorageCatalogEntry(
            logical_store_id="auth",
            db_path=str(REPO_ROOT / "kuro_auth.db"),
            owner_module="kuro_backend.auth_db",
            tables=("users", "login_attempts", "user_sessions"),
            pii_level="medium",
            retention_policy="security_operational",
            backup_tier="tier1",
            enterprise_notes="Dashboard identity and login security store.",
        ),
        StorageCatalogEntry(
            logical_store_id="chat_history",
            db_path=_path_in_working_dir("kuro_chat_history.db"),
            owner_module="kuro_backend.chat_history",
            tables=("chat_history", "chat_sessions", "uploaded_file_integrity"),
            pii_level="high",
            retention_policy="user_conversation",
            backup_tier="tier1",
            enterprise_notes="Conversation, attachment integrity, and session metadata.",
        ),
        StorageCatalogEntry(
            logical_store_id="short_term",
            db_path=_path_in_working_dir("kuro_short_term.db"),
            owner_module="kuro_backend.memory_manager",
            tables=("short_term", "dreaming_locks", "facts", "mem0_write_failures"),
            pii_level="high",
            retention_policy="memory_operational",
            backup_tier="tier1",
            enterprise_notes="Legacy short-term and memory coordination store.",
        ),
        StorageCatalogEntry(
            logical_store_id="intelligence",
            db_path=str(REPO_ROOT / "kuro_intelligence.db"),
            owner_module="kuro_backend.intelligence_db",
            tables=(
                "intelligence_briefings",
                "audit_trail",
                "backup_logs",
                "failed_telegram_notifications",
            ),
            pii_level="medium",
            retention_policy="audit_and_intelligence",
            backup_tier="tier1",
            enterprise_notes="Briefings, audit events, backup status, and notification DLQ.",
        ),
        StorageCatalogEntry(
            logical_store_id="finance",
            db_path=_finance_path(),
            owner_module="kuro_backend.finance_db",
            tables=(
                "monthly_budgets",
                "recurring_expenses",
                "api_usage_daily",
                "watched_symbols",
                "market_briefs",
            ),
            pii_level="medium",
            retention_policy="financial_operational",
            backup_tier="tier1",
            enterprise_notes="Finance, cost, market watch, and fiscal sentinel store.",
        ),
        StorageCatalogEntry(
            logical_store_id="compliance",
            db_path=_path_in_working_dir("kuro_compliance.db"),
            owner_module="kuro_backend.compliance_db",
            tables=("evidence_matrix", "findings", "controls", "audit_log"),
            pii_level="medium",
            retention_policy="compliance_evidence",
            backup_tier="tier2",
            enterprise_notes="Compliance evidence and audit analysis store.",
        ),
        StorageCatalogEntry(
            logical_store_id="ingestion",
            db_path=str(REPO_ROOT / "kuro_ingestion.db"),
            owner_module="kuro_backend.ingestion_center.ingestion_registry",
            tables=("ingestion_datasets", "ingestion_jobs", "ingestion_chunks"),
            pii_level="medium",
            retention_policy="ingested_knowledge",
            backup_tier="tier2",
            enterprise_notes="Dataset registry, ingestion lifecycle, and chunk metadata.",
        ),
        StorageCatalogEntry(
            logical_store_id="memory_v3",
            db_path=_path_in_working_dir("kuro_memory_v3.db"),
            owner_module="kuro_backend.memory_v3",
            tables=("memory_events", "memory_items", "memory_links", "memory_read_audit"),
            pii_level="high",
            retention_policy="future_memory_governance",
            backup_tier="future",
            enterprise_notes="Future Memory V3 store; intentionally not required in Phase 1.",
        ),
    ]


def get_catalog_entry(logical_store_id: str) -> Optional[StorageCatalogEntry]:
    wanted = (logical_store_id or "").strip()
    for entry in list_catalog_entries():
        if entry.logical_store_id == wanted:
            return entry
    return None


def resolve_catalog_db_path(db_name: str) -> Path:
    entry = get_catalog_entry(db_name)
    if entry:
        return entry.resolved_path()
    raw = Path(os.path.expanduser(str(db_name)))
    if raw.is_absolute():
        return raw
    return (_working_dir() / raw).resolve()


def get_storage_catalog_snapshot(
    entries: Iterable[StorageCatalogEntry] | None = None,
) -> dict:
    selected = list(entries) if entries is not None else list_catalog_entries()
    return {
        "store_count": len(selected),
        "stores": [entry.to_dict() for entry in selected],
    }
