"""Triagem automática: prioridade, responsável, dependências e duplicidade (D01, D34, D36).

Sem banco: quem chama passa as tarefas abertas (para a carga) e as existentes (para a
duplicidade). Em ``READY_FOR_TRIAGE`` a demanda segue para ``TRIAGED`` e ``PENDING_APPROVAL``;
em ``PENDING_APPROVAL`` (``POST /triage``) os valores são recalculados sem mudar o estado.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic_core import to_jsonable_python

from app.core.config import AppConfig
from app.core.state_machine import InvalidTransition, transition
from app.engines.assignment import OpenTask, compute_assignment
from app.engines.briefing import build_title
from app.engines.dedupe import ExistingTask, find_duplicate
from app.engines.dependency import is_blocked, pending_dependencies
from app.engines.priority import compute_priority
from app.schemas.api import NextAction
from app.schemas.audit import AuditEvent
from app.schemas.demand import Demand, DuplicateCandidate, FieldOrigin, RequestStatus

S = RequestStatus
HARNESS = FieldOrigin.HARNESS


class TriageNotReadyError(Exception):
    """A triagem exige Briefing Score de 100% (§9)."""


@dataclass(frozen=True)
class TriageResult:
    demand: Demand
    events: list[AuditEvent]
    next_action: NextAction = "AWAIT_APPROVAL"


def run_triage(
    demand: Demand,
    *,
    open_tasks: Sequence[OpenTask],
    existing_tasks: Sequence[ExistingTask],
    config: AppConfig,
    now: datetime,
    tz: ZoneInfo,
) -> TriageResult:
    if demand.briefing_score < 100:
        raise TriageNotReadyError(
            f"Briefing Score em {demand.briefing_score}%; a triagem exige 100%."
        )

    if demand.status not in (S.READY_FOR_TRIAGE, S.PENDING_APPROVAL):
        raise InvalidTransition(demand.status, S.TRIAGED)

    events: list[AuditEvent] = []
    moving = demand.status is S.READY_FOR_TRIAGE
    if moving:
        events.append(_transition_event(demand.status, transition(demand.status, S.TRIAGED)))

    priority = compute_priority(demand, config=config, now=now, tz=tz)
    events.append(_payload_event(priority.audit_payload()))
    assignment = compute_assignment(demand, config=config, open_tasks=open_tasks)
    events.append(_payload_event(assignment.audit_payload()))
    events.append(
        AuditEvent(
            "harness",
            "dependencies_checked",
            new_value={
                "pending": len(pending_dependencies(demand.dependencies)),
                "blocked": is_blocked(demand.dependencies),
            },
        )
    )
    title = build_title(demand, config=config)
    dedupe = find_duplicate(demand, title=title, tasks=existing_tasks, config=config, now=now)
    events.append(_payload_event(dedupe.audit_payload()))

    updates: dict[str, Any] = {}
    origin = dict(demand.field_origin)
    if not priority.locked:
        updates["priority"] = priority.level
        updates["priority_score"] = priority.score
        origin["priority"] = HARNESS
    if not assignment.locked:
        updates["assigned_to"] = assignment.employee_id
        if assignment.employee_id is None:
            origin.pop("assigned_to", None)  # D33: responsável a definir
        else:
            origin["assigned_to"] = HARNESS
    if demand.approver is None:
        updates["approver"] = config.task_types.approver_default
        origin["approver"] = HARNESS
    best = dedupe.matches[0] if dedupe.matches else None
    updates["duplicate_of"] = (
        DuplicateCandidate(
            task_id=best.task.id,
            title=best.task.title,
            criteria=list(best.criteria),
            jaccard=round(best.jaccard, 4),
        )
        if best
        else None
    )

    triaged = demand.model_copy(update={**updates, "field_origin": origin})
    for name in ("priority", "assigned_to", "approver", "duplicate_of"):
        before, after = getattr(demand, name), getattr(triaged, name)
        if before != after or demand.field_origin.get(name) != origin.get(name):
            events.append(
                AuditEvent(
                    "harness",
                    "field_registered",
                    previous_value={"field": name, "value": to_jsonable_python(before)},
                    new_value={"field": name, "value": to_jsonable_python(after)},
                )
            )

    if moving:
        target = transition(S.TRIAGED, S.PENDING_APPROVAL)
        events.append(_transition_event(S.TRIAGED, target))
        triaged = triaged.model_copy(update={"status": target})
    return TriageResult(demand=triaged, events=events)


def _transition_event(before: RequestStatus, after: RequestStatus) -> AuditEvent:
    return AuditEvent(
        "harness",
        "status_transition",
        previous_value={"status": before.value},
        new_value={"status": after.value},
    )


def _payload_event(payload: dict[str, Any]) -> AuditEvent:
    return AuditEvent(
        "harness",
        payload["action"],
        previous_value=payload.get("previous_value") or {},
        new_value=payload.get("new_value") or {},
    )
