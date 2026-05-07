from kuro_backend.evaluation.dataset_builder import EvalRecord, build_dataset
from kuro_backend.evaluation.autonomous_evaluator import evaluate_record

def test_evaluation_pipeline():
    record = EvalRecord(
        span_id="123",
        chat_id="chat",
        username="user",
        persona="persona",
        input_text="input",
        retrieved_context="ctx",
        output_text="out",
        latency_ms=100.0,
        rag_grade="relevant",
        retrieval_retries=0,
        timestamp="ts"
    )
    score = evaluate_record(record)
    assert 0.0 <= score.composite <= 1.0
    assert 0.0 <= score.groundedness <= 1.0

    dataset = build_dataset()
    assert isinstance(dataset, list)
