from __future__ import annotations

_TONE_LAYERS = {
    "advisor": "direct, analytical, and challenging",
    "auditor": "concise, surgical, and evidence-demanding",
    "tactical": "fast, practical, low-theory",
    "consultant": "professional and structured",
    "chill": "relaxed but technically clear",
    "chancellor": "data-driven and risk-framed",
}

_INTERACTION_LAYERS = {
    "advisor": "proactively questions assumptions",
    "auditor": "highlights failures before summaries",
    "tactical": "prioritizes blast-radius and rollback",
    "consultant": "frames tradeoffs and implementation steps",
    "chill": "keeps conversation natural and brief",
    "chancellor": "anchors to ledger facts and scenario analysis",
}


def get_tone_layer(persona: str) -> str:
    return _TONE_LAYERS.get(persona, _TONE_LAYERS["consultant"])


def get_interaction_layer(persona: str) -> str:
    return _INTERACTION_LAYERS.get(persona, _INTERACTION_LAYERS["consultant"])
