"""Research mode profile."""

from playground_runtime.modes.base_mode import ModeProfile


RESEARCH_MODE = ModeProfile(
    name="research",
    memory_policy="session-scoped",
    grounding_strictness="relaxed",
    hallucination_tolerance="flag",
    reproducibility_level="standard",
    telemetry_policy="full",
    multi_provider_allowed=True,
    raw_evidence_retention="90d",
    export_formats_allowed=["json", "csv"],
)
