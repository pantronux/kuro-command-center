"""
Kuro AI V1.0.0 Beta 5 Hotfix - Backup Manager
================================================================================
Automated backup engine for Kuro runtime state and SQLite assets.

--- Header Doc ---
Purpose: Centralized backup/snapshot orchestration for critical runtime data.
Caller: main.py scheduler + admin routes, *_db.py pre-migration hooks.
Dependencies: sqlite3, gzip, shutil, pathlib, kuro_backend.config, kuro_backend.intelligence_db.
Main Functions: get_backup_dir, snapshot_pre_migration, run_nightly_backup,
run_manual_backup, get_backup_status, prune_old_backups.
Side Effects: Writes under backups/, reads runtime DB/JSON/directories, logs
audit trail to kuro_intelligence.db, optional Telegram alert on failure.
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from kuro_backend.config import settings

logger = logging.getLogger(__name__)
logger.propagate = False

_BACKUP_TIER1: Sequence[Tuple[str, str]] = (
    ("kuro_chat_history.db", "sqlite"),
    ("kuro_short_term.db", "sqlite"),
    ("kuro_auth.db", "sqlite"),
    ("kuro_finances.db", "sqlite"),
    ("kuro_intelligence.db", "sqlite"),
    ("master_profile.json", "file"),
    ("kuro_memory.json", "file"),
)
_BACKUP_TIER2: Sequence[Tuple[str, str]] = (
    ("kuro_compliance.db", "sqlite"),
    ("phoenix_data/phoenix.db", "sqlite"),
)
_BACKUP_DAILY_DIRS: Sequence[str] = ("logs",)
_BACKUP_WEEKLY_DIRS: Sequence[str] = ("kuro_chromadb", "uploaded_files")
_SQLITE_REQUIRED_CORE = {
    "kuro_chat_history.db",
    "kuro_short_term.db",
    "kuro_auth.db",
    "kuro_finances.db",
    "kuro_intelligence.db",
}


def _working_dir() -> Path:
    return Path(settings.WORKING_DIR or os.getcwd()).resolve()


def get_backup_dir() -> Path:
    """Returns resolved backups root directory, creating it if needed."""
    backup_dir = Path(settings.KURO_BACKUP_DIR).expanduser()
    if not backup_dir.is_absolute():
        backup_dir = (_working_dir() / backup_dir).resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def _now_local() -> datetime:
    return settings.get_current_time()


def _gzip_level() -> int:
    return max(1, min(9, int(settings.KURO_BACKUP_COMPRESS_LEVEL)))


def _manifest_path(target_dir: Path) -> Path:
    return target_dir / "backup_manifest.json"


def _serialize_dt(value: datetime) -> str:
    return value.isoformat()


def snapshot_pre_migration(db_path: str | Path, label: str = "") -> Path | None:
    """Create a compressed pre-migration DB snapshot if the source file exists."""
    source = Path(db_path).expanduser()
    if not source.is_absolute():
        source = (_working_dir() / source).resolve()
    if not source.exists():
        return None

    now = _now_local()
    backup_root = get_backup_dir() / "pre_migration"
    backup_root.mkdir(parents=True, exist_ok=True)
    suffix = f".{label}" if label else ""
    target = backup_root / (
        f"{source.name}{suffix}.pre_migration_{now.strftime('%Y%m%d_%H%M%S')}.gz"
    )

    try:
        with tempfile.TemporaryDirectory(dir=str(backup_root)) as tmp_dir:
            tmp_db = Path(tmp_dir) / source.name
            _vacuum_into(source, tmp_db)
            _compress_file(tmp_db, target)
        logger.info("Pre-migration snapshot created: %s", target)
    except Exception as exc:
        logger.warning("Pre-migration snapshot failed for %s: %s", source, exc)
        return None

    try:
        _prune_pre_migration_snapshots(settings.KURO_BACKUP_PRE_MIGRATION_RETAIN_DAYS)
    except Exception as exc:
        logger.warning("Pre-migration snapshot prune skipped: %s", exc)
    return target


async def run_nightly_backup() -> dict:
    """Async wrapper for the nightly backup job."""
    return await asyncio.to_thread(run_nightly_backup_sync)


def run_nightly_backup_sync() -> dict:
    """Run the nightly backup job synchronously."""
    return _run_backup_job("nightly")


def run_manual_backup(label: str = "manual") -> dict:
    """Run a manual backup synchronously."""
    return _run_backup_job("manual", label=label or "manual")


def get_backup_status() -> dict:
    """Return the most recent backup status entry."""
    try:
        from kuro_backend import intelligence_db

        return intelligence_db.get_last_backup_status() or {}
    except Exception as exc:
        logger.warning("Failed to fetch backup status: %s", exc)
        return {}


def get_backup_health() -> dict:
    """Return public-safe backup readiness metadata without raw paths."""
    latest = get_backup_status()
    docs_available = (
        _working_dir() / "docs" / "deployment" / "backup_restore.md"
    ).exists()
    age_hours = None
    last_status = str(latest.get("status") or "unknown")
    started_at = latest.get("started_at") or latest.get("completed_at")
    if started_at:
        try:
            parsed = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
            age_hours = round(max(0.0, (_now_local() - parsed).total_seconds() / 3600.0), 3)
        except Exception:
            age_hours = None
    return {
        "configured": bool(settings.KURO_BACKUP_ENABLED),
        "last_status": last_status,
        "last_backup_age_hours": age_hours,
        "restore_docs_available": docs_available,
    }


def prune_old_backups(retain_days: int | None = None) -> int:
    """Prune aged backup artefacts. Returns deleted directory/file count."""
    deleted = 0
    deleted += _prune_daily_backups(
        retain_days if retain_days is not None else settings.KURO_BACKUP_RETAIN_DAYS
    )
    deleted += _prune_weekly_backups(settings.KURO_BACKUP_WEEKLY_RETAIN_WEEKS)
    deleted += _prune_pre_migration_snapshots(
        settings.KURO_BACKUP_PRE_MIGRATION_RETAIN_DAYS
    )
    return deleted


def _run_backup_job(backup_type: str, label: str = "") -> Dict[str, Any]:
    start = time.monotonic()
    started_at = _now_local()
    backup_root = get_backup_dir()
    daily_dir = backup_root / "daily" / started_at.strftime("%Y-%m-%d")
    daily_dir.mkdir(parents=True, exist_ok=True)

    errors: List[str] = []
    files: List[str] = []
    files_backed_up = 0
    total_size_bytes = 0
    core_successes = 0
    checksums: Dict[str, str] = {}
    integrity_failed = False

    try:
        from kuro_backend import intelligence_db
    except Exception as exc:
        intelligence_db = None
        errors.append(f"intelligence_db import failed: {exc}")

    log_id: Optional[int] = None
    if intelligence_db is not None:
        try:
            log_id = intelligence_db.log_backup_start(backup_type, str(daily_dir))
        except Exception as exc:
            errors.append(f"backup_log start failed: {exc}")

    for relative_path, asset_type in list(_BACKUP_TIER1) + list(_BACKUP_TIER2):
        source = (_working_dir() / relative_path).resolve()
        dest_name = f"{Path(relative_path).name}.gz"
        dest = daily_dir / dest_name
        required_core = Path(relative_path).name in _SQLITE_REQUIRED_CORE
        try:
            if asset_type == "sqlite":
                if not source.exists():
                    raise FileNotFoundError(source)
                with tempfile.TemporaryDirectory(dir=str(daily_dir)) as tmp_dir:
                    tmp_db = Path(tmp_dir) / Path(relative_path).name
                    _vacuum_into(source, tmp_db)
                    size = _compress_file(tmp_db, dest)
            else:
                if not source.exists():
                    raise FileNotFoundError(source)
                size = _copy_json_or_file(source, dest)
            files.append(dest.name)
            files_backed_up += 1
            total_size_bytes += size
            checksums[dest.name] = _sha256_file(dest)
            if required_core:
                core_successes += 1
        except FileNotFoundError:
            errors.append(f"missing asset: {relative_path}")
        except Exception as exc:
            if "Backup integrity check failed" in str(exc):
                integrity_failed = True
                logger.critical("[BACKUP] Integrity verification failed for %s: %s", relative_path, exc)
            errors.append(f"backup failed for {relative_path}: {exc}")

    for relative_dir in _BACKUP_DAILY_DIRS:
        source_dir = (_working_dir() / relative_dir).resolve()
        dest = daily_dir / f"{Path(relative_dir).name}.tar.gz"
        try:
            if not source_dir.exists():
                raise FileNotFoundError(source_dir)
            size = _copy_directory_archive(source_dir, dest)
            files.append(dest.name)
            files_backed_up += 1
            total_size_bytes += size
            checksums[dest.name] = _sha256_file(dest)
        except FileNotFoundError:
            errors.append(f"missing asset: {relative_dir}")
        except Exception as exc:
            errors.append(f"backup failed for {relative_dir}: {exc}")

    weekly_files: List[str] = []
    if started_at.weekday() == 6:
        iso_year, iso_week, _ = started_at.isocalendar()
        weekly_dir = backup_root / "weekly" / f"{iso_year}-W{iso_week:02d}"
        weekly_dir.mkdir(parents=True, exist_ok=True)
        for relative_dir in _BACKUP_WEEKLY_DIRS:
            source_dir = (_working_dir() / relative_dir).resolve()
            dest_dir = weekly_dir / Path(relative_dir).name
            try:
                if not source_dir.exists():
                    raise FileNotFoundError(source_dir)
                size = _copy_directory_snapshot(source_dir, dest_dir)
                files_backed_up += 1
                total_size_bytes += size
                weekly_files.append(str(dest_dir.relative_to(weekly_dir)))
            except FileNotFoundError:
                errors.append(f"missing weekly asset: {relative_dir}")
            except Exception as exc:
                errors.append(f"weekly backup failed for {relative_dir}: {exc}")

    status = "success"
    if errors:
        status = "partial"
    if core_successes == 0:
        status = "failed"
    if integrity_failed:
        status = "failed"
    if log_id is None and intelligence_db is None:
        status = "failed"

    duration_seconds = round(time.monotonic() - start, 3)
    manifest = {
        "backup_type": backup_type,
        "label": label or backup_type,
        "timestamp": _serialize_dt(started_at),
        "backup_path": str(daily_dir),
        "status": status,
        "files": files + weekly_files,
        "files_backed_up": files_backed_up,
        "total_size_bytes": total_size_bytes,
        "total_size_mb": round(total_size_bytes / (1024 * 1024), 3),
        "duration_seconds": duration_seconds,
        "errors": errors,
        "checksums": checksums,
    }
    _manifest_path(daily_dir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    try:
        prune_old_backups()
    except Exception as exc:
        logger.warning("Backup prune skipped: %s", exc)

    if intelligence_db is not None and log_id is not None:
        try:
            intelligence_db.log_backup_complete(
                log_id,
                status,
                files_backed_up,
                total_size_bytes,
                duration_seconds,
                "\n".join(errors) if errors else None,
            )
        except Exception as exc:
            logger.warning("backup_log completion failed: %s", exc)
            if status == "success":
                status = manifest["status"] = "partial"
                errors.append(f"backup_log completion failed: {exc}")

    if status == "failed" and settings.KURO_BACKUP_ALERT_ON_FAILURE:
        _notify_failure(manifest)

    logger.info(
        "[BACKUP] %s backup %s - files=%s size_bytes=%s duration=%.3fs",
        backup_type,
        status,
        files_backed_up,
        total_size_bytes,
        duration_seconds,
    )
    return manifest


def _notify_failure(manifest: Dict[str, Any]) -> None:
    try:
        import asyncio
        from kuro_backend import telegram_notifier

        first_error = manifest.get("errors", ["unknown error"])[0]
        asyncio.run(
            telegram_notifier.send_message_with_retry(
                "[BACKUP] FAILED\n"
                f"path={manifest.get('backup_path')}\n"
                f"error={first_error}"
            )
        )
    except Exception as exc:
        logger.warning("Backup failure alert skipped: %s", exc)


def _vacuum_into(source_db: Path, dest_path: Path) -> int:
    """WAL-safe SQLite snapshot via VACUUM INTO."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists():
        dest_path.unlink()
    conn = sqlite3.connect(str(source_db))
    try:
        quoted_dest = str(dest_path).replace("'", "''")
        conn.execute(f"VACUUM INTO '{quoted_dest}'")
        conn.commit()
    finally:
        conn.close()
    _validate_backup_integrity(dest_path)
    return dest_path.stat().st_size


def _sha256_file(path: Path) -> str:
    """Return SHA-256 hex digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_backup_integrity(backup_path: Path) -> None:
    """Validate a sqlite backup file with PRAGMA integrity_check."""
    verify_conn = sqlite3.connect(str(backup_path))
    try:
        result = verify_conn.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as exc:
        raise RuntimeError(f"Backup integrity check failed for {backup_path}: {exc}") from exc
    finally:
        verify_conn.close()
    if not result or result[0] != "ok":
        raise RuntimeError(
            f"Backup integrity check failed for {backup_path}: {result[0] if result else 'unknown'}"
        )


def _compress_file(source: Path, dest: Path) -> int:
    """Gzip compress source file to dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, gzip.open(
        dest, "wb", compresslevel=_gzip_level()
    ) as gz:
        shutil.copyfileobj(src, gz)
    return dest.stat().st_size


def _copy_json_or_file(source: Path, dest_gz: Path) -> int:
    """Copy a non-SQLite file into a gzip archive."""
    dest_gz.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, gzip.open(
        dest_gz, "wb", compresslevel=_gzip_level()
    ) as gz:
        shutil.copyfileobj(src, gz)
    return dest_gz.stat().st_size


def _copy_directory_snapshot(source_dir: Path, dest_dir: Path) -> int:
    """Copy a directory tree for weekly snapshots."""
    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    shutil.copytree(
        source_dir,
        dest_dir,
        ignore=shutil.ignore_patterns("*.lock", "__pycache__"),
    )
    total = 0
    for child in dest_dir.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _copy_directory_archive(source_dir: Path, dest_tar_gz: Path) -> int:
    """Create a compressed tar archive for a directory tree."""
    dest_tar_gz.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest_tar_gz, "w:gz") as tar:
        tar.add(
            source_dir,
            arcname=source_dir.name,
            filter=_tarinfo_filter,
        )
    return dest_tar_gz.stat().st_size


def _tarinfo_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    name = tarinfo.name
    basename = Path(name).name
    if basename == "__pycache__" or basename.endswith(".lock"):
        return None
    return tarinfo


def _prune_daily_backups(retain_days: int) -> int:
    deleted = 0
    cutoff = _now_local().date() - timedelta(days=max(0, int(retain_days)))
    daily_root = get_backup_dir() / "daily"
    if not daily_root.exists():
        return 0
    for child in daily_root.iterdir():
        if not child.is_dir():
            continue
        try:
            day = datetime.strptime(child.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            deleted += 1
    return deleted


def _prune_pre_migration_snapshots(retain_days: int) -> int:
    deleted = 0
    cutoff = _now_local() - timedelta(days=max(0, int(retain_days)))
    root = get_backup_dir() / "pre_migration"
    if not root.exists():
        return 0
    for child in root.iterdir():
        if not child.is_file():
            continue
        try:
            if datetime.fromtimestamp(child.stat().st_mtime, tz=cutoff.tzinfo) < cutoff:
                child.unlink(missing_ok=True)
                deleted += 1
        except Exception:
            continue
    return deleted


def _prune_weekly_backups(retain_weeks: int) -> int:
    deleted = 0
    weekly_root = get_backup_dir() / "weekly"
    if not weekly_root.exists():
        return 0
    cutoff = _now_local().date() - timedelta(weeks=max(0, int(retain_weeks)))
    for child in weekly_root.iterdir():
        if not child.is_dir():
            continue
        try:
            year_str, week_str = child.name.split("-W", 1)
            year = int(year_str)
            week = int(week_str)
            week_date = datetime.fromisocalendar(year, max(1, min(53, week)), 1).date()
        except Exception:
            continue
        if week_date < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            deleted += 1
    return deleted
