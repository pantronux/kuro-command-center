from __future__ import annotations

import gzip
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from kuro_backend import backup_manager, chat_history, intelligence_db, memory_manager
from kuro_backend.config import settings


def _write_sqlite(path: Path, value: str = "ok") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS demo (value TEXT)")
        conn.execute("DELETE FROM demo")
        conn.execute("INSERT INTO demo(value) VALUES (?)", (value,))
        conn.commit()
    finally:
        conn.close()


def _prepare_runtime_assets(tmp_path: Path, *, include_optional: bool = True) -> None:
    for name in (
        "kuro_chat_history.db",
        "kuro_short_term.db",
        "kuro_auth.db",
        "kuro_finances.db",
        "kuro_intelligence.db",
    ):
        _write_sqlite(tmp_path / name, value=name)
    if include_optional:
        _write_sqlite(tmp_path / "kuro_compliance.db", value="compliance")
        _write_sqlite(tmp_path / "phoenix_data" / "phoenix.db", value="phoenix")

    (tmp_path / "master_profile.json").write_text(
        json.dumps({"users": {"Pantronux": {"preferences": {}}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (tmp_path / "kuro_memory.json").write_text("{}", encoding="utf-8")


def _configure_backup_settings(tmp_path: Path, monkeypatch) -> Path:
    backup_dir = tmp_path / "backups"
    monkeypatch.setattr(settings, "WORKING_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "KURO_BACKUP_DIR", str(backup_dir), raising=False)
    monkeypatch.setattr(settings, "KURO_BACKUP_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KURO_BACKUP_ALERT_ON_FAILURE", False, raising=False)
    monkeypatch.setattr(settings, "KURO_BACKUP_RETAIN_DAYS", 30, raising=False)
    monkeypatch.setattr(settings, "KURO_BACKUP_WEEKLY_RETAIN_WEEKS", 8, raising=False)
    monkeypatch.setattr(
        settings, "KURO_BACKUP_PRE_MIGRATION_RETAIN_DAYS", 7, raising=False
    )
    monkeypatch.setattr(settings, "KURO_BACKUP_COMPRESS_LEVEL", 6, raising=False)
    monkeypatch.setattr(intelligence_db, "DB_PATH", str(tmp_path / "kuro_intelligence.db"), raising=False)
    intelligence_db._reset_schema_ready_for_tests()
    intelligence_db.init_db()
    return backup_dir


def test_snapshot_pre_migration_creates_gz_file(tmp_path, monkeypatch):
    _configure_backup_settings(tmp_path, monkeypatch)
    db_path = tmp_path / "sample.db"
    _write_sqlite(db_path, value="snapshot")

    snapshot = backup_manager.snapshot_pre_migration(db_path, label="unit")

    assert snapshot is not None
    assert snapshot.exists()
    with gzip.open(snapshot, "rb") as fh:
        data = fh.read()
    assert data.startswith(b"SQLite format 3")


def test_snapshot_pre_migration_skips_if_db_not_exist(tmp_path, monkeypatch):
    _configure_backup_settings(tmp_path, monkeypatch)
    snapshot = backup_manager.snapshot_pre_migration(tmp_path / "missing.db", label="unit")
    assert snapshot is None


def test_snapshot_pre_migration_never_raises(tmp_path, monkeypatch):
    _configure_backup_settings(tmp_path, monkeypatch)
    db_path = tmp_path / "sample.db"
    _write_sqlite(db_path, value="snapshot")
    monkeypatch.setattr(
        backup_manager,
        "_vacuum_into",
        lambda source, dest: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    snapshot = backup_manager.snapshot_pre_migration(db_path, label="unit")

    assert snapshot is None


def test_run_manual_backup_backs_up_tier1_sqlite_and_json(tmp_path, monkeypatch):
    backup_dir = _configure_backup_settings(tmp_path, monkeypatch)
    _prepare_runtime_assets(tmp_path)

    result = backup_manager.run_manual_backup()

    daily_dir = backup_dir / "daily" / settings.get_current_time().strftime("%Y-%m-%d")
    assert result["status"] in {"success", "partial"}
    assert (daily_dir / "kuro_chat_history.db.gz").exists()
    assert (daily_dir / "kuro_short_term.db.gz").exists()
    assert (daily_dir / "master_profile.json.gz").exists()
    assert (daily_dir / "kuro_memory.json.gz").exists()


def test_run_manual_backup_writes_manifest_json(tmp_path, monkeypatch):
    backup_dir = _configure_backup_settings(tmp_path, monkeypatch)
    _prepare_runtime_assets(tmp_path)

    result = backup_manager.run_manual_backup()

    daily_dir = backup_dir / "daily" / settings.get_current_time().strftime("%Y-%m-%d")
    manifest = json.loads((daily_dir / "backup_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == result["status"]
    assert manifest["files_backed_up"] == result["files_backed_up"]
    assert "kuro_chat_history.db.gz" in manifest["files"]


def test_run_manual_backup_logs_to_backup_log_table(tmp_path, monkeypatch):
    _configure_backup_settings(tmp_path, monkeypatch)
    _prepare_runtime_assets(tmp_path)

    backup_manager.run_manual_backup()

    history = intelligence_db.get_backup_history(limit=5)
    assert history
    assert history[0]["backup_type"] == "manual"


def test_run_manual_backup_partial_on_missing_optional_file(tmp_path, monkeypatch):
    _configure_backup_settings(tmp_path, monkeypatch)
    _prepare_runtime_assets(tmp_path, include_optional=False)

    result = backup_manager.run_manual_backup()

    assert result["status"] == "partial"
    assert any("missing asset:" in err for err in result["errors"])
    assert any(
        missing in "\n".join(result["errors"])
        for missing in ("kuro_compliance.db", "phoenix_data/phoenix.db")
    )


def test_prune_old_backups_deletes_old_daily_dirs(tmp_path, monkeypatch):
    backup_dir = _configure_backup_settings(tmp_path, monkeypatch)
    old_dir = backup_dir / "daily" / "2020-01-01"
    old_dir.mkdir(parents=True, exist_ok=True)

    deleted = backup_manager.prune_old_backups(retain_days=1)

    assert deleted >= 1
    assert not old_dir.exists()


def test_prune_old_backups_keeps_recent_daily_dirs(tmp_path, monkeypatch):
    backup_dir = _configure_backup_settings(tmp_path, monkeypatch)
    recent_dir = backup_dir / "daily" / settings.get_current_time().strftime("%Y-%m-%d")
    recent_dir.mkdir(parents=True, exist_ok=True)

    backup_manager.prune_old_backups(retain_days=14)

    assert recent_dir.exists()


def test_get_backup_status_returns_last_run(tmp_path, monkeypatch):
    _configure_backup_settings(tmp_path, monkeypatch)
    _prepare_runtime_assets(tmp_path)

    backup_manager.run_manual_backup()

    status = backup_manager.get_backup_status()
    assert status["backup_type"] == "manual"


def test_get_backup_history_returns_recent_runs(tmp_path, monkeypatch):
    _configure_backup_settings(tmp_path, monkeypatch)
    _prepare_runtime_assets(tmp_path)

    backup_manager.run_manual_backup("manual-a")
    backup_manager.run_nightly_backup_sync()

    history = intelligence_db.get_backup_history(limit=5)
    assert len(history) >= 2
    assert {row["backup_type"] for row in history[:2]} <= {"manual", "nightly"}


def test_backup_dir_created_if_not_exists(tmp_path, monkeypatch):
    backup_dir = _configure_backup_settings(tmp_path, monkeypatch)

    root = backup_manager.get_backup_dir()

    assert root == backup_dir
    assert root.exists()


def test_isolate_all_dbs_fixture_prevents_production_write(tmp_path):
    production_db = Path(__file__).resolve().parents[1] / "kuro_chat_history.db"
    before = production_db.stat() if production_db.exists() else None

    chat_history._reset_schema_ready_for_tests()
    chat_history.init_db()
    memory_manager._reset_short_term_schema_ready_for_tests()
    memory_manager.init_short_term_db()

    assert Path(chat_history.DB_PATH).is_relative_to(tmp_path)
    assert Path(memory_manager.SHORT_TERM_DB).is_relative_to(tmp_path)
    assert Path(chat_history.DB_PATH).exists()
    assert Path(memory_manager.SHORT_TERM_DB).exists()

    after = production_db.stat() if production_db.exists() else None
    if before and after:
        assert before.st_mtime_ns == after.st_mtime_ns
        assert before.st_size == after.st_size
