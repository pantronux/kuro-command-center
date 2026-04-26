"""
Per-persona Piper TTS tuning (length scale, pitch shift, optional voice path).

When a field is None, the effective value comes from environment defaults
handled inside :mod:`kuro_backend.voice_service`.

--- Header Doc ---
Purpose: Per-persona Piper TTS tuning table (length scale / pitch / voice path).
Caller: voice_service.synthesize_to_file, main.py /api/voice/speech.
Dependencies: kuro_backend.personas (persona name list), stdlib dataclasses.
Main Functions: VOICE_PROFILES, get_profile(persona).
Side Effects: None (pure data table).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Mapping, Optional

from kuro_backend import personas


@dataclass(frozen=True)
class VoiceProfile:
    """Optional overrides; ``None`` means use env-driven defaults."""

    length_scale: Optional[float]
    pitch_shift: Optional[float]
    voice_path: Optional[str] = None


# Chancellor: steadier cadence, slightly deeper pitch (stern register).
VOICE_PROFILES: Final[Mapping[str, VoiceProfile]] = {
    "consultant": VoiceProfile(None, None, None),
    "advisor": VoiceProfile(None, None, None),
    "tactical": VoiceProfile(None, None, None),
    "butler": VoiceProfile(None, None, None),
    "chill": VoiceProfile(None, None, None),
    "chancellor": VoiceProfile(1.00, 0.90, None),
    "auditor": VoiceProfile(1.20, 0.85, None),
}


def for_persona(persona: Optional[str]) -> VoiceProfile:
    key = personas.normalize_persona_key(persona)
    return VOICE_PROFILES.get(key, VoiceProfile(None, None, None))


__all__ = ["VoiceProfile", "VOICE_PROFILES", "for_persona"]
