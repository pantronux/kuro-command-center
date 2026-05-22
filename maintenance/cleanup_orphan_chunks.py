from __future__ import annotations

import argparse

from kuro_backend.ingestion_center.ingestion_scheduler import inspect_orphans
from kuro_backend.ingestion_center import ingestion_registry


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect or clean verified orphan ingestion chunks.")
    parser.add_argument("--apply", action="store_true", help="Delete verified orphan chunk rows.")
    args = parser.parse_args()

    report = inspect_orphans()
    orphans = report.get("orphans", [])
    cleanup_candidates = []
    for chunk in orphans:
        dataset_uuid = chunk.get("dataset_uuid")
        dataset = ingestion_registry.get_dataset(str(dataset_uuid or "")) if dataset_uuid else None
        if dataset is None or dataset.get("deleted_at") or dataset.get("ingestion_status") in {"deleted", "archived"}:
            cleanup_candidates.append(chunk)

    deleted = 0
    if args.apply:
        for chunk in cleanup_candidates:
            chunk_id = chunk.get("id")
            if chunk_id:
                ingestion_registry.execute("DELETE FROM dataset_chunks WHERE id = ?", (int(chunk_id),))
                deleted += 1

    print({
        "status": "success",
        "orphan_count": len(orphans),
        "verified_cleanup_candidates": len(cleanup_candidates),
        "deleted": deleted,
        "dry_run": not args.apply,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
