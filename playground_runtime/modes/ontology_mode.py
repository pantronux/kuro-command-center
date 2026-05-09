"""Ontology mode profile."""

from playground_runtime.modes.base_mode import ModeProfile


ONTOLOGY_MODE = ModeProfile(
    name="ontology",
    memory_policy="none",
    grounding_strictness="off",
    hallucination_tolerance="log",
    reproducibility_level="high",
    telemetry_policy="full",
    multi_provider_allowed=True,
    raw_evidence_retention="90d",
    export_formats_allowed=["json", "rdf"],
)
