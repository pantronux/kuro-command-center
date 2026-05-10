#!/usr/bin/env bash
set -euo pipefail

# V2 HARDENED (-1..2) test runner with timestamped report artifact.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
PYTEST_FLAGS="${PYTEST_FLAGS:--x --tb=short}"
RUN_FULL_SUITE="${RUN_FULL_SUITE:-0}"
REPORT_DIR="${REPORT_DIR:-backups/pre-v2}"
TS="$(date +%Y%m%d_%H%M%S)"
REPORT_FILE="$REPORT_DIR/v2_phase2_test_report_${TS}.txt"

mkdir -p "$REPORT_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "[ERROR] $PYTHON_BIN not found" | tee "$REPORT_FILE"
  exit 1
fi

exec > >(tee -a "$REPORT_FILE") 2>&1

echo "=== KURO V2 PHASE2 TEST REPORT ==="
echo "timestamp: $(date -Iseconds)"
echo "root: $ROOT_DIR"
echo "python: $PYTHON_BIN"
echo "pytest_flags: $PYTEST_FLAGS"
echo "run_full_suite: $RUN_FULL_SUITE"
echo

run_step() {
  local title="$1"
  shift
  echo "---- $title ----"
  "$@"
  echo "PASS: $title"
  echo
}

run_step "Compile check" \
  "$PYTHON_BIN" -m compileall kuro_backend main.py

run_step "Prompt 1 focused tests" \
  "$PYTHON_BIN" -m pytest tests/test_runtime_registry.py $PYTEST_FLAGS

run_step "Prompt 2 focused tests" \
  "$PYTHON_BIN" -m pytest tests/test_boundary_guard.py $PYTEST_FLAGS

run_step "Legacy stream compatibility smoke (mocked)" \
  "$PYTHON_BIN" -m pytest \
  tests/test_runtime_registry.py::test_legacy_chat_no_runtime_id_works \
  tests/test_boundary_guard.py::test_legacy_chat_unaffected_by_boundary_guard \
  tests/test_api_sse_contract.py \
  $PYTEST_FLAGS

run_step "Public/Admin route guard smoke" \
  "$PYTHON_BIN" -m pytest \
  tests/test_runtime_registry.py::test_public_runtimes_route_hides_internal_fields \
  tests/test_boundary_guard.py::test_boundary_violations_admin_route_403_non_admin \
  $PYTEST_FLAGS

if [[ "$RUN_FULL_SUITE" == "1" ]]; then
  run_step "Full regression tests/" \
    "$PYTHON_BIN" -m pytest tests/ $PYTEST_FLAGS
else
  echo "SKIP: Full regression (set RUN_FULL_SUITE=1 to enable)"
  echo
fi

echo "=== RESULT: ALL SELECTED CHECKS PASSED ==="
echo "report_file: $REPORT_FILE"
