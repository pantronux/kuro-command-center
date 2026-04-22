"""
Register LangChain ChatGoogleGenerativeAI with NeMo under engine name `kuro_gemini`.
Must be imported before RailsConfig.from_path loads models.

--- Header Doc ---
Purpose: NeMo Guardrails engine registration for Gemini (one-time import-side-effect).
Caller: guardrails.sniper_pipeline at startup.
Dependencies: nemoguardrails, langchain-google-genai, kuro_backend.config.
Main Functions: register_engine().
Side Effects: Mutates nemoguardrails engine registry (global).
"""
from __future__ import annotations

import logging

from langchain_google_genai import ChatGoogleGenerativeAI
from nemoguardrails.llm.providers import register_chat_provider

logger = logging.getLogger(__name__)

_registered = False


class KuroGeminiChat(ChatGoogleGenerativeAI):
    """Gemini via Google AI API key (same credentials as rest of Kuro)."""

    def __init__(self, **kwargs):
        # Late import so Django-like apps can load without env
        from kuro_backend.config import PRIMARY_MODEL, settings

        kwargs.setdefault("google_api_key", settings.GEMINI_API_KEY)
        kwargs.setdefault("model", PRIMARY_MODEL)
        super().__init__(**kwargs)

    def _prepare_request(self, messages, **kwargs):
        # NeMo self-check passes OpenAI-style max_tokens; google-genai expects max_output_tokens.
        if "max_tokens" in kwargs:
            mt = kwargs.pop("max_tokens")
            kwargs.setdefault("max_output_tokens", mt)
        gen_cfg = kwargs.get("generation_config")
        if isinstance(gen_cfg, dict) and "max_tokens" in gen_cfg:
            gen_cfg = dict(gen_cfg)
            gen_cfg["max_output_tokens"] = gen_cfg.pop("max_tokens")
            kwargs["generation_config"] = gen_cfg
        return super()._prepare_request(messages, **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if "max_tokens" in kwargs:
            mt = kwargs.pop("max_tokens")
            kwargs.setdefault("max_output_tokens", mt)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        if "max_tokens" in kwargs:
            mt = kwargs.pop("max_tokens")
            kwargs.setdefault("max_output_tokens", mt)
        return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)


def ensure_nemo_providers_registered() -> None:
    global _registered
    if _registered:
        return
    register_chat_provider("kuro_gemini", KuroGeminiChat)
    _registered = True
    logger.debug("[NEMO] Registered chat provider kuro_gemini")
