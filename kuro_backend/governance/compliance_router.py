from __future__ import annotations

from typing import Dict


def route_compliance(policy_action: str) -> Dict[str, str]:
    if policy_action == "restrict_tools":
        return {"route": "high_guard", "note": "Tool execution restricted by governance policy."}
    if policy_action == "downgrade":
        return {"route": "caution", "note": "Response downgraded to conservative mode."}
    return {"route": "normal", "note": "Policy check passed."}
