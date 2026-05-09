from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PersonaProfile:
    cognition_layer: str
    tone_layer: str
    expertise_layer: str
    interaction_layer: str
    behavioral_constraints: str
    verbosity_profile: str
    challenge_profile: str
