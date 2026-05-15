"""Basic evaluation runner for V2 QA leakage dataset."""

# --- Header Doc ---
# Purpose: Run lightweight rule-based checks on evaluation datasets.
# Caller: manual QA/UAT, CI scripts.
# Dependencies: json, pathlib, datetime.
# Main Functions: run_qa_leakage_evaluation(), write_report().
# Side Effects: Writes report JSON to evaluation/reports/.

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = BASE_DIR / "datasets" / "qa_leakage.json"
REPORTS_DIR = BASE_DIR / "reports"


@dataclass
class EvalCaseResult:
    case_id: str
    passed: bool
    violations: List[str]
    hits: List[str]


def _normalize(text: str) -> str:
    return (text or "").lower()


def run_qa_leakage_evaluation(
    responses_by_case_id: Dict[str, str],
    dataset_path: Path = DEFAULT_DATASET,
) -> Dict:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    results: List[EvalCaseResult] = []
    for case in dataset:
        case_id = str(case.get("id") or "")
        response = str(responses_by_case_id.get(case_id, "") or "")
        lowered = _normalize(response)
        violations: List[str] = []
        hits: List[str] = []
        for forbidden in case.get("must_not_contain", []):
            token = str(forbidden or "").strip()
            if token and token.lower() in lowered:
                violations.append(token)
        for expected in case.get("must_contain_any", []):
            token = str(expected or "").strip()
            if token and token.lower() in lowered:
                hits.append(token)
        passed = not violations and (len(case.get("must_contain_any", [])) == 0 or bool(hits))
        results.append(
            EvalCaseResult(
                case_id=case_id,
                passed=passed,
                violations=violations,
                hits=hits,
            )
        )
    passed_count = sum(1 for r in results if r.passed)
    payload = {
        "dataset": str(dataset_path),
        "evaluated_at": datetime.utcnow().isoformat(),
        "total_cases": len(results),
        "passed_cases": passed_count,
        "pass_rate": round(passed_count / len(results), 4) if results else 0.0,
        "results": [asdict(r) for r in results],
    }
    return payload


def write_report(report_payload: Dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_path = REPORTS_DIR / f"qa_leakage_report_{ts}.json"
    out_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run QA leakage evaluation.")
    parser.add_argument(
        "--responses",
        help="Path to JSON file mapping case_id -> model response text.",
        required=False,
    )
    args = parser.parse_args()
    responses: Dict[str, str] = {}
    if args.responses:
        responses = json.loads(Path(args.responses).read_text(encoding="utf-8"))
    report = run_qa_leakage_evaluation(responses)
    report_path = write_report(report)
    print(json.dumps({"report_path": str(report_path), "summary": report}, ensure_ascii=False))
