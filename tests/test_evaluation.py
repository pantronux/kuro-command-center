import sqlite3

from kuro_backend import intelligence_db
from kuro_backend.evaluation.dataset_builder import EvalRecord, build_dataset
from kuro_backend.evaluation import autonomous_evaluator
from kuro_backend.evaluation.autonomous_evaluator import evaluate_record


def _use_tmp_intelligence_db(tmp_path, monkeypatch):
    path = tmp_path / "kuro_intelligence.db"
    monkeypatch.setattr(intelligence_db, "DB_PATH", str(path))
    intelligence_db._reset_schema_ready_for_tests()
    return path

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


def test_evaluation_summary_returns_no_data_when_log_table_missing(tmp_path, monkeypatch):
    _use_tmp_intelligence_db(tmp_path, monkeypatch)

    summary = autonomous_evaluator.get_evaluation_summary()

    assert summary["status"] == "no_data"
    assert summary["total_records"] == 0
    assert summary["metrics"]["composite"] == 0.0


def test_evaluation_summary_migrates_legacy_log_table(tmp_path, monkeypatch):
    path = _use_tmp_intelligence_db(tmp_path, monkeypatch)
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE epistemic_log (id INTEGER PRIMARY KEY, source_query TEXT)")
        conn.commit()
    finally:
        conn.close()

    summary = autonomous_evaluator.get_evaluation_summary()

    assert summary["status"] == "no_data"
    conn = sqlite3.connect(path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(epistemic_log)").fetchall()}
    finally:
        conn.close()
    assert "eval_composite" in columns
    assert "eval_groundedness" in columns
