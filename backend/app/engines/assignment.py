"""Assignment Engine: responsável compatível com menor carga (SPEC §8.6, D33).

Função pura: recebe a demanda, a config e as tarefas abertas (lidas do banco por quem chama).
Equipe, capacidade, base de tarefas e níveis de desempate vêm de ``config/``.
"""

from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from app.core.config import AppConfig, TeamMember
from app.schemas.demand import Demand, PriorityLevel

LOCKED_REASON = "Responsável definido pelo gestor; não recalculado."


@dataclass(frozen=True)
class OpenTask:
    """Tarefa aberta (inclui as bloqueadas, D03) usada para calcular a carga."""

    assigned_to: str | None
    priority: PriorityLevel | None


@dataclass(frozen=True)
class MemberLoad:
    employee_id: str
    name: str
    load: float  # fração: 0,5333 = 53%
    open_tasks: int
    high_priority_open: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "employee_id": self.employee_id,
            "name": self.name,
            "load": round(self.load, 4),
            "open_tasks": self.open_tasks,
            "high_priority_open": self.high_priority_open,
        }


@dataclass(frozen=True)
class AssignmentResult:
    """``{employee_id, name, reason, loads}`` (§8.6). ``employee_id`` é None sem candidato."""

    employee_id: str | None
    name: str
    reason: str
    loads: list[MemberLoad] = field(default_factory=list)
    locked: bool = False

    def audit_payload(self) -> dict[str, Any]:
        return {
            "action": "assignment_locked" if self.locked else "assignment_calculated",
            "new_value": {
                "employee_id": self.employee_id,
                "name": self.name,
                "reason": self.reason,
                "loads": [item.as_dict() for item in self.loads],
            },
        }


def compute_assignment(
    demand: Demand, *, config: AppConfig, open_tasks: Sequence[OpenTask]
) -> AssignmentResult:
    approver = config.task_types.approver_default
    if demand.assignment_locked:
        return _locked(demand, config)

    task_type = demand.task_type
    if not task_type:
        return AssignmentResult(
            employee_id=None,
            name=approver,
            reason=f"Demanda sem tipo definido; responsável a definir por {approver}.",
        )

    candidates = [m for m in config.team if task_type in m.skills]
    if not candidates:
        return AssignmentResult(
            employee_id=None,
            name=approver,
            reason=(
                f"Nenhum colaborador tem {task_type} nas habilidades; "
                f"responsável a definir por {approver}."
            ),
        )

    high_levels = set(config.priorities.assignment_tiebreak_levels)
    ranked: list[tuple[Fraction, int, int, MemberLoad]] = []
    for order, member in enumerate(candidates):
        mine = [t for t in open_tasks if t.assigned_to == member.id]
        high = sum(1 for t in mine if t.priority in high_levels)
        load = Fraction(member.open_base + len(mine), member.capacity)
        ranked.append(
            (load, high, order, MemberLoad(member.id, member.name, float(load), len(mine), high))
        )
    # Carga ↑, depois tarefas Alta/Crítica abertas ↑; empate total mantém a ordem de team.json.
    ranked.sort(key=lambda item: item[:3])

    loads = [item[3] for item in ranked]
    chosen = ranked[0]
    return AssignmentResult(
        employee_id=chosen[3].employee_id,
        name=chosen[3].name,
        reason=_reason(ranked, candidates[ranked[0][2]], task_type, high_levels),
        loads=loads,
    )


def _reason(
    ranked: list[tuple[Fraction, int, int, MemberLoad]],
    member: TeamMember,
    task_type: str,
    high_levels: AbstractSet[str],
) -> str:
    load, high, _, chosen = ranked[0]
    text = (
        f"{chosen.name}: carga {_percent(load)} "
        f"({member.open_base + chosen.open_tasks} de {member.capacity})"
    )
    if len(ranked) == 1:
        return f"{text}; único colaborador com {task_type} nas habilidades."
    runner_up = ranked[1]
    if runner_up[0] != load:
        return f"{text}; menor carga entre {len(ranked)} colaboradores com {task_type}."
    levels = "/".join(sorted(high_levels, key=_level_order))
    if runner_up[1] != high:
        return f"{text}; empate na carga, menos tarefas {levels} abertas ({high})."
    return f"{text}; empate na carga e em tarefas {levels}, mantida a ordem da equipe."


def _level_order(level: str) -> int:
    return ["Alta", "Crítica", "Normal", "Baixa"].index(level)


def _percent(load: Fraction) -> str:
    return f"{round(load * 100)}%"


def _locked(demand: Demand, config: AppConfig) -> AssignmentResult:
    employee_id = demand.assigned_to
    if employee_id is None:
        name = config.task_types.approver_default
    else:
        member = next((m for m in config.team if m.id == employee_id), None)
        name = member.name if member else employee_id
    return AssignmentResult(employee_id=employee_id, name=name, reason=LOCKED_REASON, locked=True)
