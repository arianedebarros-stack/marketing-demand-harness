"""Escolhe o cliente de LLM pelas settings (``LLM_PROVIDER``, ``LLM_FALLBACK``, D36, D37).

``anthropic`` usa o ``AnthropicClient``; se ele falhar e ``LLM_FALLBACK=true``, a interpretação
cai no FakeLLMClient (registrado no audit como ``llm_fallback``). Sem fallback, a API devolve 502.
"""

from __future__ import annotations

from app.core.config import Settings
from app.llm.anthropic_client import AnthropicClient
from app.llm.base import LLMClient
from app.llm.fake_client import FakeLLMClient
from app.llm.fallback import FallbackLLMClient


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "fake":
        return FakeLLMClient()
    fallback = FakeLLMClient() if settings.llm_fallback else None
    return FallbackLLMClient(AnthropicClient.from_settings(settings), fallback)
