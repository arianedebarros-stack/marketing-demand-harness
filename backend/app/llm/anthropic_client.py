"""Cliente do LLM real via SDK oficial da Anthropic (SPEC §8.1, D17, D37).

O modelo só interpreta: responde chamando a tool ``register_interpretation``, cujo
``input_schema`` é gerado de ``LLMInterpretation``. A resposta é validada pelo schema Pydantic e
depois passa pelos guardrails no pipeline. Nenhuma decisão é tomada aqui.

Detalhes do modelo padrão (Claude Opus 5.5, D17): ``tool_choice`` forçado (``any``/``tool``)
devolve 400, então a chamada usa ``auto`` com ``strict: true`` e uma instrução no prompt, e
confere se a tool foi chamada. O pensamento adaptativo é sempre ligado; o esforço é explícito.
"""

from __future__ import annotations

from typing import Any, Literal

import anthropic
from pydantic import ValidationError

from app.core.config import Settings
from app.llm.base import InterpretationContext
from app.llm.prompts import SYSTEM_PROMPT, TOOL_DESCRIPTION, TOOL_NAME, build_user_prompt
from app.schemas.llm import LLMInterpretation

Effort = Literal["low", "medium", "high", "xhigh", "max"]
FALLBACK_BETA = "server-side-fallback-2026-07-01"
DEFAULT_MAX_TOKENS = 16000
ATTEMPTS = 2  # tool_choice auto não garante a chamada: uma nova tentativa

# Palavras-chave de JSON Schema que o modo strict não aceita ou que não servem ao modelo.
_DROPPED_KEYS = frozenset(
    {"default", "title", "description", "minLength", "maxLength", "minimum", "maximum",
     "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minItems", "maxItems"}
)  # fmt: skip

__all__ = [
    "TOOL_NAME",
    "AnthropicClient",
    "LLMRefusalError",
    "LLMResponseError",
    "strict_input_schema",
]


class LLMResponseError(Exception):
    """O modelo respondeu, mas sem uma interpretação válida."""


class LLMRefusalError(LLMResponseError):
    """O modelo recusou o pedido (``stop_reason: refusal``)."""


def strict_input_schema() -> dict[str, Any]:
    """``input_schema`` da tool no formato do modo strict.

    Parte de ``LLMInterpretation.tool_input_schema()`` (sem ``$ref``, D25) e ajusta: todo objeto
    com ``additionalProperties: false`` e todas as chaves em ``required`` (campos opcionais já são
    ``anyOf [tipo, null]``), sem ``default``, títulos, descrições internas nem limites numéricos
    ou de tamanho, que o modo strict não aceita. Os limites continuam valendo na validação
    Pydantic e nos guardrails.
    """
    schema: dict[str, Any] = _strict(LLMInterpretation.tool_input_schema())
    return schema


def _strict(node: Any) -> Any:
    if isinstance(node, list):
        return [_strict(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {k: _strict(v) for k, v in node.items() if k not in _DROPPED_KEYS}
    if out.get("type") == "object" and "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out["properties"])
    return out


class AnthropicClient:
    provider = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        sdk: Any,
        effort: Effort = "medium",
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self._sdk = sdk
        self._tool = {
            "name": TOOL_NAME,
            "description": TOOL_DESCRIPTION,
            "strict": True,
            "input_schema": strict_input_schema(),
        }

    @classmethod
    def from_settings(cls, settings: Settings) -> AnthropicClient:
        """Cria o SDK com a chave de ``ANTHROPIC_API_KEY`` (``.env``). Sem chave nas settings, o
        SDK procura as credenciais sozinho (variável de ambiente ou perfil do ``ant``)."""
        options: dict[str, Any] = {"timeout": float(settings.llm_timeout_seconds)}
        if settings.anthropic_api_key is not None:
            options["api_key"] = settings.anthropic_api_key.get_secret_value()
        return cls(
            model=settings.llm_model,
            effort=settings.llm_effort,
            sdk=anthropic.Anthropic(**options),
        )

    def interpret(self, context: InterpretationContext) -> LLMInterpretation:
        request = self._request(context)
        for _ in range(ATTEMPTS):
            response = self._sdk.beta.messages.create(**request)
            if response.stop_reason == "refusal":
                details = getattr(response, "stop_details", None)
                category = getattr(details, "category", None)
                raise LLMRefusalError(f"o modelo recusou o pedido (categoria: {category})")
            if response.stop_reason == "max_tokens":
                raise LLMResponseError("resposta cortada por max_tokens")
            payload = self._tool_input(response)
            if payload is None:
                continue
            try:
                return LLMInterpretation.model_validate(payload)
            except ValidationError as exc:
                raise LLMResponseError(f"entrada da tool fora do schema: {exc}") from exc
        raise LLMResponseError(f"o modelo não chamou {TOOL_NAME} em {ATTEMPTS} tentativas")

    def _request(self, context: InterpretationContext) -> dict[str, Any]:
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": SYSTEM_PROMPT,
            "tools": [self._tool],
            "tool_choice": {"type": "auto"},
            "output_config": {"effort": self.effort},
            # Recusa por classificador de segurança: a API tenta o modelo de reserva indicado
            # pela própria Anthropic antes de devolver ``refusal`` (D37).
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
            "messages": [{"role": "user", "content": build_user_prompt(context)}],
        }

    @staticmethod
    def _tool_input(response: Any) -> Any:
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == TOOL_NAME:
                return block.input
        return None
