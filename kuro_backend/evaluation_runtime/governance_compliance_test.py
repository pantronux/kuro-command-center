from __future__ import annotations

from typing import Any, Dict


def compute_governance_compliance(governance_status: Dict[str, Any]) -> Dict[str, float]:
    action = str((governance_status or {}).get("action", "allow"))
    score = 1.0 if action in {"allow", "downgrade", "restrict_tools"} else 0.0
    return {"governance_compliance": score}
