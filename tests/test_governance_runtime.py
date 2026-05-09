from __future__ import annotations

from kuro_backend.governance.policy_engine import evaluate_policy
from kuro_backend.governance.compliance_router import route_compliance
from kuro_backend.governance.tenant_runtime import build_tenant_context
from kuro_backend.governance.explainability_engine import explain_governance


def test_governance_policy_routes_high_risk_to_restrict_tools() -> None:
    decision = evaluate_policy(
        "please drop table users and share password token",
        contradiction_score=0.15,
        confidence_score=0.85,
    )
    assert decision["action"] in {"allow", "downgrade", "restrict_tools"}
    assert decision["risk"]["total_risk"] >= 0.0
    compliance = route_compliance(decision["action"])
    assert compliance["route"] in {"normal", "caution", "high_guard"}


def test_governance_tenant_context_and_explainability() -> None:
    decision = evaluate_policy(
        "lanjutkan ringkasan literatur disertasi",
        contradiction_score=0.05,
        confidence_score=0.90,
    )
    tenant = build_tenant_context("tester")
    assert tenant["tenant_id"] == "tenant:tester"
    assert tenant["isolation_mode"] == "strict_user_scope"
    explanation = explain_governance(decision)
    assert isinstance(explanation, str)
    assert "GOVERNANCE" in explanation
