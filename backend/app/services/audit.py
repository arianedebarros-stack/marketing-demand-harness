"""Gravação e leitura do ``audit_log`` (SPEC §15, D35).

Engines e pipeline produzem eventos (``AuditEvent`` ou ``audit_payload()``); este serviço só os
grava. O horário vem de quem chama (testes passam ``now``), sempre com fuso.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, get_args

from pydantic_core import to_jsonable_python
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog
from app.schemas.api import AuditActor, AuditEntry
from app.schemas.audit import AuditEvent

_ACTORS = frozenset(get_args(AuditActor))


def record(
    session: Session,
    *,
    actor: AuditActor,
    action: str,
    timestamp: datetime,
    previous_value: Mapping[str, Any] | None = None,
    new_value: Mapping[str, Any] | None = None,
    request_id: uuid.UUID | None = None,
    task_id: int | None = None,
) -> AuditLog:
    """Acrescenta uma linha ao audit log (não faz commit)."""
    if actor not in _ACTORS:
        raise ValueError(f"ator desconhecido no audit: {actor!r}")
    if timestamp.tzinfo is None:
        raise ValueError("timestamp do audit precisa ter fuso horário")
    row = AuditLog(
        request_id=request_id,
        task_id=task_id,
        actor=actor,
        action=action,
        previous_value=_json(previous_value),
        new_value=_json(new_value),
        timestamp=timestamp,
    )
    session.add(row)
    session.flush()
    return row


def record_events(
    session: Session,
    events: Iterable[AuditEvent],
    *,
    timestamp: datetime,
    request_id: uuid.UUID | None = None,
    task_id: int | None = None,
) -> list[AuditLog]:
    """Grava, em ordem, os eventos devolvidos pelo pipeline."""
    return [
        record(
            session,
            actor=event.actor,
            action=event.action,
            previous_value=event.previous_value,
            new_value=event.new_value,
            timestamp=timestamp,
            request_id=request_id,
            task_id=task_id,
        )
        for event in events
    ]


def record_payload(
    session: Session,
    payload: Mapping[str, Any],
    *,
    actor: AuditActor,
    timestamp: datetime,
    request_id: uuid.UUID | None = None,
    task_id: int | None = None,
) -> AuditLog:
    """Grava o ``audit_payload()`` de um engine (``{action, previous_value?, new_value?}``)."""
    return record(
        session,
        actor=actor,
        action=payload["action"],
        previous_value=payload.get("previous_value"),
        new_value=payload.get("new_value"),
        timestamp=timestamp,
        request_id=request_id,
        task_id=task_id,
    )


def entries_for_request(session: Session, request_id: uuid.UUID) -> list[AuditEntry]:
    rows = session.scalars(
        select(AuditLog).where(AuditLog.request_id == request_id).order_by(AuditLog.id)
    )
    return [_entry(row) for row in rows]


def entries_for_task(session: Session, task_id: int) -> list[AuditEntry]:
    rows = session.scalars(
        select(AuditLog).where(AuditLog.task_id == task_id).order_by(AuditLog.id)
    )
    return [_entry(row) for row in rows]


def recent_entries(
    session: Session,
    *,
    request_id: uuid.UUID | None = None,
    before: int | None = None,
    limit: int,
) -> list[AuditEntry]:
    """Linhas mais recentes primeiro; ``before`` é o cursor (só ids menores que ele)."""
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if request_id is not None:
        query = query.where(AuditLog.request_id == request_id)
    if before is not None:
        query = query.where(AuditLog.id < before)
    return [_entry(row) for row in session.scalars(query)]


def _json(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Valores em forma JSON (datas, UUIDs…); payload vazio vira NULL."""
    if not value:
        return None
    converted: dict[str, Any] = to_jsonable_python(dict(value))
    return converted


def _entry(row: AuditLog) -> AuditEntry:
    return AuditEntry.model_validate(
        {
            "id": row.id,
            "request_id": row.request_id,
            "task_id": row.task_id,
            "actor": row.actor,
            "action": row.action,
            "previous_value": row.previous_value,
            "new_value": row.new_value,
            "timestamp": row.timestamp,
        }
    )
