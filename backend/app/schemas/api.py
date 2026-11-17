"""Corpos e respostas da API (SPEC §9)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

from app.schemas.demand import ContentFields, Demand, PriorityLevel

NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

NextAction = Literal["REQUEST_INFORMATION", "CONFIRM_TYPE", "AWAIT_APPROVAL", "DONE", "CANCELLED"]
ScoreBand = Literal["Incompleto", "Parcial", "Quase pronto", "Pronto para produção"]
AuditActor = Literal["llm", "harness", "user", "manager"]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Respostas ---------------------------------------------------------------------------------


class Question(_Body):
    """Uma pergunta ao solicitante; pode agrupar campos (ex.: channel + format, §8.4)."""

    fields: list[str] = Field(min_length=1)
    text: NonBlankStr


class AuditEntry(BaseModel):
    id: int
    request_id: UUID | None
    task_id: int | None
    actor: AuditActor
    action: str
    previous_value: JsonValue = None
    new_value: JsonValue = None
    timestamp: datetime


class RequestView(BaseModel):
    demand: Demand
    next_action: NextAction
    questions: list[Question] = Field(default_factory=list)
    score_band: ScoreBand
    audit: list[AuditEntry] = Field(default_factory=list)


# --- Corpos das requisições ----------------------------------------------------------------------


class CreateRequestBody(_Body):
    requester_name: NonBlankStr
    department: NonBlankStr
    channel: NonBlankStr
    message: NonBlankStr


class MessageBody(_Body):
    message: NonBlankStr


class ConfirmTypeBody(_Body):
    task_type: NonBlankStr


class ApproveBody(_Body):
    force_new: bool = False


class LinkExistingBody(_Body):
    task_id: int


class DemandPatch(ContentFields):
    """Edição humana (PATCH /requests/{id}): campos de conteúdo + decisões do gestor (D23).

    Estado, scores, travas, origens e ids não são editáveis.
    """

    task_type: str | None = None
    priority: PriorityLevel | None = None
    assigned_to: str | None = None
    approver: str | None = None

    def provided(self) -> dict[str, Any]:
        """Somente os campos enviados no corpo (permite limpar um campo enviando null)."""
        return {name: getattr(self, name) for name in self.model_fields_set}
