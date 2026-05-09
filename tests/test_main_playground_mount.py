from __future__ import annotations

from pathlib import Path
import ast


def test_main_mount_playground_router_conditional():
    source = Path("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    fn = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_mount_playground_router_if_enabled":
            fn = node
            break

    assert fn is not None
    assert "KURO_PLAYGROUND_API_ENABLED" in source
    assert "include_router" in source
    assert "create_playground_router" in source
