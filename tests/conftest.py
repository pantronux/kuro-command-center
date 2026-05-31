from __future__ import annotations

import os
import sys
import types

import pytest


os.environ.setdefault("KURO_APP_PROFILE", "legacy")
os.environ.pop("KURO_APP_ROLE", None)

if "mem0" not in sys.modules:
    fake_mem0 = types.ModuleType("mem0")

    class _FakeMemory:
        def __init__(self, *args, **kwargs):
            pass

    fake_mem0.Memory = _FakeMemory
    sys.modules["mem0"] = fake_mem0

if "phoenix" not in sys.modules:
    fake_phoenix = types.ModuleType("phoenix")

    class _FakePhoenixApp:
        url = "http://localhost:6006"

        def close(self):
            return None

    fake_phoenix.launch_app = lambda *args, **kwargs: _FakePhoenixApp()
    sys.modules["phoenix"] = fake_phoenix


@pytest.fixture(autouse=True)
def _default_legacy_profile_for_tests(monkeypatch):
    """Keep legacy tests independent from the developer's local .env profile."""
    monkeypatch.delenv("KURO_APP_ROLE", raising=False)
    monkeypatch.setenv("KURO_APP_PROFILE", "legacy")
