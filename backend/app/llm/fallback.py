"""Fallback do LLM (§9): se o provedor principal falhar, usa o FakeLLMClient quando permitido.

Sem fallback (``LLM_FALLBACK=false``), a falha vira ``LLMUnavailableError`` e a API responde 502.
"""

from __future__ import annotations

from typing import Any

from app.llm.base import InterpretationContext, LLMClient
from app.schemas.llm import LLMInterpretation


class LLMUnavailableError(Exception):
    """O LLM falhou e não há fallback."""

    def __init__(self, provider: str, error: str) -> None:
        self.provider = provider
        self.error = error
        super().__init__(f"LLM {provider} indisponível: {error}")


class FallbackLLMClient:
    """Tenta o principal; se ele falhar, usa o fallback e guarda o que aconteceu para o audit."""

    def __init__(self, primary: LLMClient, fallback: LLMClient | None) -> None:
        self._primary = primary
        self._fallback = fallback
        self._used: LLMClient = primary
        self.last_fallback: dict[str, Any] | None = None

    @property
    def primary(self) -> LLMClient:
        return self._primary

    @property
    def provider(self) -> str:
        """Provedor que de fato respondeu a última interpretação."""
        return self._used.provider

    def interpret(self, context: InterpretationContext) -> LLMInterpretation:
        self.last_fallback = None
        self._used = self._primary
        try:
            return self._primary.interpret(context)
        except Exception as exc:  # noqa: BLE001 — qualquer falha do provedor externo
            if self._fallback is None:
                raise LLMUnavailableError(self._primary.provider, str(exc)) from exc
            self._used = self._fallback
            self.last_fallback = {
                "failed": self._primary.provider,
                "used": self._fallback.provider,
                "error": str(exc),
            }
            return self._fallback.interpret(context)
