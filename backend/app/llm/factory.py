"""Escolhe o cliente de LLM pelas settings (``LLM_PROVIDER``, ``LLM_FALLBACK``).

O ``AnthropicClient`` chega na T16. Até lá, ``anthropic`` falha de propósito e, com
``LLM_FALLBACK=true``, a interpretação cai no FakeLLMClient (registrado no audit).
"""

from __future__ import annotations

from app.core.config import Settings
from app.llm.base import InterpretationContext, LLMClient
from app.llm.fake_client import FakeLLMClient
from app.llm.fallback import FallbackLLMClient
from app.schemas.llm import LLMInterpretation


class _AnthropicNotAvailable:
    provider = "anthropic"

    def interpret(self, context: InterpretationContext) -> LLMInterpretation:
        raise RuntimeError("AnthropicClient ainda não implementado (T16)")


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "fake":
        return FakeLLMClient()
    fallback = FakeLLMClient() if settings.llm_fallback else None
    return FallbackLLMClient(_AnthropicNotAvailable(), fallback)
