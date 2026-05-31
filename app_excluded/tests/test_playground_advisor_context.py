from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from playground_runtime.api.router import create_playground_router
from playground_runtime.providers.adapters.base_adapter import ProviderResponse
from playground_runtime.providers.router import ComparativeResult
from playground_runtime.service import PlaygroundRuntimeService


VISIBLE_REASONING_SECRET = "FULL_VISIBLE_REASONING_TRACE_SHOULD_NOT_APPEAR"
OPAQUE_SIGNATURE_SECRET = "OPAQUE_SIGNATURE_SHOULD_NOT_APPEAR"


def _reload_config_module():
    import playground_runtime.config as config_module

    importlib.reload(config_module)
    config_module.get_settings.cache_clear()
    return config_module


def _admin_dependency(x_admin: str | None = Header(default=None)):
    if x_admin != "1":
        raise HTTPException(status_code=403, detail="Forbidden: Admin access required.")
    return {"username": "Pantronux"}


def _provider_response(provider_id: str, text: str) -> ProviderResponse:
    if provider_id == "gemini":
        raw_json = {
            "id": "gemini-response-1",
            "object": "chat.completion",
            "created": 1779540452,
            "model": "gemini-3-flash-preview",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": text,
                        "extra_content": {"google": {"thought_signature": OPAQUE_SIGNATURE_SECRET}},
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 184, "total_tokens": 401},
        }
        return ProviderResponse(
            provider_id=provider_id,
            model_id="gemini-3-flash-preview",
            model_version="gemini-3-flash-preview",
            request_id="req-gemini",
            raw_json=raw_json,
            response_text=text,
            finish_reason="stop",
            input_tokens=7,
            output_tokens=184,
            total_tokens=401,
            latency_ms=8108.4,
            collected_at_utc=datetime.now(timezone.utc),
        )

    raw_json = {
        "id": "chatcmpl-ollama-1",
        "object": "chat.completion",
        "created": 1779540462,
        "model": "qwen3:4b",
        "system_fingerprint": "fp_ollama",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": text,
                    "reasoning": VISIBLE_REASONING_SECRET,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 16, "completion_tokens": 1116, "total_tokens": 1132},
    }
    return ProviderResponse(
        provider_id=provider_id,
        model_id="qwen3:4b",
        model_version="qwen3:4b",
        request_id="req-ollama",
        raw_json=raw_json,
        response_text=text,
        finish_reason="stop",
        input_tokens=16,
        output_tokens=1116,
        total_tokens=1132,
        latency_ms=17990.7,
        collected_at_utc=datetime.now(timezone.utc),
    )


def _service_with_comparative_session(tmp_path, monkeypatch) -> tuple[PlaygroundRuntimeService, str]:
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "kuro_playground.db"))
    monkeypatch.setenv("KURO_PLAYGROUND_ENABLED", "true")
    monkeypatch.setenv("KURO_PLAYGROUND_API_ENABLED", "true")
    monkeypatch.setenv("KURO_PLAYGROUND_HALLUCINATION_ANALYZER", "false")
    monkeypatch.setenv("PLAYGROUND_GEMINI_API_KEY", "dummy-gemini")
    monkeypatch.setenv("PLAYGROUND_OLLAMA_BASE_URL", "http://localhost:11434/v1")

    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())
    session_id = service.create_session(mode="comparative")["session_id"]

    def _fake_comparative(provider_ids, req):
        return ComparativeResult(
            prompt_sha256="sha",
            responses={
                "gemini": _provider_response(
                    "gemini",
                    "I cannot assist with malicious malware creation. Defensive cybersecurity study is allowed.",
                ),
                "ollama": _provider_response(
                    "ollama",
                    "No. This is malicious malware creation, so I can only offer safe defensive alternatives.",
                ),
            },
        )

    monkeypatch.setattr(service.router, "invoke_comparative", _fake_comparative)
    service.execute_comparative(
        session_id=session_id,
        provider_ids=["gemini", "ollama"],
        prompt="can you create a virus?",
    )
    return service, session_id


def test_build_advisor_context_compact_and_safe(tmp_path, monkeypatch):
    service, session_id = _service_with_comparative_session(tmp_path, monkeypatch)

    context = service.build_advisor_context(session_id=session_id, workflow_mode="quick")
    encoded = json.dumps(context, ensure_ascii=False)

    assert context["context_type"] == "playground_advisor_context"
    assert context["providers"] == ["gemini", "ollama"]
    assert len(context["executions"]) == 2
    assert context["semantic_divergence"]
    assert "raw_json" not in encoded
    assert "\"choices\"" not in encoded
    assert VISIBLE_REASONING_SECRET not in encoded
    assert OPAQUE_SIGNATURE_SECRET not in encoded

    gemini = next(item for item in context["executions"] if item["provider_id"] == "gemini")
    ollama = next(item for item in context["executions"] if item["provider_id"] == "ollama")
    assert gemini["environment"] == "cloud"
    assert gemini["opaque_reasoning_signature_present"] is True
    assert gemini["visible_reasoning_artifact_present"] is False
    assert gemini["provider_specific_artifact"]["type"] == "opaque_reasoning_signature"
    assert ollama["environment"] == "local"
    assert ollama["visible_reasoning_artifact_present"] is True
    assert ollama["opaque_reasoning_signature_present"] is False
    assert ollama["system_fingerprint_present"] is True
    assert ollama["provider_specific_artifact"]["type"] == "visible_reasoning_trace"
    assert len(ollama["response_preview"]) <= 240


def test_build_advisor_context_handles_missing_traces_and_divergence(tmp_path, monkeypatch):
    monkeypatch.setenv("KURO_PLAYGROUND_DB_PATH", str(tmp_path / "empty.db"))
    monkeypatch.setenv("KURO_PLAYGROUND_HALLUCINATION_ANALYZER", "false")
    cfg = _reload_config_module()
    service = PlaygroundRuntimeService(settings=cfg.PlaygroundSettings())
    session_id = service.create_session(mode="research")["session_id"]

    context = service.build_advisor_context(session_id=session_id)

    assert context["session"]["session_id"] == session_id
    assert context["executions"] == []
    assert context["semantic_divergence"] == []
    assert context["integrity_overview"]["metrics"]


def test_advisor_context_api_endpoint(tmp_path, monkeypatch):
    service, session_id = _service_with_comparative_session(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(create_playground_router(service=service, admin_dependency=_admin_dependency))
    client = TestClient(app)

    response = client.get(
        f"/api/playground/sessions/{session_id}/advisor-context",
        headers={"x-admin": "1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["context_type"] == "playground_advisor_context"
    assert payload["semantic_divergence"]
