from __future__ import annotations

from playground_runtime.providers.adapters.base_adapter import ProviderRequest
from playground_runtime.providers.adapters.openai_compat_adapter import OpenAICompatAdapter


class _DummyResponse:
    def __init__(self):
        self._payload = {
            "id": "resp-ollama-1",
            "model": "qwen3:4b",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


def _capture_post(monkeypatch):
    captured = {}

    def _fake_post(url, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _DummyResponse()

    monkeypatch.setattr(
        "playground_runtime.providers.adapters.openai_compat_adapter.requests.post",
        _fake_post,
    )
    return captured


def test_openai_compat_url_from_v1_base(monkeypatch):
    captured = _capture_post(monkeypatch)
    adapter = OpenAICompatAdapter(
        provider_id="ollama",
        base_url="http://localhost:11434/v1",
        api_key=None,
        default_model="qwen3:4b",
    )

    adapter.invoke(ProviderRequest(prompt="hello", model=""))

    assert captured["url"] == "http://localhost:11434/v1/chat/completions"


def test_openai_compat_url_from_root_base(monkeypatch):
    captured = _capture_post(monkeypatch)
    adapter = OpenAICompatAdapter(
        provider_id="ollama",
        base_url="http://localhost:11434",
        api_key=None,
        default_model="qwen3:4b",
    )

    adapter.invoke(ProviderRequest(prompt="hello", model=""))

    assert captured["url"] == "http://localhost:11434/v1/chat/completions"


def test_openai_compat_url_from_full_chat_endpoint(monkeypatch):
    captured = _capture_post(monkeypatch)
    adapter = OpenAICompatAdapter(
        provider_id="openai_compat",
        base_url="http://localhost:11434/v1/chat/completions",
        api_key=None,
        default_model="qwen3:4b",
    )

    adapter.invoke(ProviderRequest(prompt="hello", model=""))

    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
