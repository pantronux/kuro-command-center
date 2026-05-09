from __future__ import annotations

from kuro_backend.ingestion_center.ingestion_scheduler import inspect_orphans


def main() -> int:
    print(inspect_orphans())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
