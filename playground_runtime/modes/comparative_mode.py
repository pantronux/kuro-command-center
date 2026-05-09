"""Comparative mode profile."""

from playground_runtime.modes.base_mode import ModeProfile


COMPARATIVE_MODE = ModeProfile(
    name="comparative",
    memory_policy="none",
    grounding_strictness="medium",
    hallucination_tolerance="flag",
    reproducibility_level="high",
    telemetry_policy="full",
    multi_provider_allowed=True,
    raw_evidence_retention="90d",
    export_formats_allowed=["json", "csv", "rdf"],
)
