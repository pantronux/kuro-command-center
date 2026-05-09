"""
Provider manifest schemas.

--- Header Doc ---
Purpose: Canonical provider manifest used for execution metadata.
Caller: provider registry and report builder.
Dependencies: dataclasses.
Main Functions: ProviderManifest.
Side Effects: None.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class ProviderManifest:
    provider_id: str
    model_id: str
    model_version: str
    endpoint: Optional[str] = None
    capability_spec_hash: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)
