from dataclasses import dataclass
import logging
from typing import List
from .dataset_builder import EvalRecord, build_dataset

logger = logging.getLogger(__name__)

@dataclass
class EvalScore:
    groundedness: float
    goal_alignment: float
    epistemic_compliance: float
    latency_risk: float
    composite: float
    rationale: str

def evaluate_record(record: EvalRecord) -> EvalScore:
    # Dummy mock scoring for now, production would call Gemini
    return EvalScore(1.0, 1.0, 1.0, 0.0, 1.0, "Mock evaluation")

def run_evaluation_batch(since_hours: int = 24) -> List[EvalScore]:
    records = build_dataset(since_hours)
    scores = []
    for r in records:
        scores.append(evaluate_record(r))
    return scores
