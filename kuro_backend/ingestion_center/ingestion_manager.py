from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, UploadFile

from kuro_backend import dashboard_broadcast, semantic_cache
from kuro_backend.config import settings

from . import ingestion_registry
from .chroma_inspector import find_orphan_chunks, get_collection_health, get_dataset_vector_health
from .ingestion_audit import log_lineage
from .ingestion_pipeline import run_ingestion, run_reindex
from .ingestion_security import ALLOWED_EXTENSIONS, compute_sha256, save_upload_file
from .retrieval_analytics import get_dataset_analytics, get_top_retrieved_datasets

logger = logging.getLogger(__name__)


def _normalize_tags(raw_tags: str | List[str] | None) -> List[str]:
    if raw_tags is None:
        return []
    if isinstance(raw_tags, list):
        return [item.strip() for item in raw_tags if item and item.strip()]
    return [item.strip() for item in str(raw_tags).split(",") if item.strip()]


def _notify_refresh() -> None:
    try:
        dashboard_broadcast.schedule_ui_command("STATUS_TICKER", {"message": "Ingestion center updated."})
    except Exception:
        pass


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _ingestion_source_dir(username: str) -> Path:
    return Path(settings.WORKING_DIR) / "uploaded_files" / username / "ingestion_center"


def _create_dataset_record(
    *,
    username: str,
    original_filename: str,
    stored_path: str,
    sha256_hash: str,
    size_bytes: int,
    category: str,
    tags: str | List[str] = "",
    memory_scope: str = "chroma_only",
    source_type: Optional[str] = None,
    source_origin: str = "upload",
) -> Dict[str, Any]:
    dataset_uuid = str(uuid.uuid4())
    return ingestion_registry.create_dataset(
        {
            "dataset_uuid": dataset_uuid,
            "dataset_name": os.path.splitext(original_filename)[0],
            "original_filename": original_filename,
            "file_path": stored_path,
            "file_hash_sha256": sha256_hash,
            "source_type": source_type or Path(original_filename).suffix.lstrip("."),
            "category": category,
            "owner_username": username,
            "ingestion_status": "queued",
            "memory_scope": memory_scope,
            "tags": _normalize_tags(tags),
            "metadata": {
                "size_bytes": size_bytes,
                "source_origin": source_origin,
            },
        }
    )


def create_ingestion_job(dataset_uuid: str, username: str, job_type: str = "ingest") -> Dict[str, Any]:
    return ingestion_registry.create_job(dataset_uuid, username, job_type, status="queued")


def schedule_ingestion_job(background_tasks: Optional[BackgroundTasks], job_id: int) -> None:
    if background_tasks is None:
        process_ingestion_job(job_id)
        return
    background_tasks.add_task(process_ingestion_job, job_id)


def process_ingestion_job(job_id: int) -> Optional[Dict[str, Any]]:
    job = ingestion_registry.get_job(job_id)
    if job is None:
        logger.warning("Skipping missing ingestion job_id=%s", job_id)
        return None
    dataset_uuid = job.get("dataset_uuid")
    username = job.get("username") or ""
    job_type = job.get("job_type") or "ingest"
    try:
        if job_type == "reindex":
            result = run_reindex(dataset_uuid, username, job_id=job_id)
            semantic_cache.invalidate_tag(f"dataset:{dataset_uuid}")
        else:
            result = run_ingestion(dataset_uuid, username, job_id=job_id)
        return result
    except Exception as exc:
        logger.exception("Ingestion job failed job_id=%s dataset_uuid=%s", job_id, dataset_uuid)
        ingestion_registry.update_job(
            job_id,
            status="failed",
            completed_at=ingestion_registry.now_iso(),
            error_message=str(exc),
        )
        if dataset_uuid:
            ingestion_registry.update_dataset(
                dataset_uuid,
                ingestion_status="failed",
                last_error=str(exc),
            )
            log_lineage(
                dataset_uuid,
                f"{job_type}_failed",
                {"username": username, "error": str(exc)},
            )
        ingestion_registry.append_job_log(job_id, f"Failed: {exc}")
        return {"dataset": ingestion_registry.get_dataset(dataset_uuid) if dataset_uuid else None, "job": ingestion_registry.get_job(job_id)}
    finally:
        _notify_refresh()


def create_dataset_from_upload(
    file: UploadFile,
    username: str,
    category: str,
    tags: str = "",
    memory_scope: str = "chroma_only",
    source_type: Optional[str] = None,
) -> Dict[str, Any]:
    saved = save_upload_file(file, username)
    duplicate = ingestion_registry.find_dataset_by_hash(username, saved["sha256"])
    if duplicate is not None:
        return {"status": "success", "data": {"dataset": duplicate, "duplicate": True, "job": None}}
    dataset = _create_dataset_record(
        username=username,
        original_filename=saved["original_filename"],
        stored_path=saved["stored_path"],
        sha256_hash=saved["sha256"],
        size_bytes=saved["size_bytes"],
        category=category,
        tags=tags,
        memory_scope=memory_scope,
        source_type=source_type or saved["source_type"],
    )
    job = create_ingestion_job(dataset["dataset_uuid"], username, job_type="ingest")
    _notify_refresh()
    return {"status": "accepted", "data": {"dataset": dataset, "job": job, "duplicate": False}}


def reindex_dataset(dataset_uuid: str, username: str) -> Dict[str, Any]:
    dataset = ingestion_registry.get_dataset(dataset_uuid)
    if dataset is None:
        return {"status": "error", "message": "Dataset not found."}
    job = create_ingestion_job(dataset_uuid, username, "reindex")
    _notify_refresh()
    return {"status": "accepted", "data": {"dataset": dataset, "job": job}}


def archive_dataset(dataset_uuid: str, username: str) -> Dict[str, Any]:
    dataset = ingestion_registry.update_dataset(dataset_uuid, ingestion_status="archived", archived_at=ingestion_registry.now_iso())
    log_lineage(dataset_uuid, "archive", {"username": username, "status": "archived"})
    semantic_cache.invalidate_tag(f"dataset:{dataset_uuid}")
    _notify_refresh()
    return {"status": "success", "data": {"dataset": dataset, "job_id": None}}


def delete_dataset(dataset_uuid: str, username: str) -> Dict[str, Any]:
    from .embedding_manager import delete_vectors

    dataset = ingestion_registry.get_dataset(dataset_uuid)
    if dataset is None:
        return {"status": "error", "message": "Dataset not found."}
    delete_vectors(dataset_uuid, dataset.get("owner_username"))
    file_path = dataset.get("file_path")
    archive_path = None
    if file_path and os.path.exists(file_path):
        deleted_dir = os.path.join(os.path.dirname(os.path.dirname(file_path)), "deleted")
        os.makedirs(deleted_dir, exist_ok=True)
        archive_path = os.path.join(deleted_dir, os.path.basename(file_path))
        shutil.move(file_path, archive_path)
    ingestion_registry.execute("DELETE FROM dataset_chunks WHERE dataset_uuid = ?", (dataset_uuid,))
    updated = ingestion_registry.update_dataset(
        dataset_uuid,
        ingestion_status="deleted",
        deleted_at=ingestion_registry.now_iso(),
        file_path=None,
        metadata_json=json.dumps({"archived_file_path": archive_path}, ensure_ascii=False),
    )
    log_lineage(dataset_uuid, "delete", {"username": username, "archived_file_path": archive_path})
    semantic_cache.invalidate_tag(f"dataset:{dataset_uuid}")
    _notify_refresh()
    return {"status": "success", "data": {"dataset": updated, "job_id": None}}


def search_datasets(query: str, owner_username: Optional[str] = None) -> Dict[str, Any]:
    rows = ingestion_registry.search_datasets(query, owner_username)
    normalized = []
    seen = set()
    for row in rows:
        dataset_uuid = row["dataset_uuid"]
        if dataset_uuid in seen:
            continue
        seen.add(dataset_uuid)
        normalized.append(
            {
                "dataset_uuid": dataset_uuid,
                "dataset_name": row["dataset_name"],
                "ingestion_status": row["ingestion_status"],
                "original_filename": row["original_filename"],
                "tags": json.loads(row.get("tags_json") or "[]"),
                "matched_chunk_preview": row.get("matched_chunk_preview") or "",
            }
        )
    return {"status": "success", "data": normalized}


def get_dashboard_snapshot(owner_username: Optional[str] = None, active_only: bool = False) -> Dict[str, Any]:
    reconcile_stale_jobs(owner_username=owner_username)
    datasets = ingestion_registry.list_datasets(owner_username=owner_username, active_only=active_only)
    jobs = list_jobs(owner_username=owner_username, limit=25)
    return {
        "status": "success",
        "data": {
            "totals": ingestion_registry.get_totals(),
            "datasets": datasets,
            "jobs": jobs,
            "collection_health": get_collection_health(),
        },
    }


def list_jobs(owner_username: Optional[str] = None, limit: int = 25) -> List[Dict[str, Any]]:
    reconcile_stale_jobs(owner_username=owner_username)
    if owner_username:
        return ingestion_registry.fetch_all(
            "SELECT * FROM ingestion_jobs WHERE username = ? ORDER BY created_at DESC LIMIT ?",
            (owner_username, limit),
        )
    return ingestion_registry.list_jobs(limit=limit)


def reconcile_stale_jobs(owner_username: Optional[str] = None, stale_minutes: int = 30) -> int:
    cutoff = datetime.utcnow() - timedelta(minutes=stale_minutes)
    params: List[Any] = []
    where = "status IN ('queued', 'processing')"
    if owner_username:
        where += " AND username = ?"
        params.append(owner_username)
    rows = ingestion_registry.fetch_all(
        f"SELECT * FROM ingestion_jobs WHERE {where} ORDER BY created_at ASC",
        params,
    )
    stale_count = 0
    for row in rows:
        anchor = _parse_iso_datetime(row.get("updated_at")) or _parse_iso_datetime(row.get("created_at"))
        if anchor is None or anchor > cutoff:
            continue
        job_id = row["id"]
        error_message = f"Job stale timeout after {stale_minutes} minutes."
        ingestion_registry.update_job(
            job_id,
            status="failed",
            completed_at=ingestion_registry.now_iso(),
            error_message=error_message,
        )
        ingestion_registry.append_job_log(job_id, f"Failed: {error_message}")
        dataset_uuid = row.get("dataset_uuid")
        if dataset_uuid:
            dataset = ingestion_registry.get_dataset(dataset_uuid)
            dataset_status = (dataset or {}).get("ingestion_status")
            if dataset_status in {"queued", "processing"}:
                ingestion_registry.update_dataset(
                    dataset_uuid,
                    ingestion_status="failed",
                    last_error=error_message,
                )
        stale_count += 1
    if stale_count:
        _notify_refresh()
    return stale_count


def get_dataset_detail(dataset_uuid: str) -> Dict[str, Any]:
    dataset = ingestion_registry.get_dataset(dataset_uuid)
    if dataset is None:
        return {"status": "error", "message": "Dataset not found."}
    chunks = ingestion_registry.list_chunks(dataset_uuid)
    lineage = ingestion_registry.list_lineage(dataset_uuid)
    return {
        "status": "success",
        "data": {
            "dataset": dataset,
            "chunks": chunks,
            "lineage": lineage,
            "vector_health": get_dataset_vector_health(dataset_uuid),
        },
    }


def get_analytics_overview() -> Dict[str, Any]:
    return {
        "status": "success",
        "data": {
            "retrieval": get_dataset_analytics(),
            "leaderboard": get_top_retrieved_datasets(),
            "collection_health": get_collection_health(),
            "orphans": find_orphan_chunks(),
        },
    }


def discover_orphan_source_files(username: str) -> Dict[str, Any]:
    source_dir = _ingestion_source_dir(username)
    files = []
    seen_hashes = set()
    for path in sorted(source_dir.glob("*")) if source_dir.exists() else []:
        if not path.is_file() or path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        sha256_hash = compute_sha256(str(path))
        if sha256_hash in seen_hashes:
            continue
        existing = ingestion_registry.fetch_one(
            """
            SELECT * FROM ingested_datasets
            WHERE owner_username = ? AND deleted_at IS NULL
              AND (file_hash_sha256 = ? OR file_path = ?)
            ORDER BY created_at DESC LIMIT 1
            """,
            (username, sha256_hash, str(path)),
        )
        if existing is not None:
            continue
        seen_hashes.add(sha256_hash)
        files.append(
            {
                "filename": path.name,
                "file_path": str(path),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_hash,
                "suggested_category": "recovered",
                "source_type": path.suffix.lstrip(".").lower(),
            }
        )
    return {
        "status": "success",
        "data": {
            "source_dir": str(source_dir),
            "orphan_count": len(files),
            "files": files,
        },
    }


def recover_orphan_source_files(
    username: str,
    filenames: Optional[List[str]] = None,
    category: str = "recovered",
    tags: str = "recovered,orphan-source",
    memory_scope: str = "chroma_only",
) -> Dict[str, Any]:
    discovered = discover_orphan_source_files(username)["data"]["files"]
    filename_filter = set(filenames or [])
    selected = [row for row in discovered if not filename_filter or row["filename"] in filename_filter]
    accepted = []
    for row in selected:
        dataset = _create_dataset_record(
            username=username,
            original_filename=row["filename"],
            stored_path=row["file_path"],
            sha256_hash=row["sha256"],
            size_bytes=row["size_bytes"],
            category=category,
            tags=tags,
            memory_scope=memory_scope,
            source_type=row["source_type"],
            source_origin="recovered_orphan",
        )
        job = create_ingestion_job(dataset["dataset_uuid"], username, job_type="ingest")
        accepted.append({"dataset": dataset, "job": job})
    _notify_refresh()
    return {
        "status": "accepted",
        "data": {
            "recovered_count": len(accepted),
            "jobs": accepted,
            "requested_filenames": filenames or [],
        },
    }


def get_logs_overview(username: str, job_limit: int = 100, failed_limit: int = 50) -> Dict[str, Any]:
    reconcile_stale_jobs(owner_username=username)
    failed_jobs = ingestion_registry.fetch_all(
        """
        SELECT j.*, d.dataset_name
        FROM ingestion_jobs j
        LEFT JOIN ingested_datasets d ON d.dataset_uuid = j.dataset_uuid
        WHERE j.username = ? AND j.status = 'failed'
        ORDER BY j.created_at DESC
        LIMIT ?
        """,
        (username, failed_limit),
    )
    failed_datasets = ingestion_registry.fetch_all(
        """
        SELECT dataset_uuid, dataset_name, ingestion_status, last_error, updated_at, category
        FROM ingested_datasets
        WHERE owner_username = ? AND deleted_at IS NULL AND ingestion_status = 'failed'
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (username, failed_limit),
    )
    duplicate_rows = ingestion_registry.fetch_all(
        """
        SELECT
            LOWER(TRIM(dataset_name)) AS normalized_name,
            COUNT(*) AS dataset_count,
            GROUP_CONCAT(dataset_uuid) AS dataset_uuids,
            GROUP_CONCAT(ingestion_status) AS statuses,
            GROUP_CONCAT(original_filename) AS source_files,
            MAX(updated_at) AS last_updated
        FROM ingested_datasets
        WHERE owner_username = ? AND deleted_at IS NULL
        GROUP BY LOWER(TRIM(dataset_name))
        HAVING COUNT(*) > 1
        ORDER BY dataset_count DESC, last_updated DESC
        """,
        (username,),
    )
    duplicates = []
    for row in duplicate_rows:
        duplicates.append(
            {
                "dataset_name": row.get("normalized_name", ""),
                "dataset_count": row.get("dataset_count", 0),
                "dataset_uuids": [item for item in (row.get("dataset_uuids") or "").split(",") if item],
                "statuses": [item for item in (row.get("statuses") or "").split(",") if item],
                "source_files": [item for item in (row.get("source_files") or "").split(",") if item],
                "last_updated": row.get("last_updated"),
            }
        )
    recent_jobs = ingestion_registry.fetch_all(
        """
        SELECT j.*, d.dataset_name
        FROM ingestion_jobs j
        LEFT JOIN ingested_datasets d ON d.dataset_uuid = j.dataset_uuid
        WHERE j.username = ?
        ORDER BY j.created_at DESC
        LIMIT ?
        """,
        (username, job_limit),
    )
    return {
        "status": "success",
        "data": {
            "failed_jobs": failed_jobs,
            "failed_datasets": failed_datasets,
            "duplicates": duplicates,
            "recent_jobs": recent_jobs,
        },
    }
