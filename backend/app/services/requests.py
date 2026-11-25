"""Casos de uso da API: banco + pipeline + triagem + audit + sistema de tarefas (§9, D36).

Cada operação grava a demanda e o audit numa transação só (D35). Quando a operação é recusada
(transição inválida, duplicidade, falha do sistema de tarefas), o motivo é gravado no audit
antes de o erro subir para a API.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, NoReturn
from zoneinfo import ZoneInfo

from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import AppConfig
from app.core.state_machine import InvalidTransition, transition
from app.core.text import normalize
from app.engines.assignment import OpenTask
from app.engines.briefing import build_briefing, build_title
from app.engines.dedupe import ExistingTask, find_duplicate
from app.engines.dependency import is_blocked, resolve_dependency
from app.engines.validator import validate_demand
from app.integrations.base import TaskManagerConnector
from app.llm.base import LLMClient
from app.llm.fallback import FallbackLLMClient, LLMUnavailableError
from app.models import DependencyRow, Message, RequestRow, Task
from app.schemas.api import (
    AuditEntry,
    ConfirmTypeBody,
    CreateRequestBody,
    DemandPatch,
    DuplicateConflict,
    MessageView,
    NextAction,
    RequestView,
    TaskView,
)
from app.schemas.audit import AuditEvent
from app.schemas.demand import (
    Demand,
    Dependency,
    DuplicateCandidate,
    FieldOrigin,
    RequestStatus,
)
from app.services import audit
from app.services.errors import (
    ConflictError,
    DuplicateTaskError,
    NotFoundError,
    TaskCreationError,
    UnprocessableError,
)
from app.services.pipeline import PipelineResult, process_message, revalidate
from app.services.triage import run_triage

S = RequestStatus
OPEN = "Aberta"
DONE = "Concluída"
EDITABLE_STATES = frozenset({S.NEEDS_INFORMATION, S.PENDING_APPROVAL})


@dataclass
class Context:
    session: Session
    config: AppConfig
    now: datetime
    tz: ZoneInfo
    llm: LLMClient | None = None
    task_manager: TaskManagerConnector | None = None


# --- Leitura ---------------------------------------------------------------------------------


def get_view(ctx: Context, request_id: uuid.UUID) -> RequestView:
    return _view(ctx, _load(ctx, request_id))


def list_messages(ctx: Context, request_id: uuid.UUID) -> list[MessageView]:
    """Histórico do chat, em ordem (D39). Só leitura: não grava audit."""
    if ctx.session.get(RequestRow, request_id) is None:
        raise NotFoundError(f"demanda {request_id} não encontrada")
    rows = ctx.session.scalars(
        select(Message).where(Message.request_id == request_id).order_by(Message.id)
    )
    return [MessageView.model_validate(m, from_attributes=True) for m in rows]


def _view(ctx: Context, row: RequestRow) -> RequestView:
    """Tudo derivado da demanda gravada: o GET devolve o mesmo que a operação que a gravou."""
    demand = row.to_demand()
    validation = validate_demand(demand, config=ctx.config)
    questions = validation.questions if demand.status is S.NEEDS_INFORMATION else []
    return RequestView(
        demand=demand,
        title=build_title(demand, config=ctx.config),
        next_action=_next_action(demand.status, validation.needs_type_confirmation),
        questions=questions,
        score_band=validation.score.band,
        audit=audit.entries_for_request(ctx.session, demand.request_id),
    )


def _next_action(status: RequestStatus, confirm_type: bool) -> NextAction:
    if status in (S.RECEIVED, S.PARSED, S.VALIDATING, S.NEEDS_INFORMATION):
        return "CONFIRM_TYPE" if confirm_type else "REQUEST_INFORMATION"
    if status is S.TASK_CREATED:
        return "DONE"
    if status in (S.CANCELLED, S.REJECTED, S.ERROR):
        return "CANCELLED"
    return "AWAIT_APPROVAL"  # READY_FOR_TRIAGE, TRIAGED, PENDING_APPROVAL, APPROVED (D04)


# --- Conversa --------------------------------------------------------------------------------


def create_request(ctx: Context, body: CreateRequestBody) -> RequestView:
    requester = FieldOrigin.REQUESTER
    demand = Demand(
        requester=body.requester_name,
        department=body.department,
        field_origin={"requester": requester, "department": requester},
    )
    row = RequestRow.from_demand(demand, channel=body.channel, now=ctx.now)
    ctx.session.add(row)
    ctx.session.flush()
    return _converse(ctx, row, body.message)


def add_answer(ctx: Context, request_id: uuid.UUID, message: str) -> RequestView:
    return _converse(ctx, _load(ctx, request_id), message)


def _converse(ctx: Context, row: RequestRow, message: str) -> RequestView:
    assert ctx.llm is not None
    llm = ctx.llm
    history = [*_requester_messages(ctx.session, row.id), message]
    ctx.session.add(Message(request_id=row.id, role="requester", text=message, created_at=ctx.now))

    def run() -> PipelineResult:
        return process_message(
            row.to_demand(), history, llm=llm, config=ctx.config, now=ctx.now, tz=ctx.tz
        )

    try:
        result = _guard(ctx, row, run)
    except LLMUnavailableError:
        ctx.session.rollback()  # §9: 502, nada desta requisição fica gravado
        raise
    extra: list[AuditEvent] = []
    if isinstance(llm, FallbackLLMClient) and llm.last_fallback:
        extra.append(AuditEvent("harness", "llm_fallback", new_value=llm.last_fallback))
    return _finish(ctx, row, result, extra)


def confirm_type(ctx: Context, request_id: uuid.UUID, body: ConfirmTypeBody) -> RequestView:
    row = _load(ctx, request_id)
    task_type = _canonical_type(body.task_type, ctx.config)
    demand = row.to_demand()
    origin = {**demand.field_origin, "task_type": FieldOrigin.REQUESTER}
    confirmed = demand.model_copy(
        update={"task_type": task_type, "type_confirmed": True, "field_origin": origin}
    )
    event = AuditEvent(
        "user",
        "type_confirmed",
        previous_value={"type": demand.task_type},
        new_value={"type": task_type},
    )
    result = _guard(ctx, row, lambda: revalidate(confirmed, config=ctx.config))
    return _finish(ctx, row, result, [], before=[event])


def validate(ctx: Context, request_id: uuid.UUID) -> RequestView:
    row = _load(ctx, request_id)
    result = _guard(ctx, row, lambda: revalidate(row.to_demand(), config=ctx.config))
    return _finish(ctx, row, result, [])


def triage(ctx: Context, request_id: uuid.UUID) -> RequestView:
    row = _load(ctx, request_id)
    result = _guard(ctx, row, lambda: _run_triage(ctx, row.to_demand()))
    audit.record_events(ctx.session, result.events, request_id=row.id, timestamp=ctx.now)
    row.update_demand(result.demand, now=ctx.now)
    ctx.session.commit()
    return _view(ctx, row)


def patch(ctx: Context, request_id: uuid.UUID, body: DemandPatch) -> RequestView:
    """Edição humana (D23): origem ``manager``; prioridade e responsável ficam travados."""
    row = _load(ctx, request_id)
    demand = row.to_demand()
    if demand.status not in EDITABLE_STATES:
        _refuse(ctx, row, InvalidTransition(demand.status, S.VALIDATING))

    provided = body.provided()
    updates: dict[str, Any] = {}
    origin = dict(demand.field_origin)
    for name in type(body).model_fields:
        if name not in provided:
            continue
        value = provided[name]
        if name == "task_type" and value is not None:
            value = _canonical_type(value, ctx.config)
        if name == "assigned_to" and value is not None and value not in _team_ids(ctx.config):
            raise UnprocessableError(f"responsável desconhecido: {value!r}")
        updates[name] = value
        if value is None:
            origin.pop(name, None)
        else:
            origin[name] = FieldOrigin.MANAGER
        if name == "priority":
            updates["priority_locked"] = value is not None
            updates["priority_score"] = None
        if name == "assigned_to":
            updates["assignment_locked"] = value is not None

    edited = Demand.model_validate({**demand.model_dump(), **updates, "field_origin": origin})
    events = [
        AuditEvent(
            "manager",
            "human_edit",
            previous_value={"field": name, "value": to_jsonable_python(getattr(demand, name))},
            new_value={"field": name, "value": to_jsonable_python(getattr(edited, name))},
        )
        for name in type(body).model_fields
        if name in provided
    ]
    result = _guard(ctx, row, lambda: revalidate(edited, config=ctx.config))
    return _finish(ctx, row, result, [], before=events)


# --- Aprovação e encerramento ----------------------------------------------------------------


def approve(ctx: Context, request_id: uuid.UUID, *, force_new: bool) -> RequestView:
    """Dedupe → APPROVED → cria tarefa → TASK_CREATED (§9). APPROVED aceita nova tentativa (D04)."""
    row = _load(ctx, request_id)
    demand = row.to_demand()
    events: list[AuditEvent] = []

    if demand.status is S.PENDING_APPROVAL:
        title = build_title(demand, config=ctx.config)
        dedupe = find_duplicate(
            demand, title=title, tasks=_existing_tasks(ctx.session),
            config=ctx.config, now=ctx.now,
        )  # fmt: skip
        events.append(_payload_event("harness", dedupe.audit_payload()))
        best = dedupe.matches[0] if dedupe.matches else None
        if best and not force_new:
            audit.record_events(ctx.session, events, request_id=row.id, timestamp=ctx.now)
            ctx.session.commit()
            task = ctx.session.get(Task, best.task.id)
            assert task is not None
            raise DuplicateTaskError(
                DuplicateConflict(
                    detail="Já existe tarefa aberta parecida. Use force_new ou link-existing.",
                    duplicate=_candidate(
                        best.task.id, best.task.title, best.criteria, best.jaccard
                    ),
                    task=_task_view(task),
                )
            )
        if best:
            events.append(
                AuditEvent("manager", "duplicate_overridden", new_value={"task_id": best.task.id})
            )
        events.append(AuditEvent("manager", "approved", new_value={"force_new": force_new}))
        demand, event = _move(demand, S.APPROVED)
        events.append(event)
    elif demand.status is not S.APPROVED:
        _refuse(ctx, row, InvalidTransition(demand.status, S.APPROVED))

    task = _create_task(ctx, row, demand, events)
    events.append(
        AuditEvent(
            "harness",
            "task_created",
            new_value={
                "task_id": task.id,
                "external_task_id": task.external_task_id,
                "connector": _connector(ctx).name,
                "blocked": task.blocked,
            },
        )
    )
    demand = demand.model_copy(update={"external_task_id": task.external_task_id})
    demand, event = _move(demand, S.TASK_CREATED)
    events.append(event)
    _record(ctx, row, events, task_id_for={"task_created": task.id})
    row.update_demand(demand, now=ctx.now)
    ctx.session.commit()
    return _view(ctx, row)


def link_existing(ctx: Context, request_id: uuid.UUID, task_id: int) -> RequestView:
    row = _load(ctx, request_id)
    demand = row.to_demand()
    if demand.status is not S.PENDING_APPROVAL:
        _refuse(ctx, row, InvalidTransition(demand.status, S.CANCELLED))
    task = ctx.session.get(Task, task_id)
    if task is None:
        raise NotFoundError(f"tarefa {task_id} não encontrada")
    if task.status != OPEN:
        raise ConflictError(f"a tarefa {task_id} já está concluída")
    linked = AuditEvent(
        "manager",
        "linked_to_existing",
        new_value={"task_id": task.id, "external_task_id": task.external_task_id},
    )
    demand = demand.model_copy(update={"external_task_id": task.external_task_id})
    demand, event = _move(demand, S.CANCELLED)
    _record(ctx, row, [linked, event], task_id_for={"linked_to_existing": task.id})
    row.update_demand(demand, now=ctx.now)
    ctx.session.commit()
    return _view(ctx, row)


def cancel(ctx: Context, request_id: uuid.UUID) -> RequestView:
    return _close(ctx, request_id, S.CANCELLED, AuditEvent("user", "cancelled"))


def reject(ctx: Context, request_id: uuid.UUID) -> RequestView:
    """D02: ``PENDING_APPROVAL → REJECTED``."""
    return _close(ctx, request_id, S.REJECTED, AuditEvent("manager", "rejected"))


def _close(
    ctx: Context, request_id: uuid.UUID, target: RequestStatus, reason: AuditEvent
) -> RequestView:
    row = _load(ctx, request_id)
    demand = row.to_demand()
    moved = _guard(ctx, row, lambda: _move(demand, target))
    _record(ctx, row, [reason, moved[1]])
    row.update_demand(moved[0], now=ctx.now)
    ctx.session.commit()
    return _view(ctx, row)


# --- Registro (§13, tela 5; D40) ------------------------------------------------------------


def list_audit(
    ctx: Context, *, request_id: uuid.UUID | None, before: int | None, limit: int
) -> list[AuditEntry]:
    """Audit log em ordem decrescente. Só leitura: não grava audit."""
    return audit.recent_entries(ctx.session, request_id=request_id, before=before, limit=limit)


# --- Tarefas ---------------------------------------------------------------------------------


def list_tasks(ctx: Context) -> list[TaskView]:
    return [_task_view(t) for t in ctx.session.scalars(select(Task).order_by(Task.id))]


def resolve_task_dependency(ctx: Context, task_id: int, index: int) -> TaskView:
    task = _load_task(ctx, task_id)
    deps = [
        Dependency.model_validate(
            {"dependency": d.description, "owner": d.owner, "status": d.status}
        )
        for d in task.dependencies
    ]
    try:
        resolution = resolve_dependency(deps, index)
    except IndexError as exc:
        raise NotFoundError(str(exc)) from exc
    task.dependencies[index].status = resolution.dependencies[index].status
    task.blocked = resolution.blocked
    audit.record_payload(
        ctx.session, resolution.audit_payload(), actor="user",
        request_id=task.request_id, task_id=task.id, timestamp=ctx.now,
    )  # fmt: skip
    ctx.session.commit()
    return _task_view(task)


def complete_task(ctx: Context, task_id: int) -> TaskView:
    """D13: ``POST /tasks/{id}/complete``."""
    task = _load_task(ctx, task_id)
    if task.status != OPEN:
        raise ConflictError(f"a tarefa {task_id} já está concluída")
    task.status = DONE
    audit.record(
        ctx.session, actor="user", action="task_completed", request_id=task.request_id,
        task_id=task.id, new_value={"status": DONE}, timestamp=ctx.now,
    )  # fmt: skip
    ctx.session.commit()
    return _task_view(task)


# --- Auxiliares ------------------------------------------------------------------------------


def _finish(
    ctx: Context,
    row: RequestRow,
    result: PipelineResult,
    extra: list[AuditEvent],
    *,
    before: Iterable[AuditEvent] = (),
) -> RequestView:
    """Triagem automática se a demanda ficou pronta (D01, D34); grava tudo e responde."""
    events = [*before, *result.events, *extra]
    demand = result.demand
    if demand.status is S.READY_FOR_TRIAGE:
        triaged = _run_triage(ctx, demand)
        events.extend(triaged.events)
        demand = triaged.demand
    _record(ctx, row, events)
    if demand.status is S.NEEDS_INFORMATION and result.questions:
        text = "\n".join(q.text for q in result.questions)
        ctx.session.add(Message(request_id=row.id, role="assistant", text=text, created_at=ctx.now))
    row.update_demand(demand, now=ctx.now)
    ctx.session.commit()
    return _view(ctx, row)


def _run_triage(ctx: Context, demand: Demand) -> Any:
    return run_triage(
        demand,
        open_tasks=_open_tasks(ctx.session),
        existing_tasks=_existing_tasks(ctx.session),
        config=ctx.config,
        now=ctx.now,
        tz=ctx.tz,
    )


def _guard[R](ctx: Context, row: RequestRow, operation: Callable[[], R]) -> R:
    """Transição inválida: desfaz o que a operação mudou, grava no audit e devolve 409."""
    try:
        return operation()
    except InvalidTransition as exc:
        _refuse(ctx, row, exc)


def _refuse(ctx: Context, row: RequestRow, exc: InvalidTransition) -> NoReturn:
    request_id = row.id
    ctx.session.rollback()
    audit.record_payload(
        ctx.session, exc.audit_payload(), actor="harness", request_id=request_id,
        timestamp=ctx.now,
    )  # fmt: skip
    ctx.session.commit()
    raise exc


def _move(demand: Demand, target: RequestStatus) -> tuple[Demand, AuditEvent]:
    new_status = transition(demand.status, target)
    event = AuditEvent(
        "harness",
        "status_transition",
        previous_value={"status": demand.status.value},
        new_value={"status": new_status.value},
    )
    return demand.model_copy(update={"status": new_status}), event


def _record(
    ctx: Context,
    row: RequestRow,
    events: Iterable[AuditEvent],
    *,
    task_id_for: dict[str, int] | None = None,
) -> None:
    links = task_id_for or {}
    for event in events:
        audit.record(
            ctx.session,
            actor=event.actor,
            action=event.action,
            previous_value=event.previous_value,
            new_value=event.new_value,
            request_id=row.id,
            task_id=links.get(event.action),
            timestamp=ctx.now,
        )


def _create_task(ctx: Context, row: RequestRow, demand: Demand, events: list[AuditEvent]) -> Task:
    """Grava a tarefa e chama o conector; se ele falhar, nada da tarefa fica (D04)."""
    title = build_title(demand, config=ctx.config)
    task = Task(
        request_id=demand.request_id,
        title=title,
        type=demand.task_type or "Outro",
        brand=demand.brand,
        supplier=demand.supplier,
        campaign=demand.campaign,
        assigned_to=demand.assigned_to,
        priority=demand.priority,
        deadline=demand.deadline,
        blocked=is_blocked(demand.dependencies),
        status=OPEN,
        briefing=build_briefing(demand, config=ctx.config, title=title),
        briefing_score=demand.briefing_score,
        created_at=ctx.now,
        dependencies=[
            DependencyRow(description=d.dependency, owner=d.owner, status=d.status)
            for d in demand.dependencies
        ],
    )
    connector = _connector(ctx)
    savepoint = ctx.session.begin_nested()
    try:
        ctx.session.add(task)
        ctx.session.flush()
        task.external_task_id = connector.create_task(task)
        ctx.session.flush()
    except Exception as exc:  # noqa: BLE001 — falha do sistema externo (D04)
        savepoint.rollback()
        events.append(
            AuditEvent(
                "harness",
                "task_creation_failed",
                new_value={"connector": connector.name, "error": str(exc)},
            )
        )
        _record(ctx, row, events)
        row.update_demand(demand, now=ctx.now)
        ctx.session.commit()
        raise TaskCreationError(str(exc)) from exc
    savepoint.commit()
    return task


def _connector(ctx: Context) -> TaskManagerConnector:
    assert ctx.task_manager is not None
    return ctx.task_manager


def _load(ctx: Context, request_id: uuid.UUID) -> RequestRow:
    row = ctx.session.get(RequestRow, request_id, with_for_update=True)
    if row is None:
        raise NotFoundError(f"demanda {request_id} não encontrada")
    return row


def _load_task(ctx: Context, task_id: int) -> Task:
    task = ctx.session.get(Task, task_id, with_for_update=True)
    if task is None:
        raise NotFoundError(f"tarefa {task_id} não encontrada")
    return task


def _requester_messages(session: Session, request_id: uuid.UUID) -> list[str]:
    return list(
        session.scalars(
            select(Message.text)
            .where(Message.request_id == request_id, Message.role == "requester")
            .order_by(Message.id)
        )
    )


def _open_tasks(session: Session) -> list[OpenTask]:
    rows = session.execute(select(Task.assigned_to, Task.priority).where(Task.status == OPEN))
    return [OpenTask(assigned_to=assigned, priority=priority) for assigned, priority in rows]


def _existing_tasks(session: Session) -> list[ExistingTask]:
    return [
        ExistingTask(
            id=t.id, title=t.title, brand=t.brand, task_type=t.type, supplier=t.supplier,
            campaign=t.campaign, created_at=t.created_at, is_open=t.status == OPEN,
        )
        for t in session.scalars(select(Task).where(Task.status == OPEN))
    ]  # fmt: skip


def _team_ids(config: AppConfig) -> set[str]:
    return {member.id for member in config.team}


def _canonical_type(value: str, config: AppConfig) -> str:
    target = normalize(value).strip()
    for name in config.task_types.types:
        if normalize(name) == target:
            return name
    raise UnprocessableError(f"tipo desconhecido: {value!r}")


def _candidate(task_id: int, title: str, criteria: Any, jaccard: float) -> DuplicateCandidate:
    return DuplicateCandidate(
        task_id=task_id, title=title, criteria=list(criteria), jaccard=round(jaccard, 4)
    )


def _payload_event(actor: Any, payload: dict[str, Any]) -> AuditEvent:
    return AuditEvent(
        actor,
        payload["action"],
        previous_value=payload.get("previous_value") or {},
        new_value=payload.get("new_value") or {},
    )


def _task_view(task: Task) -> TaskView:
    return TaskView.model_validate(
        {
            "id": task.id,
            "request_id": task.request_id,
            "external_task_id": task.external_task_id,
            "title": task.title,
            "type": task.type,
            "brand": task.brand,
            "supplier": task.supplier,
            "campaign": task.campaign,
            "assigned_to": task.assigned_to,
            "priority": task.priority,
            "deadline": task.deadline,
            "blocked": task.blocked,
            "status": task.status,
            "briefing": task.briefing,
            "briefing_score": task.briefing_score,
            "created_at": task.created_at,
            "dependencies": [
                {"index": i, "description": d.description, "owner": d.owner, "status": d.status}
                for i, d in enumerate(task.dependencies)
            ],
        }
    )
