from dataclasses import dataclass
import json
import logging
from typing import List
from pathlib import Path
import datetime

logger = logging.getLogger(__name__)

@dataclass
class EvalRecord:
    span_id: str
    chat_id: str
    username: str
    persona: str
    input_text: str
    retrieved_context: str
    output_text: str
    latency_ms: float
    rag_grade: str
    retrieval_retries: int
    timestamp: str

def build_dataset(since_hours: int = 24) -> List[EvalRecord]:
    # Placeholder for actual Phoenix REST API query.
    # In a real scenario, this would query GET /v1/projects/{project_id}/spans
    return []

def export_to_jsonl(records: List[EvalRecord], path: Path):
    with open(path, "w") as f:
        for record in records:
            # dataclasses.asdict could be used but simple dump works
            f.write(json.dumps(record.__dict__) + "\n")
