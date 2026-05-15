"""Structured output schema registry."""

# --- Header Doc ---
# Purpose: Central registry for runtime structured-output contracts.
# Caller: output_validator.py, main.py schema routes, QA playground modules.
# Dependencies: pydantic.
# Main Functions: SchemaRegistry.get_schema(), list_schemas(), get_json_schema().
# Side Effects: None.

from __future__ import annotations

from pydantic import BaseModel, Field


class TestCaseStep(BaseModel):
    step_number: int
    action: str
    expected_result: str


class TestCase(BaseModel):
    id: str
    title: str
    precondition: str = ""
    steps: list[TestCaseStep] = Field(default_factory=list)
    expected_result: str
    priority: str = "medium"
    type: str = "functional"


class QAOutputV1(BaseModel):
    runtime: str = "qa"
    task_type: str
    input_summary: str = ""
    assumptions: list[str] = Field(default_factory=list)
    test_cases: list[TestCase] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    schema_version: str = "qa_output_v1"


class ComplianceFinding(BaseModel):
    id: str
    severity: str
    description: str
    evidence: str = ""
    recommendation: str = ""


class ComplianceOutputV1(BaseModel):
    runtime: str = "compliance"
    task_type: str
    applicable_rules: list[str] = Field(default_factory=list)
    findings: list[ComplianceFinding] = Field(default_factory=list)
    risk_level: str = "medium"
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    schema_version: str = "compliance_output_v1"


class GovernancePolicyItem(BaseModel):
    policy_id: str
    description: str
    status: str  # compliant | non-compliant | unknown
    notes: str = ""


class GovernanceOutputV1(BaseModel):
    runtime: str = "governance"
    task_type: str
    policies_evaluated: list[GovernancePolicyItem] = Field(default_factory=list)
    overall_status: str = "unknown"
    recommendations: list[str] = Field(default_factory=list)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    schema_version: str = "governance_output_v1"


class ForensicOutputV1(BaseModel):
    runtime: str = "forensic"
    task_type: str
    findings: list[dict] = Field(default_factory=list)
    timeline: list[dict] = Field(default_factory=list)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    schema_version: str = "forensic_output_v1"


SCHEMA_REGISTRY = {
    "qa_output_v1": QAOutputV1,
    "compliance_output_v1": ComplianceOutputV1,
    "governance_output_v1": GovernanceOutputV1,
    "forensic_output_v1": ForensicOutputV1,
}


class SchemaRegistry:
    @staticmethod
    def get_schema(contract_id: str):
        schema = SCHEMA_REGISTRY.get(contract_id)
        if schema is None:
            raise KeyError(f"Unknown output schema: {contract_id}")
        return schema

    @staticmethod
    def list_schemas() -> list[str]:
        return list(SCHEMA_REGISTRY.keys())

    @staticmethod
    def get_json_schema(contract_id: str) -> dict:
        schema_class = SchemaRegistry.get_schema(contract_id)
        return schema_class.model_json_schema()
