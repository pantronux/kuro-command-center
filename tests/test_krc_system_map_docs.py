from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_system_map_documents_krc_and_ks_boundary():
    system_map = (PROJECT_ROOT / "SYSTEM_MAP.md").read_text()

    assert "Kuro Research Center" in system_map
    assert "Kuro Stack" in system_map
    assert "KURO_APP_ROLE" in system_map
    assert "KURO_APP_PROFILE" in system_map
    assert "kuro_backend/knowledge_center/" in system_map
    assert "kuro_backend/research_center/" in system_map
    assert "/api/knowledge/search-approved" in system_map
    assert "Kuro Command Center" in system_map
    assert "phd_advisor" in system_map
    assert "KURO_KRC_QA_PLAYGROUND_ENABLED=false" in system_map
    assert "/api/chat/stream" in system_map


def test_app_split_docs_include_final_acceptance():
    docs_dir = PROJECT_ROOT / "docs" / "app_split"
    readme = (docs_dir / "README.md").read_text()
    acceptance = (docs_dir / "final_acceptance.md").read_text()

    assert "final_acceptance.md" in readme
    assert "Kuro Stack remains separate for daily chat" in acceptance
    assert "Candidate write is disabled by default" in acceptance
    assert "phd_advisor" in acceptance


def test_krc_refocus_docs_include_final_acceptance():
    docs_dir = PROJECT_ROOT / "docs" / "krc_refocus"
    readme = (docs_dir / "README.md").read_text()
    acceptance = (docs_dir / "final_acceptance.md").read_text()

    assert "final_acceptance.md" in readme
    assert "KS remains separate for daily chat" in acceptance
    assert "Candidate write disabled by default" in acceptance
    assert "Kuro Playground" in acceptance
