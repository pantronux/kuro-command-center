"""Forensic mode profile."""

from playground_runtime.modes.base_mode import ModeProfile


FORENSIC_MODE = ModeProfile(
    name="forensic",
    memory_policy="ephemeral",
    grounding_strictness="high",
    hallucination_tolerance="zero",
    reproducibility_level="maximum",
    telemetry_policy="maximum",
    multi_provider_allowed=True,
    raw_evidence_retention="immutable",
    export_formats_allowed=["json", "rdf", "csv"],
)
