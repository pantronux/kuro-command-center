"""
Kuro AI V4.0 - Guardrails Pydantic Schemas
================================================================================
Defines structured output schemas for validated responses.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
import re
from datetime import datetime


class ValidationFailure(BaseModel):
    """Represents a single guardrail validation failure."""
    guardrail_type: str  # "compliance", "privacy", "tone"
    rule_violated: str   # Specific rule that was violated
    severity: str        # "critical", "warning", "info"
    detail: str          # Human-readable explanation
    suggestion: str      # How to fix the issue


class GuardrailResult(BaseModel):
    """
    Result from guardrails validation.
    
    If is_valid=True, the response is safe to return.
    If is_valid=False, the response needs correction.
    """
    is_valid: bool = True
    failures: List[ValidationFailure] = Field(default_factory=list)
    corrected_text: Optional[str] = None
    validation_timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    
    @property
    def has_critical_failures(self) -> bool:
        """Check if any failures are critical."""
        return any(f.severity == "critical" for f in self.failures)
    
    @property
    def failure_summary(self) -> str:
        """Get a summary of all failures."""
        if not self.failures:
            return "All guardrails passed"
        critical = sum(1 for f in self.failures if f.severity == "critical")
        warnings = sum(1 for f in self.failures if f.severity == "warning")
        return f"{critical} critical, {warnings} warnings"


class AuditResponse(BaseModel):
    """
    Structured audit response for compliance queries.
    Ensures all compliance answers have proper citations and grounding.
    """
    answer: str = Field(..., description="The main answer text")
    iso_references: List[str] = Field(
        default_factory=list,
        description="List of ISO clause references cited (e.g., 'A.5.1', '8.2')"
    )
    source_documents: List[str] = Field(
        default_factory=list,
        description="List of source document names used for grounding"
    )
    confidence_level: str = Field(
        default="medium",
        description="Confidence level: high, medium, low"
    )
    disclaimer: Optional[str] = Field(
        default=None,
        description="Disclaimer if information is incomplete"
    )
    
    @field_validator('iso_references')
    @classmethod
    def validate_iso_format(cls, v: List[str]) -> List[str]:
        """Validate that ISO references follow standard format patterns."""
        valid_pattern = re.compile(r'^(ISO[/\s]*\d+|A\.\d+\.\d+|Clause\s*\d+|Section\s*\d+|Klausul\s*\d+)', re.IGNORECASE)
        for ref in v:
            if ref and not valid_pattern.match(ref):
                raise ValueError(f"Invalid ISO reference format: {ref}. Expected format like 'A.5.1', 'Clause 8', etc.")
        return v
    
    @field_validator('confidence_level')
    @classmethod
    def validate_confidence(cls, v: str) -> str:
        """Validate confidence level is one of the allowed values."""
        allowed = {"high", "medium", "low"}
        if v.lower() not in allowed:
            raise ValueError(f"Invalid confidence level: {v}. Must be one of {allowed}")
        return v.lower()


class ScoldingResponse(BaseModel):
    """
    Structured response for habit scolding/evaluation.
    Ensures scolding is professional and contains logical consequences.
    """
    evaluation_text: str = Field(..., description="The scolding/evaluation message")
    has_logical_consequence: bool = Field(
        default=False,
        description="Whether the message contains logical consequences of poor habits"
    )
    has_motivation: bool = Field(
        default=False,
        description="Whether the message ends with motivation/encouragement"
    )
    contains_profanity: bool = Field(
        default=False,
        description="Whether the message contains any profanity (should be False)"
    )
    tone_score: float = Field(
        default=0.0,
        description="Professional tone score (0-1, higher is more professional)"
    )


class PrivacyCheckResult(BaseModel):
    """Result from privacy guardrail check."""
    has_pii: bool = False
    pii_types_found: List[str] = Field(default_factory=list)
    has_confidential_project_data: bool = False
    confidential_keywords_found: List[str] = Field(default_factory=list)
    is_safe: bool = True
    redacted_text: Optional[str] = None
