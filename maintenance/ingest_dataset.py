from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

from kuro_backend.ingestion_center import ingestion_manager


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a dataset into the Kuro ingestion center.")
    parser.add_argument("file_path")
    parser.add_argument("--username", default="Pantronux")
    parser.add_argument("--category", default="manual")
    parser.add_argument("--tags", default="")
    args = parser.parse_args()

    file_path = Path(args.file_path)
    upload = SimpleNamespace(filename=file_path.name, file=open(file_path, "rb"))
    try:
        result = ingestion_manager.create_dataset_from_upload(
            file=upload,
            username=args.username,
            category=args.category,
            tags=args.tags,
        )
        job = result.get("data", {}).get("job")
        if job is not None:
            result = ingestion_manager.process_ingestion_job(job["id"]) or result
        print(result)
    finally:
        upload.file.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
