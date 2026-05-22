"""Safety baseline guardrails for the enterprise refactor prep phase."""
from __future__ import annotations

import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKUP_DIR = PROJECT_ROOT / "backups" / "pre-enterprise-refactor"
BASELINE_DOC = PROJECT_ROOT / "docs" / "enterprise_refactor" / "01_safety_baseline.md"
RESTORE_DOC = PROJECT_ROOT / "docs" / "enterprise_refactor" / "01_restore_instructions.md"


def _git_check_ignore(path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "check-ignore", "--no-index", path],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_enterprise_refactor_backup_directory_exists_after_safety_prep():
    assert BACKUP_DIR.is_dir()
    assert (BACKUP_DIR / "db").is_dir()
    assert (BACKUP_DIR / "runtime_json").is_dir()


def test_enterprise_refactor_restore_and_baseline_docs_exist():
    assert BASELINE_DOC.is_file()
    assert RESTORE_DOC.is_file()

    baseline_text = BASELINE_DOC.read_text(encoding="utf-8")
    restore_text = RESTORE_DOC.read_text(encoding="utf-8")

    assert "Current commit hash" in baseline_text
    assert "SQLite Files Found" in baseline_text
    assert "Restore SQLite Files" in restore_text
    assert "Restore `.env`" in restore_text


def test_enterprise_refactor_runtime_artifacts_are_git_ignored():
    ignored_paths = [
        ".env",
        "backups/pre-enterprise-refactor/.env.backup",
        "kuro_memory.json",
        "master_profile.json",
        "kuro_chat_history.db",
        "kuro_chromadb/chroma.sqlite3",
        "sample.sqlite",
        "sample.sqlite3",
        "sample.sqlite-wal",
        "sample.sqlite3-wal",
        "uploaded_files/example.txt",
        "phoenix_data/phoenix.db",
    ]

    for path in ignored_paths:
        result = _git_check_ignore(path)
        assert result.returncode == 0, f"{path} should be ignored by git"
