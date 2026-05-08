import importlib
import json
import logging
from pathlib import Path

import pytest


logger = logging.getLogger("conftest")

_DB_MODULES = (
    ("kuro_backend.chat_history", "DB_PATH", "kuro_chat_history.db", "init_db", True),
    ("kuro_backend.auth_db", "DB_PATH", "kuro_auth.db", "init_auth_db", True),
    ("kuro_backend.intelligence_db", "DB_PATH", "kuro_intelligence.db", "init_db", True),
    ("kuro_backend.compliance_db", "DB_PATH", "kuro_compliance.db", "init_db", False),
)


@pytest.fixture(autouse=True)
def reset_schema_caches():
    try:
        from kuro_backend.services import core_service

        core_service._reset_schema_ready_for_tests()
    except Exception:
        pass

    try:
        from kuro_backend import memory_manager

        memory_manager._reset_short_term_schema_ready_for_tests()
    except Exception:
        pass


@pytest.fixture(scope="function", autouse=True)
def isolate_all_dbs(tmp_path, monkeypatch):
    """Redirect runtime DB and JSON state paths into a per-test tmp directory."""
    tmp_path = Path(tmp_path)
    _write_runtime_state_files(tmp_path)

    for module_name, path_attr, filename, init_name, fail_fast in _DB_MODULES:
        try:
            module = importlib.import_module(module_name)
            monkeypatch.setattr(module, path_attr, str(tmp_path / filename))
            if hasattr(module, "_reset_schema_ready_for_tests"):
                module._reset_schema_ready_for_tests()
            init_fn = getattr(module, init_name, None)
            if callable(init_fn):
                init_fn()
        except Exception as exc:
            if fail_fast:
                raise RuntimeError(
                    f"DB isolation setup failed for {module_name}: {exc}"
                ) from exc
            logger.warning("DB isolation warning for %s: %s", module_name, exc)

    from kuro_backend import finance_db

    finance_path = tmp_path / "kuro_finances.db"
    monkeypatch.setenv("KURO_FINANCE_DB_PATH", str(finance_path))
    monkeypatch.setattr(finance_db, "DB_PATH", str(finance_path), raising=False)
    finance_db._reset_schema_ready_for_tests()
    finance_db.init_db()

    from kuro_backend import memory_manager
    from kuro_backend.services import core_service

    short_term_path = tmp_path / "kuro_short_term.db"
    profile_path = tmp_path / "master_profile.json"
    memory_blob_path = tmp_path / "kuro_memory.json"

    monkeypatch.setenv("KURO_SHORT_TERM_DB_PATH", str(short_term_path))
    monkeypatch.setattr(memory_manager, "SHORT_TERM_DB", str(short_term_path), raising=False)
    monkeypatch.setattr(memory_manager, "MASTER_PROFILE_PATH", str(profile_path), raising=False)
    monkeypatch.setattr(core_service, "SHORT_TERM_DB_PATH", str(short_term_path), raising=False)
    core_service._reset_schema_ready_for_tests()
    memory_manager._reset_short_term_schema_ready_for_tests()

    if not profile_path.exists():
        profile_path.write_text(
            json.dumps(
                {
                    "shared": {
                        "infrastructure": {},
                        "compliance_standards": {},
                        "cross_mapping": {},
                        "notes": [],
                    },
                    "users": {"Pantronux": {"master": {"name": "Pantronux"}, "preferences": {}}},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    if not memory_blob_path.exists():
        memory_blob_path.write_text("{}", encoding="utf-8")

    memory_manager.init_short_term_db()
    core_service.get_data_revision()

    yield


def _write_runtime_state_files(tmp_path: Path) -> None:
    (tmp_path / "master_profile.json").write_text(
        json.dumps(
            {
                "shared": {
                    "infrastructure": {},
                    "compliance_standards": {},
                    "cross_mapping": {},
                    "notes": [],
                },
                "users": {"Pantronux": {"master": {"name": "Pantronux"}, "preferences": {}}},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (tmp_path / "kuro_memory.json").write_text("{}", encoding="utf-8")
