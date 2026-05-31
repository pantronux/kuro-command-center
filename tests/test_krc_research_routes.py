from __future__ import annotations

from fastapi.testclient import TestClient

import main


def _client(monkeypatch, username: str = "Pantronux") -> TestClient:
    monkeypatch.setattr(main, "validate_token", lambda token: {"username": username})
    return TestClient(main.app)


def _cookies():
    return {main.COOKIE_NAME: "Bearer dummy"}


def test_research_routes_require_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("KURO_RESEARCH_DB_PATH", str(tmp_path / "research.db"))

    response = TestClient(main.app).get("/api/research/projects")

    assert response.status_code == 401


def test_research_project_source_claim_and_argument_map(monkeypatch, tmp_path):
    monkeypatch.setenv("KURO_RESEARCH_DB_PATH", str(tmp_path / "research.db"))
    client = _client(monkeypatch)

    project = client.post(
        "/api/research/projects",
        json={"title": "PhD topic", "description": "SE research"},
        cookies=_cookies(),
    ).json()["project"]
    project_id = project["project_id"]

    source = client.post(
        "/api/research/sources",
        json={"project_id": project_id, "title": "A paper", "authors": ["A. Author"], "year": 2026},
        cookies=_cookies(),
    ).json()["source"]

    claim = client.post(
        "/api/research/claims",
        json={
            "project_id": project_id,
            "source_id": source["source_id"],
            "claim_text": "The method improves traceability.",
            "confidence": 0.7,
        },
        cookies=_cookies(),
    )
    assert claim.status_code == 200

    question = client.post(
        "/api/research/questions",
        json={"project_id": project_id, "question": "What is the novelty?"},
        cookies=_cookies(),
    )
    assert question.status_code == 200

    gap = client.post(
        "/api/research/novelty-gaps",
        json={"project_id": project_id, "description": "Existing work does not cover runtime provenance."},
        cookies=_cookies(),
    )
    assert gap.status_code == 200

    node_a = client.post(
        "/api/research/argument-map/nodes",
        json={"project_id": project_id, "label": "Claim A"},
        cookies=_cookies(),
    ).json()["node"]
    node_b = client.post(
        "/api/research/argument-map/nodes",
        json={"project_id": project_id, "label": "Evidence B", "node_type": "evidence"},
        cookies=_cookies(),
    ).json()["node"]
    edge = client.post(
        "/api/research/argument-map/edges",
        json={
            "project_id": project_id,
            "from_node_id": node_b["node_id"],
            "to_node_id": node_a["node_id"],
            "relation": "supports",
        },
        cookies=_cookies(),
    )
    assert edge.status_code == 200

    graph = client.get(f"/api/research/argument-map?project_id={project_id}", cookies=_cookies()).json()
    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) == 1


def test_research_user_isolation(monkeypatch, tmp_path):
    monkeypatch.setenv("KURO_RESEARCH_DB_PATH", str(tmp_path / "research.db"))
    project = _client(monkeypatch, "Pantronux").post(
        "/api/research/projects",
        json={"title": "Private project"},
        cookies=_cookies(),
    ).json()["project"]

    response = _client(monkeypatch, "Faikhira").get(
        f"/api/research/projects/{project['project_id']}",
        cookies=_cookies(),
    )

    assert response.status_code == 404
