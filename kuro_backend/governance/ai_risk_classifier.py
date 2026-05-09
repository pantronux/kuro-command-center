from __future__ import annotations

from typing import Dict


def classify_risk(user_input: str, contradiction_score: float, confidence_score: float) -> Dict[str, float | str]:
    text = (user_input or "").lower()
    pii_risk = 0.7 if any(k in text for k in ("password", "token", "secret", "api key")) else 0.1
    unsafe_exec_risk = 0.7 if any(k in text for k in ("delete", "rm -rf", "drop table", "format")) else 0.1
    hallucination_risk = max(0.0, min(1.0, (1.0 - confidence_score) + contradiction_score * 0.4))
    total = max(0.0, min(1.0, (pii_risk * 0.25) + (unsafe_exec_risk * 0.35) + (hallucination_risk * 0.40)))
    label = "high" if total >= 0.65 else "medium" if total >= 0.35 else "low"
    return {
        "pii_risk": pii_risk,
        "unsafe_execution_risk": unsafe_exec_risk,
        "hallucination_risk": hallucination_risk,
        "total_risk": total,
        "risk_label": label,
    }
