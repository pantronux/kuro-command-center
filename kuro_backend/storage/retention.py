"""Retention policy metadata for Storage Foundation V2."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class RetentionPolicy:
    policy_id: str
    description: str
    default_retention_days: Optional[int]
    deletion_review_required: bool


RETENTION_POLICIES: Dict[str, RetentionPolicy] = {
    "security_operational": RetentionPolicy(
        "security_operational",
        "Security and authentication operations.",
        365,
        True,
    ),
    "user_conversation": RetentionPolicy(
        "user_conversation",
        "User chat and attachment metadata.",
        None,
        True,
    ),
    "memory_operational": RetentionPolicy(
        "memory_operational",
        "Legacy memory and coordination data.",
        365,
        True,
    ),
    "audit_and_intelligence": RetentionPolicy(
        "audit_and_intelligence",
        "Audit, backup, intelligence, and notification records.",
        730,
        True,
    ),
    "financial_operational": RetentionPolicy(
        "financial_operational",
        "Finance, market, and cost records.",
        1095,
        True,
    ),
    "compliance_evidence": RetentionPolicy(
        "compliance_evidence",
        "Compliance evidence and control records.",
        2555,
        True,
    ),
    "ingested_knowledge": RetentionPolicy(
        "ingested_knowledge",
        "Uploaded and ingested knowledge metadata.",
        None,
        True,
    ),
    "future_memory_governance": RetentionPolicy(
        "future_memory_governance",
        "Future Memory V3 governed retention.",
        None,
        True,
    ),
}


def get_retention_policy(policy_id: str) -> Optional[RetentionPolicy]:
    return RETENTION_POLICIES.get(policy_id)


def get_retention_snapshot() -> dict:
    return {
        "policies": {
            key: {
                "policy_id": value.policy_id,
                "description": value.description,
                "default_retention_days": value.default_retention_days,
                "deletion_review_required": value.deletion_review_required,
            }
            for key, value in RETENTION_POLICIES.items()
        }
    }
