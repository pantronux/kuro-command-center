#!/usr/bin/env bash
set -euo pipefail

# Ready-to-run validation pack for V2 HARDENED Prompt -1..2 scope.
# Scope intentionally excludes Prompt 3+ and goal/decision engines.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
PYTEST_FLAGS="${PYTEST_FLAGS:--x --tb=short}"

echo "[V2-PHASE2] root=$ROOT_DIR"
echo "[V2-PHASE2] python=$PYTHON_BIN"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[V2-PHASE2][ERROR] $PYTHON_BIN not found"
  exit 1
fi

echo "[V2-PHASE2] compile check"
"$PYTHON_BIN" -m compileall kuro_backend main.py

echo "[V2-PHASE2] prompt-1 focused tests"
"$PYTHON_BIN" -m pytest tests/test_runtime_registry.py $PYTEST_FLAGS

echo "[V2-PHASE2] prompt-2 focused tests"
"$PYTHON_BIN" -m pytest tests/test_boundary_guard.py $PYTEST_FLAGS

echo "[V2-PHASE2] legacy stream compatibility smoke (mocked)"
"$PYTHON_BIN" -m pytest \
  tests/test_runtime_registry.py::test_legacy_chat_no_runtime_id_works \
  tests/test_boundary_guard.py::test_legacy_chat_unaffected_by_boundary_guard \
  tests/test_api_sse_contract.py \
  $PYTEST_FLAGS

echo "[V2-PHASE2] admin/public route guard smoke"
"$PYTHON_BIN" -m pytest \
  tests/test_runtime_registry.py::test_public_runtimes_route_hides_internal_fields \
  tests/test_boundary_guard.py::test_boundary_violations_admin_route_403_non_admin \
  $PYTEST_FLAGS

echo "[V2-PHASE2] optional full regression"
if [[ "${RUN_FULL_SUITE:-0}" == "1" ]]; then
  "$PYTHON_BIN" -m pytest tests/ $PYTEST_FLAGS
else
  echo "[V2-PHASE2] skip full suite (set RUN_FULL_SUITE=1 to enable)"
fi

echo "[V2-PHASE2] all selected checks passed"
