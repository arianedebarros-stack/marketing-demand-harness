"""Validator: obrigatórios, faltantes e perguntas ao solicitante (SPEC §8.4, §7, D29).

Função pura: recebe a demanda (já com as regras aplicadas) e a config; devolve o que falta, as
perguntas e o Briefing Score. Quem grava o resultado na demanda e muda o estado é o pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import AppConfig
from app.engines.score import BriefingScore, compute_briefing_score
from app.schemas.api import Question
from app.schemas.demand import Demand, FieldOrigin

TYPE_FIELD = "task_type"

# Textos das perguntas (§8.4). A ordem do dicionário é a ordem em que as perguntas são feitas.
# Chaves com mais de um campo são perguntas agrupadas; quando só parte do grupo falta, usa-se a
# chave com os campos que faltam.
QUESTIONS: dict[tuple[str, ...], str] = {
    (TYPE_FIELD,): "Qual é o tipo da demanda (arte, vídeo, e-mail, evento…)?",
    ("requester",): "Quem está solicitando a demanda?",
    ("brand",): "Para qual marca é a demanda?",
    ("objective",): "Qual é o objetivo da peça?",
    ("audience",): "Qual é o público-alvo?",
    ("message_tone",): "Qual tom a mensagem deve ter?",
    ("channel", "format"): "Em qual canal e formato a peça será publicada (ex.: Instagram Feed)?",
    ("channel",): "Em qual canal a peça será publicada?",
    ("format",): "Qual é o formato da peça (ex.: Feed, Stories, Reels)?",
    ("dimensions",): "Quais são as dimensões da peça (ex.: 1080 × 1350 px)?",
    ("headline",): "Qual é o título (headline)?",
    ("landing_page",): "Para qual landing page a peça deve levar?",
    ("link",): "Qual é o link?",
    ("publish_period",): "Em qual período a peça deve ficar publicada?",
    ("product", "price"): (
        "Quais produtos e preços devem aparecer? Se estiverem em uma planilha, pode anexá-la."
    ),
    ("product",): "Quais produtos devem aparecer?",
    ("price",): "Quais são os preços? Se estiverem em uma planilha, pode anexá-la.",
    ("validity",): "Até quando vale a promoção?",
    ("duration",): "Qual deve ser a duração do vídeo?",
    ("concept",): "Qual é o conceito ou roteiro?",
    ("location",): "Qual é o local?",
    ("participants",): "Quem vai participar da gravação?",
    ("shoot_date",): "Qual é a data da gravação ou da sessão de fotos?",
    ("event_name",): "Qual é o nome do evento?",
    ("event_date",): "Qual é a data do evento?",
    ("event_time",): "Qual é o horário do evento?",
    ("participants_count",): "Quantas pessoas devem participar?",
    ("budget",): "Qual é o orçamento disponível?",
    ("deliverables",): "Quais são as entregas esperadas?",
    ("size",): "Qual é o tamanho do material?",
    ("quantity",): "Quantas unidades devem ser produzidas?",
    ("material",): "Qual material deve ser usado?",
    ("finishing",): "Qual acabamento deve ser usado?",
    ("deadline",): "Para quando você precisa da entrega?",
}

# Campos que vêm da marca: não são perguntados enquanto a marca falta (§8.4).
_FROM_BRAND = frozenset({"audience", "message_tone"})
_GROUPS: dict[str, tuple[str, ...]] = {
    field: key for key in QUESTIONS if len(key) > 1 for field in key
}
_ORDER: dict[str, int] = {}
for _key in QUESTIONS:
    for _field in _key:
        _ORDER.setdefault(_field, len(_ORDER))


@dataclass(frozen=True)
class ValidationResult:
    required: list[str]
    missing: list[str]
    questions: list[Question]
    score: BriefingScore
    needs_type_confirmation: bool

    @property
    def ready(self) -> bool:
        """Só avança para ``READY_FOR_TRIAGE`` com 100% (§8.4)."""
        return not self.needs_type_confirmation and self.score.filled == self.score.total


def validate_demand(demand: Demand, *, config: AppConfig) -> ValidationResult:
    task_types = config.task_types
    universal = _unique(task_types.universal_required)

    if _type_uncertain(demand, config):
        # D29: só confirmar o tipo; os campos do tipo são cobrados depois da confirmação.
        required = [*universal, TYPE_FIELD]
        filled = sum(1 for field in universal if _is_filled(getattr(demand, field)))
        return ValidationResult(
            required=required,
            missing=[TYPE_FIELD],
            questions=[_question((TYPE_FIELD,))],
            score=compute_briefing_score(filled, len(required), config=config),
            needs_type_confirmation=True,
        )

    assert demand.task_type is not None  # garantido por _type_uncertain
    rule = task_types.types[demand.task_type]
    promo = rule.promo_required if demand.is_promotional else []
    required = _unique([*universal, *rule.required, *promo])
    missing = [field for field in required if not _is_filled(getattr(demand, field))]

    return ValidationResult(
        required=required,
        missing=missing,
        questions=_questions(missing),
        score=compute_briefing_score(len(required) - len(missing), len(required), config=config),
        needs_type_confirmation=False,
    )


def _type_uncertain(demand: Demand, config: AppConfig) -> bool:
    """Tipo vazio, fora da config ou com confiança baixa sem confirmação (§7)."""
    if not demand.task_type or demand.task_type not in config.task_types.types:
        return True
    if demand.type_confirmed or demand.field_origin.get(TYPE_FIELD) is FieldOrigin.MANAGER:
        return False
    return demand.classification_confidence < config.task_types.classification_threshold


def _questions(missing: list[str]) -> list[Question]:
    missing_set = set(missing)
    asked: set[str] = set()
    questions: list[Question] = []
    for field in sorted(missing, key=lambda f: _ORDER.get(f, len(_ORDER))):
        if field in asked or (field in _FROM_BRAND and "brand" in missing_set):
            continue
        group = _GROUPS.get(field, (field,))
        key = tuple(f for f in group if f in missing_set)
        questions.append(_question(key))
        asked.update(key)
    return questions


def _question(key: tuple[str, ...]) -> Question:
    return Question(fields=list(key), text=QUESTIONS[key])


def _is_filled(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _unique(fields: list[str]) -> list[str]:
    return list(dict.fromkeys(fields))
