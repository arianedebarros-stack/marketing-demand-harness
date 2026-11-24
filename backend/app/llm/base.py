"""Interface comum dos clientes de LLM (SPEC §8.1).

O LLM só interpreta: recebe o contexto e devolve uma ``LLMInterpretation`` validada.
Nenhuma decisão é tomada aqui.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from app.core.config import AppConfig
from app.schemas.demand import EXTRACTABLE_FIELDS
from app.schemas.llm import LLMInterpretation

WEEKDAYS_PT = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)


@dataclass(frozen=True)
class InterpretationContext:
    """Entrada do LLM (§8.1). ``messages`` contém só as mensagens do solicitante, em ordem."""

    today: date
    messages: list[str]
    known_fields: Mapping[str, Any]
    asked_fields: list[str]
    allowed_types: list[str]
    brand_names: list[str]
    suppliers: list[str]
    possible_fields: list[str] = field(default_factory=lambda: list(EXTRACTABLE_FIELDS))

    @property
    def weekday(self) -> str:
        return WEEKDAYS_PT[self.today.weekday()]

    @classmethod
    def build(
        cls,
        config: AppConfig,
        *,
        today: date,
        messages: list[str],
        known_fields: Mapping[str, Any],
        asked_fields: list[str],
    ) -> InterpretationContext:
        return cls(
            today=today,
            messages=list(messages),
            known_fields=dict(known_fields),
            asked_fields=list(asked_fields),
            allowed_types=list(config.task_types.types),
            brand_names=[brand.name for brand in config.brands.values()],
            suppliers=list(config.task_types.suppliers),
        )


class LLMClient(Protocol):
    @property
    def provider(self) -> str:
        """Nome do provedor que respondeu (vai para o audit)."""
        ...

    def interpret(self, context: InterpretationContext) -> LLMInterpretation: ...
