from __future__ import annotations

import pytest

from playground_runtime.errors import PlaygroundIsolationError
from playground_runtime.governance.boundary_validator import (
    validate_db_path,
    validate_playground_imports,
)


def test_boundary_validator_rejects_forbidden_db_name():
    with pytest.raises(PlaygroundIsolationError):
        validate_db_path("kuro_short_term.db")


def test_boundary_validator_detects_forbidden_import(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("import kuro_backend\n", encoding="utf-8")
    with pytest.raises(PlaygroundIsolationError):
        validate_playground_imports(root=tmp_path)
