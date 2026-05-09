from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict

from fastapi import HTTPException, Request, UploadFile

from kuro_backend.config import settings
from kuro_backend.tools.base_tools import MAX_FILE_SIZE_MB

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".xlsx", ".xls", ".pptx", ".ppt"}


def assert_admin(request: Request) -> Dict[str, str]:
    from main import require_admin_user

    return require_admin_user(request)


def validate_uploaded_file(upload_file: UploadFile) -> Dict[str, str]:
    filename = (upload_file.filename or "").strip()
    ext = Path(filename).suffix.lower()
    if not filename or ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported ingestion file type.")
    return {"filename": filename, "extension": ext}


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "_", value.strip())
    return value.strip("._") or "dataset"


def build_dataset_storage_path(username: str, original_filename: str) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    ext = Path(original_filename).suffix.lower()
    base = _slugify(Path(original_filename).stem)
    target_dir = Path(settings.WORKING_DIR) / "uploaded_files" / username / "ingestion_center"
    target_dir.mkdir(parents=True, exist_ok=True)
    return str(target_dir / f"{base}_{stamp}{ext}")


def save_upload_file(upload_file: UploadFile, username: str) -> Dict[str, str]:
    info = validate_uploaded_file(upload_file)
    content = upload_file.file.read()
    size_bytes = len(content)
    if size_bytes > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File exceeds {MAX_FILE_SIZE_MB} MB limit.")
    target_path = build_dataset_storage_path(username, info["filename"])
    with open(target_path, "wb") as handle:
        handle.write(content)
    return {
        "original_filename": info["filename"],
        "stored_path": target_path,
        "size_bytes": size_bytes,
        "sha256": hashlib.sha256(content).hexdigest(),
        "source_type": info["extension"].lstrip("."),
    }


def compute_sha256(file_path: str) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
