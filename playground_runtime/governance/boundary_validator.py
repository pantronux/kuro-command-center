"""
Static boundary validator.

--- Header Doc ---
Purpose: Validate import and db boundary contracts for playground_runtime.
Caller: tests, startup guards.
Dependencies: ast, pathlib, playground_runtime.errors.
Main Functions: validate_playground_imports(), validate_db_path().
Side Effects: Raises PlaygroundIsolationError on violations.
"""

from __future__ import annotations

import ast
from pathlib import Path

from playground_runtime.errors import PlaygroundIsolationError

FORBIDDEN_IMPORT_PREFIXES = (
    "kuro_backend",
    "langgraph_core",
    "memory_coordinator",
    "perpetual_memory",
    "personas",
    "epistemic_filter",
)
FORBIDDEN_DB_NAMES = {
    "kuro_short_term.db",
    "kuro_chat_history.db",
    "kuro_intelligence.db",
}


def validate_db_path(db_path: str) -> None:
    name = Path(db_path).name
    if name in FORBIDDEN_DB_NAMES:
        raise PlaygroundIsolationError(f"BOUNDARY_VIOLATION: forbidden DB path '{name}'")


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        yield path


def validate_playground_imports(root: Path | None = None) -> None:
    root = root or Path(__file__).resolve().parents[1]
    violations = []

    for py_file in _iter_python_files(root):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(FORBIDDEN_IMPORT_PREFIXES):
                        violations.append((py_file, alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.startswith(FORBIDDEN_IMPORT_PREFIXES):
                    violations.append((py_file, mod, node.lineno))

    if violations:
        parts = [f"{path}:{line} imports '{mod}'" for path, mod, line in violations]
        raise PlaygroundIsolationError("BOUNDARY_VIOLATION: forbidden import(s): " + "; ".join(parts))
