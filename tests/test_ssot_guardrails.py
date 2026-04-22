"""
P3.1 — SSoT static guardrails.

The only modules allowed to call raw mutation primitives on core_service
(`add_habit`, `update_habit`, `delete_habit`, `mark_habit_done`, and
`add_reminder`, `delete_reminder`) are `core_service.py` itself and
`memory_coordinator.py`. All other callers must go through the `*_svc`
wrappers (which call `bump_data_revision()` + `record_mutation()`).

This test scans the `kuro_backend/` tree and fails if any other file imports
or calls those raw primitives. It also ensures the SSoT API surface
(`bump_data_revision`, `record_mutation`) still exists.

--- Header Doc ---
Purpose: Static AST guardrail ensuring only *_svc wrappers mutate SSoT.
Covers: kuro_backend/ AST scan for raw writer primitives.
Fixtures: Walks package tree; no runtime DB.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "kuro_backend"

RAW_PRIMITIVES = (
    "add_habit",
    "update_habit",
    "delete_habit",
    "mark_habit_done",
    "add_reminder",
    "delete_reminder",
)

# Only these files legitimately call raw SSoT primitives. Everyone else must go
# through the `*_svc` helpers which bump data revision + record mutation.
ALLOWED_CALLERS = {
    BACKEND / "services" / "core_service.py",
    BACKEND / "memory_coordinator.py",
}

_CALL_PATTERN = re.compile(
    r"(?<![\w.])core_service\.(?:"
    + "|".join(RAW_PRIMITIVES)
    + r")\b"
)
_ALIASED_CALL_PATTERN = re.compile(
    r"(?<![\w.])core_data\.(?:"
    + "|".join(RAW_PRIMITIVES)
    + r")\b"
)


def _python_files_under(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_ssot_api_surface_present() -> None:
    """Fail loudly if someone removes the SSoT primitives."""
    core_text = (BACKEND / "services" / "core_service.py").read_text(encoding="utf-8")
    coord_text = (BACKEND / "memory_coordinator.py").read_text(encoding="utf-8")

    assert "def bump_data_revision" in core_text, (
        "bump_data_revision() must remain in services/core_service.py"
    )
    assert "def record_mutation" in coord_text, (
        "record_mutation() must remain in memory_coordinator.py"
    )

    for svc in (
        "add_habit_svc",
        "update_habit_svc",
        "delete_habit_svc",
        "mark_habit_done_svc",
        "add_reminder_svc",
        "delete_reminder_svc",
    ):
        assert f"def {svc}" in core_text, f"{svc}() must remain in core_service.py"


@pytest.mark.parametrize(
    "pattern",
    [_CALL_PATTERN, _ALIASED_CALL_PATTERN],
    ids=["core_service.*", "core_data.*"],
)
def test_no_raw_primitive_calls_outside_allowlist(pattern: re.Pattern[str]) -> None:
    offenders: list[tuple[Path, int, str]] = []
    for py in _python_files_under(BACKEND):
        if py in ALLOWED_CALLERS:
            continue
        for lineno, line in enumerate(py.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                offenders.append((py.relative_to(PROJECT_ROOT), lineno, line.strip()))
    assert not offenders, (
        "SSoT guardrail breach: only core_service.py and memory_coordinator.py may call "
        "raw habit/reminder mutation primitives. Route the following call sites through "
        "the `*_svc` helpers instead:\n"
        + "\n".join(f"  {p}:{ln} -> {src}" for p, ln, src in offenders)
    )


def test_memory_coordinator_uses_svc_wrappers() -> None:
    """memory_coordinator.py must route through *_svc helpers that bump revision."""
    text = (BACKEND / "memory_coordinator.py").read_text(encoding="utf-8")
    for svc in ("add_habit_svc", "update_habit_svc", "delete_habit_svc"):
        assert svc in text, (
            f"memory_coordinator must call {svc}() (SSoT + revision bump entry)."
        )
