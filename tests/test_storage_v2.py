"""Storage Foundation V2 guardrail tests."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import types
from pathlib import Path

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

import main
from kuro_backend.storage.data_catalog import (
    StorageCatalogEntry,
    get_storage_catalog_snapshot,
)
from kuro_backend.storage.health import check_store_health
from kuro_backend.storage.migrations import (
    ensure_column,
    ensure_index,
    ensure_table,
    get_migration_history,
    record_migration,
)


def _auth_client(monkeypatch, username: str) -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def test_storage_migration_history_idempotency(tmp_path):
    db_path = tmp_path / "migration_history.db"

    record_migration(str(db_path), 1, "initial baseline")
    record_migration(str(db_path), 1, "initial baseline duplicated")

    history = get_migration_history(str(db_path))
    assert len(history) == 1
    assert history[0]["version"] == 1
    assert history[0]["description"] == "initial baseline"


def test_storage_ensure_column_run_twice(tmp_path):
    db_path = tmp_path / "columns.db"
    conn = sqlite3.connect(db_path)
    try:
        ensure_table(conn, "CREATE TABLE IF NOT EXISTS sample (id INTEGER PRIMARY KEY)")

        first = ensure_column(conn, "sample", "status", "TEXT DEFAULT 'new'")
        second = ensure_column(conn, "sample", "status", "TEXT DEFAULT 'new'")

        columns = [row[1] for row in conn.execute("PRAGMA table_info(sample)").fetchall()]
        assert first is True
        assert second is False
        assert columns.count("status") == 1
    finally:
        conn.close()


def test_storage_ensure_index_run_twice(tmp_path):
    db_path = tmp_path / "indexes.db"
    conn = sqlite3.connect(db_path)
    try:
        ensure_table(conn, "CREATE TABLE IF NOT EXISTS sample (id INTEGER PRIMARY KEY, status TEXT)")

        first = ensure_index(conn, "idx_sample_status", "sample", "status")
        second = ensure_index(conn, "idx_sample_status", "sample", "status")

        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
            ("idx_sample_status",),
        ).fetchall()
        assert first is True
        assert second is False
        assert len(indexes) == 1
    finally:
        conn.close()


def test_storage_catalog_does_not_expose_secrets():
    snapshot = get_storage_catalog_snapshot()
    serialized = json.dumps(snapshot, sort_keys=True).lower()

    forbidden = [
        "api_key",
        "token_secret",
        "password_hash",
        "jwt_secret",
        ".env",
    ]
    for fragment in forbidden:
        assert fragment not in serialized


def test_admin_storage_routes_require_admin(monkeypatch):
    routes = [
        "/api/admin/storage/health",
        "/api/admin/storage/catalog",
        "/api/admin/storage/migrations",
    ]

    anonymous = TestClient(main.app)
    for route in routes:
        assert anonymous.get(route).status_code == 401

    non_admin = _auth_client(monkeypatch, "Faikhira")
    for route in routes:
        response = non_admin.get(route, cookies={main.COOKIE_NAME: "Bearer dummy"})
        assert response.status_code == 403

    admin = _auth_client(monkeypatch, "Pantronux")
    for route in routes:
        response = admin.get(route, cookies={main.COOKIE_NAME: "Bearer dummy"})
        assert response.status_code == 200
        assert response.json()["status"] == "success"


def test_storage_health_handles_missing_optional_db_gracefully(tmp_path):
    entry = StorageCatalogEntry(
        logical_store_id="memory_v3",
        db_path=str(tmp_path / "missing_memory_v3.db"),
        owner_module="kuro_backend.memory_v3",
        tables=("memory_events",),
        pii_level="high",
        retention_policy="future_memory_governance",
        backup_tier="future",
        enterprise_notes="Future optional store.",
    )

    health = check_store_health(entry)

    assert health["exists"] is False
    assert health["required_for_runtime"] is False
    assert health["status"] == "optional_missing"
