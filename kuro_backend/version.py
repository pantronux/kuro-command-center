"""Kuro AI V6.1 — Single-source-of-truth version metadata.

Importers should prefer :data:`VERSION_BANNER` when rendering in the UI
and :data:`VERSION` for machine-readable comparisons. Bumping a new
release is a one-line change here — everything else reads from this
module.
"""
from __future__ import annotations

from typing import Dict

VERSION: str = "6.1.0"
CODENAME: str = "Sovereign"
VERSION_LABEL: str = f"V{VERSION.split('.')[0]}.{VERSION.split('.')[1]}"
VERSION_BANNER: str = f"Kuro {VERSION_LABEL} — {CODENAME}"


def version_info() -> Dict[str, str]:
    """Return the canonical version payload used by `/api/version` and
    the frontend version badge."""
    return {
        "version": VERSION,
        "codename": CODENAME,
        "label": VERSION_LABEL,
        "banner": VERSION_BANNER,
    }


__all__ = ["VERSION", "CODENAME", "VERSION_LABEL", "VERSION_BANNER", "version_info"]
