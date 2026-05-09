from __future__ import annotations

from typing import Any, Dict


def log_tool_trace(*, session_id: str, payload: Dict[str, Any]) -> None:
    from kuro_backend import intelligence_db

    intelligence_db.save_tool_trace_log(session_id=session_id, payload=payload)


def log_tool_risk(*, session_id: str, tool_name: str, risk_profile: Dict[str, Any], payload: Dict[str, Any]) -> None:
    from kuro_backend import intelligence_db

    intelligence_db.save_tool_risk_log(
        session_id=session_id,
        tool_name=tool_name,
        composite_risk=float(risk_profile.get("composite_risk", 0.0) or 0.0),
        payload={"risk_profile": risk_profile, **(payload or {})},
    )


def log_tool_budget(*, session_id: str, payload: Dict[str, Any]) -> None:
    from kuro_backend import intelligence_db

    intelligence_db.save_tool_budget_log(session_id=session_id, payload=payload)
