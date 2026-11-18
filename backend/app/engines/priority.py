"""Priority Engine: pontuação, faixa e regras de elevação (SPEC §8.5, D14, D20, D32).

Função pura: recebe a demanda, a config e o "agora" (com fuso). Todos os números vêm de
``config/priorities.json`` e de ``task_types.json`` (impacto por tipo). O texto do solicitante
não é lido aqui, então "urgente" não altera nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from app.core.config import AppConfig
from app.schemas.demand import Demand, PriorityLevel

FALLBACK_TYPE = "Outro"
LOCKED_REASON = "Prioridade definida pelo gestor; não recalculada."
_RANK: dict[PriorityLevel, int] = {"Baixa": 0, "Normal": 1, "Alta": 2, "Crítica": 3}


@dataclass(frozen=True)
class PriorityResult:
    """``{score, level, factors, reasons[]}`` (§8.5). ``locked`` quando o gestor definiu."""

    score: float | None
    level: PriorityLevel | None
    factors: dict[str, float | None] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    locked: bool = False

    def audit_payload(self) -> dict[str, Any]:
        return {
            "action": "priority_locked" if self.locked else "priority_calculated",
            "new_value": {
                "score": self.score,
                "level": self.level,
                "factors": dict(self.factors),
                "reasons": list(self.reasons),
            },
        }


def compute_priority(
    demand: Demand, *, config: AppConfig, now: datetime, tz: ZoneInfo
) -> PriorityResult:
    if demand.priority_locked:
        return PriorityResult(
            score=demand.priority_score,
            level=demand.priority,
            reasons=[LOCKED_REASON],
            locked=True,
        )

    rules = config.priorities
    local_now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
    hours = _hours_to_deadline(demand.deadline, local_now, rules.deadline_hour, tz)

    urgency, urgency_reason = _urgency(hours, config)
    impact, impact_reason = _impact(demand, config)
    pending = sum(1 for d in demand.dependencies if d.status == "Pendente")
    dependencies = rules.dependency_scores[min(pending, len(rules.dependency_scores) - 1)]
    risk, risk_reason = _risk(demand, config)

    weights = rules.weights
    score = round(
        urgency * weights.urgency
        + impact * weights.impact
        + dependencies * weights.dependencies
        + risk * weights.risk,
        2,
    )
    band: PriorityLevel = next(b.level for b in rules.bands if score >= b.min)

    reasons = [
        f"Urgência {_num(urgency)}: {urgency_reason}",
        f"Impacto {_num(impact)}: {impact_reason}",
        f"Dependências {_num(dependencies)}: {pending} pendente(s)",
        f"Risco {_num(risk)}: {risk_reason}",
        f"Pontuação {_num(score)} → {band}",
    ]
    level = band
    for minimum, reason in _elevations(demand, hours, local_now.date(), config):
        if _RANK[minimum] > _RANK[level]:
            level = minimum
            reasons.append(f"Elevada para {minimum}: {reason}")

    return PriorityResult(
        score=score,
        level=level,
        factors={
            "urgency": urgency,
            "impact": impact,
            "dependencies": dependencies,
            "risk": risk,
            "hours_to_deadline": hours,
        },
        reasons=reasons,
    )


def _hours_to_deadline(
    deadline: date | None, now: datetime, deadline_hour: int, tz: ZoneInfo
) -> float | None:
    """Horas até o prazo às ``deadline_hour`` no fuso da aplicação (negativo se vencido)."""
    if deadline is None:
        return None
    due = datetime.combine(deadline, time(hour=deadline_hour), tzinfo=tz)
    return round((due - now).total_seconds() / 3600, 2)


def _urgency(hours: float | None, config: AppConfig) -> tuple[float, str]:
    rules = config.priorities
    if hours is None:
        return rules.urgency_without_deadline, "sem prazo"
    description = f"prazo vencido há {_num(-hours)} h" if hours < 0 else f"prazo em {_num(hours)} h"
    for index, step in enumerate(rules.urgency_by_hours):
        if step.max_hours is None:
            return step.score, description
        # D32: a primeira faixa é estrita (< 24); as demais incluem o limite (≤ 48, …).
        within = hours < step.max_hours if index == 0 else hours <= step.max_hours
        if within:
            return step.score, description
    raise AssertionError("urgency_by_hours sem faixa final")  # pragma: no cover — loader garante


def _impact(demand: Demand, config: AppConfig) -> tuple[float, str]:
    rules = config.priorities.impact
    types = config.task_types.types
    type_name = demand.task_type if demand.task_type in types else FALLBACK_TYPE
    assert type_name is not None
    base = float(types[type_name].impact)
    if demand.published_error:
        return rules.published_error, "erro em material publicado"
    if demand.is_promotional and base < rules.promotional_min:
        return rules.promotional_min, f"tipo {type_name} ({_num(base)}), promocional"
    return base, f"tipo {type_name}"


def _risk(demand: Demand, config: AppConfig) -> tuple[float, str]:
    rules = config.priorities.risk
    if demand.published_error:
        return rules.published_error, "erro em material publicado"
    if demand.is_promotional and _filled(demand.price):
        return rules.promotional_with_price, "promocional com preço"
    if _filled(demand.supplier):  # D32: qualquer demanda com fornecedor
        return rules.with_supplier, "com fornecedor"
    return rules.default, "padrão"


def _elevations(
    demand: Demand, hours: float | None, today: date, config: AppConfig
) -> list[tuple[PriorityLevel, str]]:
    """Regras que elevam a faixa (nunca rebaixam), da mais forte para a mais fraca."""
    rules = config.priorities.elevation
    found: list[tuple[PriorityLevel, str]] = []
    if demand.published_error:
        found.append(("Crítica", "erro em material publicado"))
    if hours is not None and hours < rules.critical_under_hours:
        found.append(("Crítica", f"prazo em menos de {_num(rules.critical_under_hours)} h"))
    if demand.event_date is not None and demand.event_date == today:
        found.append(("Crítica", "evento hoje"))
    if hours is not None and hours <= rules.high_max_hours:
        found.append(("Alta", f"prazo em até {_num(rules.high_max_hours)} h"))
    return found


def _filled(value: str | None) -> bool:
    return bool(value and value.strip())


def _num(value: float) -> str:
    """76.5 → '76,5'; 90.0 → '90' (texto em pt-BR)."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")
