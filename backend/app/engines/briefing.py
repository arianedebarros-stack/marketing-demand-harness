"""Título da tarefa e briefing final em texto (SPEC §8.9, D15, D30).

Funções puras: recebem a demanda e a config e devolvem texto. Campos vazios não aparecem.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.config import AppConfig
from app.schemas.demand import Demand

TITLE_SEPARATOR = " | "

# Lista da §8.9, na ordem do template. Os campos próprios do tipo entram depois do CTA (D30).
_MAIN_BEFORE_TYPE: tuple[tuple[str, str], ...] = (
    ("objective", "OBJETIVO"),
    ("brand", "MARCA"),
    ("audience", "PÚBLICO"),
    ("channel", "CANAL"),
    ("format", "FORMATO"),
    ("dimensions", "DIMENSÃO"),
    ("message_tone", "MENSAGEM E TOM"),
    ("product", "PRODUTOS"),
    ("price", "PREÇOS"),
    ("validity", "VIGÊNCIA"),
    ("cta", "CTA"),
)
_MAIN_AFTER_TYPE: tuple[tuple[str, str], ...] = (
    ("deadline", "PRAZO"),
    ("priority", "PRIORIDADE"),
    ("assigned_to", "RESPONSÁVEL"),
    ("approver", "APROVAÇÃO"),
    ("dependencies", "DEPENDÊNCIAS"),
    ("required_files", "ARQUIVOS"),
)
_MAIN_FIELDS = frozenset(name for name, _ in (*_MAIN_BEFORE_TYPE, *_MAIN_AFTER_TYPE))

# Rótulos dos campos próprios de cada tipo (obrigatórios em task_types.json fora da lista acima).
TYPE_FIELD_LABELS: dict[str, str] = {
    "duration": "DURAÇÃO",
    "concept": "CONCEITO",
    "location": "LOCAL",
    "participants": "PARTICIPANTES",
    "shoot_date": "DATA DA GRAVAÇÃO",
    "headline": "HEADLINE",
    "landing_page": "LANDING PAGE",
    "link": "LINK",
    "publish_period": "PERÍODO DE PUBLICAÇÃO",
    "size": "TAMANHO",
    "quantity": "QUANTIDADE",
    "material": "MATERIAL",
    "finishing": "ACABAMENTO",
    "event_name": "NOME DO EVENTO",
    "event_date": "DATA DO EVENTO",
    "event_time": "HORÁRIO DO EVENTO",
    "participants_count": "NÚMERO DE PARTICIPANTES",
    "budget": "ORÇAMENTO",
    "deliverables": "ENTREGAS",
}


def build_title(demand: Demand, *, config: AppConfig) -> str:
    """``[TIPO] | [CAMPANHA ou "Promoção <fornecedor>" ou objetivo curto] | [MARCA]``."""
    parts = [_text(demand.task_type), _title_middle(demand, config), _text(demand.brand)]
    return TITLE_SEPARATOR.join(part for part in parts if part)


def build_briefing(demand: Demand, *, config: AppConfig, title: str | None = None) -> str:
    """Uma linha ``RÓTULO: valor`` por campo preenchido, na ordem da §8.9 (D15, D30)."""
    lines: list[tuple[str, str | None]] = [
        ("TÍTULO", title if title is not None else build_title(demand, config=config))
    ]
    for name, label in _MAIN_BEFORE_TYPE:
        lines.append((label, _format(name, getattr(demand, name), config)))
    for name in _type_fields(demand, config):
        lines.append((TYPE_FIELD_LABELS[name], _format(name, getattr(demand, name), config)))
    for name, label in _MAIN_AFTER_TYPE:
        lines.append((label, _format(name, getattr(demand, name), config)))
    lines.append(("BRIEFING SCORE", f"{demand.briefing_score}%"))
    return "\n".join(f"{label}: {value}" for label, value in lines if value)


def _title_middle(demand: Demand, config: AppConfig) -> str | None:
    campaign = _text(demand.campaign)
    if campaign:
        return campaign
    supplier = _text(demand.supplier)
    if demand.is_promotional and supplier:
        return config.task_types.title.promo_template.format(supplier=supplier)
    objective = _text(demand.objective)
    if objective:
        return " ".join(objective.split()[: config.task_types.title.objective_max_words])
    return None


def _type_fields(demand: Demand, config: AppConfig) -> list[str]:
    """Obrigatórios do tipo que não estão na lista principal, na ordem de ``task_types.json``."""
    rule = config.task_types.types.get(demand.task_type or "")
    if rule is None:
        return []
    names = [*rule.required, *(rule.promo_required if demand.is_promotional else [])]
    return [n for n in dict.fromkeys(names) if n not in _MAIN_FIELDS and n in TYPE_FIELD_LABELS]


def _format(name: str, value: Any, config: AppConfig) -> str | None:
    if value is None:
        return None
    if name == "assigned_to":
        member = next((m for m in config.team if m.id == value), None)
        return member.name if member else _text(value)
    if name == "dependencies":
        items = [f"{d.dependency} ({d.owner}, {d.status})" for d in value]
        return "; ".join(items) or None
    if name == "required_files":
        return "; ".join(f.name for f in value) or None
    if isinstance(value, date):
        return _br_date(value)
    if name == "validity":
        return _br_date_or_text(value)
    return _text(value)


def _br_date(value: date) -> str:
    return value.strftime("%d/%m/%Y")


def _br_date_or_text(value: str) -> str | None:
    """Vigência em ISO vira dd/mm/aaaa; texto livre ("enquanto durar o estoque") fica como está."""
    try:
        return _br_date(date.fromisoformat(value.strip()))
    except ValueError:
        return _text(value)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
