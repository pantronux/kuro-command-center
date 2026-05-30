from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from kuro_backend.kuro_stack_handoff import (
    build_kuro_stack_analysis_prompt,
    create_kuro_stack_handoff_router,
)


class DummyPlaygroundService:
    def build_session_json_artifact(self, session_id: str, artifact_type: str):
        assert artifact_type == "session"
        return (
            f"playground-session-{session_id}.json",
            json.dumps(
                {
                    "session": {"session_id": session_id, "mode": "comparative"},
                    "integrity_overview": {"trust_state": "VERIFIED"},
                    "semantic_divergence": {"count": 1},
                }
            ),
        )


def _auth_dependency():
    return {"username": "Pantronux"}


def test_prompt_template_tracks_analysis_mode_and_json():
    prompt = build_kuro_stack_analysis_prompt(
        session_id="s-1",
        source_label="unit",
        json_text='{"session":{"mode":"forensic"}}',
        analysis_mode="integrity",
        workflow_mode="deep",
    )

    assert "Tolong audit integrity artifact ini" in prompt
    assert 'query="KRC Playground Runtime"' in prompt
    assert '"mode": "forensic"' in prompt
    assert "Mode review: deep" in prompt


def test_handoff_router_creates_openwebui_chat(monkeypatch):
    captured = {}

    def fake_create_chat(prompt: str):
        captured["prompt"] = prompt
        return "chat-123", "kuro-kg-gemini-3.1-pro"

    monkeypatch.setattr("kuro_backend.kuro_stack_handoff.create_openwebui_analysis_chat", fake_create_chat)
    monkeypatch.setattr("kuro_backend.kuro_stack_handoff.update_openwebui_chat_title", lambda *_args, **_kwargs: None)

    app = FastAPI()
    app.state.playground_service = DummyPlaygroundService()
    app.include_router(create_kuro_stack_handoff_router(auth_dependency=_auth_dependency))
    client = TestClient(app)

    response = client.post(
        "/api/integrations/kuro-stack/analyze-playground",
        json={"session_id": "session-1", "analysis_mode": "divergence", "workflow_mode": "academic"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["chat_id"] == "chat-123"
    assert body["chat_url"] == "/c/chat-123"
    assert body["analysis_mode"] == "divergence"
    assert "semantic divergence" in captured["prompt"].lower()
    assert '"session_id": "session-1"' in captured["prompt"]

