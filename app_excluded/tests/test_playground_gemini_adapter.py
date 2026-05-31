from __future__ import annotations

from playground_runtime.providers.adapters.base_adapter import ProviderRequest
from playground_runtime.providers.adapters.gemini_adapter import GeminiAdapter


class _DummyResponse:
    def __init__(self):
        self._payload = {
            "id": "resp-1",
            "model": "gemini-3-flash-preview",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def test_gemini_adapter_uses_google_openai_compat_endpoint(monkeypatch):
    captured = {}

    def _fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _DummyResponse()

    monkeypatch.setattr("playground_runtime.providers.adapters.gemini_adapter.requests.post", _fake_post)

    adapter = GeminiAdapter(api_key="dummy-key", default_model="gemini-3-flash-preview")
    resp = adapter.invoke(ProviderRequest(prompt="hello", model=""))

    assert captured["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer dummy-key"
    assert resp.provider_id == "gemini"
    assert resp.response_text == "ok"
