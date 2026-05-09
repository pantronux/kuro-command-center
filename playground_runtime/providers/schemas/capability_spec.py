"""
Provider capability schema.

--- Header Doc ---
Purpose: Declare provider feature support matrix used by runtime guards.
Caller: capability registry and provider router.
Dependencies: dataclasses.
Main Functions: CapabilitySpec.
Side Effects: None.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilitySpec:
    provider_id: str
    supports_text: bool = True
    supports_image: bool = False
    supports_code: bool = True
    supports_structured_output: bool = False
    supports_grounding: bool = False
    grounding_type: str = "none"
    supports_citations: bool = False
    citation_format: str = "none"
    supports_streaming: bool = False
    supports_tool_use: bool = False
    max_context_window: int = 32768
    exposes_visible_reasoning_traces: bool = False
