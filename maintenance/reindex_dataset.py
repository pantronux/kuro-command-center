from __future__ import annotations

import argparse

from kuro_backend.ingestion_center import ingestion_manager


def main() -> int:
    parser = argparse.ArgumentParser(description="Reindex a dataset in the ingestion center.")
    parser.add_argument("dataset_uuid")
    parser.add_argument("--username", default="Pantronux")
    args = parser.parse_args()
    print(ingestion_manager.reindex_dataset(args.dataset_uuid, args.username))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
