import pytest

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
