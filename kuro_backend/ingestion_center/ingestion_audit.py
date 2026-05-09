from __future__ import annotations

from typing import Any, Dict, Optional

from . import ingestion_registry


def log_lineage(
    dataset_uuid: str,
    operation_type: str,
    metadata: Dict[str, Any],
    parent_dataset_uuid: Optional[str] = None,
) -> None:
    ingestion_registry.create_lineage(
        dataset_uuid=dataset_uuid,
        operation_type=operation_type,
        metadata=metadata,
        parent_dataset_uuid=parent_dataset_uuid,
    )
