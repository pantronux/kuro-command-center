from __future__ import annotations

import os

import pytest


os.environ.setdefault("KURO_APP_PROFILE", "legacy")


@pytest.fixture(autouse=True)
def _default_legacy_profile_for_tests(monkeypatch):
    """Keep legacy tests independent from the developer's local .env profile."""
    monkeypatch.setenv("KURO_APP_PROFILE", "legacy")
