"""Rotas da §9 (mais ``reject``, D02, e ``complete``, D13)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import AppConfig
from app.integrations.base import TaskManagerConnector
from app.llm.base import LLMClient
from app.schemas.api import (
    ApproveBody,
    AuditEntry,
    ConfirmTypeBody,
    CreateRequestBody,
    DemandPatch,
    LinkExistingBody,
    MessageBody,
    MessageView,
    RequestView,
    TaskView,
)
from app.services import requests as service
from app.services.requests import Context

router = APIRouter()

AUDIT_DEFAULT_LIMIT = 200
AUDIT_MAX_LIMIT = 1000


def _context(
    session: Annotated[Session, Depends(deps.get_session)],
    config: Annotated[AppConfig, Depends(deps.get_config)],
    now: Annotated[datetime, Depends(deps.get_now)],
    tz: Annotated[ZoneInfo, Depends(deps.get_tz)],
) -> Context:
    return Context(session=session, config=config, now=now, tz=tz)


def _with_llm(
    ctx: Annotated[Context, Depends(_context)],
    llm: Annotated[LLMClient, Depends(deps.get_llm)],
) -> Context:
    ctx.llm = llm
    return ctx


def _with_task_manager(
    ctx: Annotated[Context, Depends(_context)],
    task_manager: Annotated[TaskManagerConnector, Depends(deps.get_task_manager)],
) -> Context:
    ctx.task_manager = task_manager
    return ctx


Ctx = Annotated[Context, Depends(_context)]
LLMCtx = Annotated[Context, Depends(_with_llm)]
TaskCtx = Annotated[Context, Depends(_with_task_manager)]


@router.post("/requests", status_code=status.HTTP_201_CREATED)
def create_request(body: CreateRequestBody, ctx: LLMCtx) -> RequestView:
    return service.create_request(ctx, body)


@router.get("/requests/{request_id}")
def get_request(request_id: uuid.UUID, ctx: Ctx) -> RequestView:
    return service.get_view(ctx, request_id)


@router.get("/requests/{request_id}/messages")
def list_messages(request_id: uuid.UUID, ctx: Ctx) -> list[MessageView]:
    """Histórico do chat para o frontend (D39)."""
    return service.list_messages(ctx, request_id)


@router.post("/requests/{request_id}/answers")
def add_answer(request_id: uuid.UUID, body: MessageBody, ctx: LLMCtx) -> RequestView:
    return service.add_answer(ctx, request_id, body.message)


@router.post("/requests/{request_id}/confirm-type")
def confirm_type(request_id: uuid.UUID, body: ConfirmTypeBody, ctx: Ctx) -> RequestView:
    return service.confirm_type(ctx, request_id, body)


@router.post("/requests/{request_id}/validate")
def validate(request_id: uuid.UUID, ctx: Ctx) -> RequestView:
    return service.validate(ctx, request_id)


@router.post("/requests/{request_id}/triage")
def triage(request_id: uuid.UUID, ctx: Ctx) -> RequestView:
    return service.triage(ctx, request_id)


@router.patch("/requests/{request_id}")
def patch_request(request_id: uuid.UUID, body: DemandPatch, ctx: Ctx) -> RequestView:
    return service.patch(ctx, request_id, body)


@router.post("/requests/{request_id}/approve")
def approve(request_id: uuid.UUID, body: ApproveBody, ctx: TaskCtx) -> RequestView:
    return service.approve(ctx, request_id, force_new=body.force_new)


@router.post("/requests/{request_id}/link-existing")
def link_existing(request_id: uuid.UUID, body: LinkExistingBody, ctx: Ctx) -> RequestView:
    return service.link_existing(ctx, request_id, body.task_id)


@router.post("/requests/{request_id}/cancel")
def cancel(request_id: uuid.UUID, ctx: Ctx) -> RequestView:
    return service.cancel(ctx, request_id)


@router.post("/requests/{request_id}/reject")
def reject(request_id: uuid.UUID, ctx: Ctx) -> RequestView:
    return service.reject(ctx, request_id)


@router.get("/audit")
def list_audit(
    ctx: Ctx,
    request_id: uuid.UUID | None = None,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=AUDIT_MAX_LIMIT)] = AUDIT_DEFAULT_LIMIT,
) -> list[AuditEntry]:
    """Registro (§13, tela 5; D40): audit log em ordem decrescente, só leitura."""
    return service.list_audit(ctx, request_id=request_id, before=before, limit=limit)


@router.get("/tasks")
def list_tasks(ctx: Ctx) -> list[TaskView]:
    return service.list_tasks(ctx)


@router.post("/tasks/{task_id}/dependencies/{index}/resolve")
def resolve_dependency(task_id: int, index: int, ctx: Ctx) -> TaskView:
    return service.resolve_task_dependency(ctx, task_id, index)


@router.post("/tasks/{task_id}/complete")
def complete_task(task_id: int, ctx: Ctx) -> TaskView:
    return service.complete_task(ctx, task_id)


@router.get("/config")
def get_config(config: Annotated[AppConfig, Depends(deps.get_config)]) -> dict[str, Any]:
    """Config atual, somente leitura (§9, §14: o agente não altera config)."""
    data: dict[str, Any] = config.model_dump(mode="json")
    return data
