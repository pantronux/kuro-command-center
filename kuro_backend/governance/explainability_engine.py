from __future__ import annotations

from typing import Any, Dict


def explain_governance(decision: Dict[str, Any]) -> str:
    action = decision.get("action", "allow")
    risk = (decision.get("risk") or {}).get("risk_label", "low")
    return f"[GOVERNANCE_CONTEXT] action={action}; risk={risk}."
