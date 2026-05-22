"""Ollama local HTTP adapter for Provider Registry V2."""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Any, AsyncIterator, Dict, List, Optional

from kuro_backend.config import settings
from kuro_backend.providers.base import BaseProvider, done_event, error_event, text_delta_event
from kuro_backend.providers.errors import ProviderUnavailableError
from kuro_backend.providers.schemas import (
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
    ProviderStatus,
    ProviderStreamEvent,
)
from kuro_backend.providers.usage import estimate_request_usage


logger = logging.getLogger(__name__)


class OllamaProvider(BaseProvider):
    provider_id = "ollama"
    display_name = "Local Ollama"
    api_key_attr = ""
    sdk_module_name = ""
    supports_streaming = True
    supports_tools = False
    supports_structured_output = True

    def enabled(self) -> bool:
        return bool(getattr(settings, "KURO_OLLAMA_ENABLED", False))

    def base_url(self) -> str:
        return str(getattr(settings, "KURO_OLLAMA_BASE_URL", "http://localhost:11434") or "").rstrip("/")

    def openai_base_url(self) -> str:
        return str(
            getattr(settings, "KURO_OLLAMA_OPENAI_BASE_URL", "http://localhost:11434/v1") or ""
        ).rstrip("/")

    def timeout_s(self) -> float:
        return float(getattr(settings, "KURO_OLLAMA_TIMEOUT_S", 60) or 60)

    def stream_timeout_s(self) -> float:
        return float(getattr(settings, "KURO_OLLAMA_STREAM_TIMEOUT_S", 120) or 120)

    def default_model(self) -> str:
        return str(
            getattr(settings, "KURO_MODEL_OLLAMA_LOCAL", "")
            or getattr(settings, "KURO_OLLAMA_DEFAULT_MODEL", "qwen")
            or "qwen"
        ).strip()

    def use_openai_compat(self) -> bool:
        return bool(getattr(settings, "KURO_OLLAMA_USE_OPENAI_COMPAT", False))

    def allow_public_model_list(self) -> bool:
        return bool(getattr(settings, "KURO_OLLAMA_ALLOW_PUBLIC_MODEL_LIST", False))

    def is_configured(self) -> bool:
        return bool(self.enabled() and self.base_url())

    def availability(self) -> ProviderStatus:
        if not self.enabled():
            return ProviderStatus(
                provider=self.provider_id,
                display_name=self.display_name,
                available=False,
                reason="disabled",
                configured=False,
                dependency_available=True,
                supports_streaming=self.supports_streaming,
                supports_tools=self.supports_tools,
                supports_structured_output=self.supports_structured_output,
            )
        if not self.base_url():
            return ProviderStatus(
                provider=self.provider_id,
                display_name=self.display_name,
                available=False,
                reason="missing_base_url",
                configured=False,
                dependency_available=True,
                supports_streaming=self.supports_streaming,
                supports_tools=self.supports_tools,
                supports_structured_output=self.supports_structured_output,
            )
        return ProviderStatus(
            provider=self.provider_id,
            display_name=self.display_name,
            available=True,
            reason="configured",
            configured=True,
            dependency_available=True,
            supports_streaming=self.supports_streaming,
            supports_tools=self.supports_tools,
            supports_structured_output=self.supports_structured_output,
        )

    def _content_to_text(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        try:
            return json.dumps(content, ensure_ascii=True)
        except TypeError:
            return str(content)

    def _messages(self, request: ProviderRequest) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        if request.system_instruction:
            messages.append({"role": "system", "content": str(request.system_instruction)})
        if request.structured_output_schema:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Return valid JSON only. Do not use markdown fences. "
                        "If unsure, return the closest JSON object you can."
                    ),
                }
            )
        for message in request.messages:
            messages.append(
                {
                    "role": str(message.role or "user"),
                    "content": self._content_to_text(message.content),
                }
            )
        return messages

    def _native_payload(self, request: ProviderRequest, *, model_id: str, stream: bool) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model_id,
            "messages": self._messages(request),
            "stream": stream,
            "options": {
                "temperature": float(request.temperature),
                "num_predict": int(request.max_output_tokens),
            },
        }
        if request.structured_output_schema:
            payload["format"] = "json"
        return payload

    def _openai_payload(self, request: ProviderRequest, *, model_id: str, stream: bool) -> Dict[str, Any]:
        return {
            "model": model_id,
            "messages": self._messages(request),
            "temperature": float(request.temperature),
            "max_tokens": int(request.max_output_tokens),
            "stream": stream,
        }

    def _post_json(self, url: str, payload: Dict[str, Any], *, timeout_s: float) -> Dict[str, Any]:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as response:
                raw_text = response.read().decode("utf-8")
        except Exception as exc:
            raise self._provider_error(exc) from None
        try:
            raw = json.loads(raw_text or "{}")
        except json.JSONDecodeError as exc:
            raise ProviderUnavailableError("invalid_response") from exc
        if not isinstance(raw, dict):
            raise ProviderUnavailableError("invalid_response")
        return raw

    def _try_structured(self, request: ProviderRequest, content: str) -> Optional[Any]:
        if not request.structured_output_schema:
            return None
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    def _provider_error(self, exc: BaseException) -> ProviderUnavailableError:
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return ProviderUnavailableError("provider_timeout")
        if isinstance(exc, urllib.error.URLError):
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                return ProviderUnavailableError("provider_timeout")
            return ProviderUnavailableError("connection_error")
        return ProviderUnavailableError("provider_unavailable")

    def _list_models(self) -> List[str]:
        url = f"{self.base_url()}/api/tags"
        req = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s()) as response:
                raw = json.loads(response.read().decode("utf-8") or "{}")
        except Exception as exc:
            raise self._provider_error(exc) from None
        models = raw.get("models") if isinstance(raw, dict) else []
        names: List[str] = []
        for item in models or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("model") or "").strip()
            if name:
                names.append(name)
        return list(dict.fromkeys(names))

    def health_check(self, *, include_models: bool = True, public: bool = False) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "provider": self.provider_id,
            "enabled": self.enabled(),
            "status": "disabled",
            "model_aliases": ["ollama_local"],
        }
        if not public:
            result["base_url"] = self.base_url()
        if not self.enabled():
            return result
        if not self.base_url():
            result.update({"status": "unavailable", "reason": "missing_base_url"})
            return result
        try:
            models = self._list_models()
        except ProviderUnavailableError as exc:
            result.update({"status": "unavailable", "reason": str(exc)})
            return result
        default_model = self.default_model()
        result.update({"status": "ok", "default_model": default_model})
        if include_models and (not public or self.allow_public_model_list()):
            result["models"] = models
        if models and default_model not in models:
            result["status"] = "degraded"
            result["reason"] = "default_model_not_found"
        return result

    async def list_models(self) -> Dict[str, Any]:
        if not self.enabled():
            return {"provider": self.provider_id, "enabled": False, "models": []}
        models = await asyncio.to_thread(self._list_models)
        return {
            "provider": self.provider_id,
            "enabled": True,
            "models": models,
            "default_model": self.default_model(),
        }

    async def generate(self, request: ProviderRequest, *, model_id: str) -> ProviderResponse:
        if not self.enabled():
            raise ProviderUnavailableError("ollama_disabled")
        resolved_model = self.resolve_model_id(request, model_id or self.default_model())
        if self.use_openai_compat():
            return await self._generate_openai_compat(request, model_id=resolved_model)
        return await self._generate_native(request, model_id=resolved_model)

    async def _generate_native(self, request: ProviderRequest, *, model_id: str) -> ProviderResponse:
        start = time.perf_counter()
        url = f"{self.base_url()}/api/chat"
        payload = self._native_payload(request, model_id=model_id, stream=False)
        raw = await asyncio.to_thread(self._post_json, url, payload, timeout_s=self.timeout_s())
        content = str(((raw.get("message") or {}).get("content")) or "")
        structured = self._try_structured(request, content)
        finish_reason = "stop"
        if request.structured_output_schema and structured is None:
            finish_reason = "schema_not_guaranteed"
        return ProviderResponse(
            provider=self.provider_id,
            model_id=model_id,
            content=content,
            structured=structured,
            raw=raw,
            usage=estimate_request_usage(
                [ProviderMessage(role=m["role"], content=m["content"]) for m in self._messages(request)],
                content,
            ),
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
            finish_reason=finish_reason,
            safety={"tools_executed": False},
            trace_id=request.trace_id,
        )

    async def _generate_openai_compat(self, request: ProviderRequest, *, model_id: str) -> ProviderResponse:
        start = time.perf_counter()
        url = f"{self.openai_base_url()}/chat/completions"
        payload = self._openai_payload(request, model_id=model_id, stream=False)
        raw = await asyncio.to_thread(self._post_json, url, payload, timeout_s=self.timeout_s())
        choice = (raw.get("choices") or [{}])[0]
        content = str(((choice.get("message") or {}).get("content")) or "")
        structured = self._try_structured(request, content)
        finish_reason = str(choice.get("finish_reason") or "stop")
        if request.structured_output_schema and structured is None:
            finish_reason = "schema_not_guaranteed"
        return ProviderResponse(
            provider=self.provider_id,
            model_id=model_id,
            content=content,
            structured=structured,
            raw=raw,
            usage=estimate_request_usage(
                [ProviderMessage(role=m["role"], content=m["content"]) for m in self._messages(request)],
                content,
            ),
            latency_ms=round((time.perf_counter() - start) * 1000, 2),
            finish_reason=finish_reason,
            safety={"tools_executed": False},
            trace_id=request.trace_id,
        )

    async def stream(self, request: ProviderRequest, *, model_id: str) -> AsyncIterator[ProviderStreamEvent]:
        if not self.enabled():
            yield error_event("ollama_disabled", trace_id=request.trace_id)
            yield done_event(trace_id=request.trace_id)
            return
        resolved_model = self.resolve_model_id(request, model_id or self.default_model())
        if self.use_openai_compat():
            yield error_event("ollama_openai_compat_streaming_unsupported", trace_id=request.trace_id)
            yield done_event(trace_id=request.trace_id)
            return

        queue: asyncio.Queue[ProviderStreamEvent] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _put(event: ProviderStreamEvent) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        def _worker() -> None:
            url = f"{self.base_url()}/api/chat"
            payload = self._native_payload(request, model_id=resolved_model, stream=True)
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.stream_timeout_s()) as response:
                    for raw_line in response:
                        line = raw_line.decode("utf-8").strip()
                        if not line:
                            continue
                        try:
                            raw = json.loads(line)
                        except json.JSONDecodeError:
                            _put(error_event("invalid_stream_chunk", trace_id=request.trace_id))
                            continue
                        delta = str(((raw.get("message") or {}).get("content")) or "")
                        if delta:
                            _put(text_delta_event(delta, trace_id=request.trace_id))
                        if raw.get("done") is True:
                            break
            except Exception as exc:
                _put(error_event(str(self._provider_error(exc)), trace_id=request.trace_id))
            finally:
                _put(done_event(trace_id=request.trace_id))

        threading.Thread(target=_worker, name="kuro-ollama-stream", daemon=True).start()
        while True:
            event = await queue.get()
            yield event
            if event.done:
                return
