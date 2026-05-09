"""
Runtime modes.

--- Header Doc ---
Purpose: Define runtime mode profiles for KPR execution policy.
Caller: session initialization and API endpoints.
Dependencies: mode modules.
Main Functions: resolve_mode_profile().
Side Effects: None.
"""

from .base_mode import ModeProfile
from .research_mode import RESEARCH_MODE
from .forensic_mode import FORENSIC_MODE
from .comparative_mode import COMPARATIVE_MODE
from .ontology_mode import ONTOLOGY_MODE


def resolve_mode_profile(mode: str) -> ModeProfile:
    key = mode.lower().strip()
    if key == "research":
        return RESEARCH_MODE
    if key == "forensic":
        return FORENSIC_MODE
    if key == "comparative":
        return COMPARATIVE_MODE
    if key == "ontology":
        return ONTOLOGY_MODE
    return RESEARCH_MODE
