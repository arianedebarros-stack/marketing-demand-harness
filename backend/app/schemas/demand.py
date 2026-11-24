"""Modelo da demanda (SPEC §6)."""

from __future__ import annotations

import re
from datetime import date
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RequestStatus(StrEnum):
    """Estados da demanda (§7). BLOCKED é flag da tarefa, não estado (D03)."""

    RECEIVED = "RECEIVED"
    PARSED = "PARSED"
    VALIDATING = "VALIDATING"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    READY_FOR_TRIAGE = "READY_FOR_TRIAGE"
    TRIAGED = "TRIAGED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    TASK_CREATED = "TASK_CREATED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


class FieldOrigin(StrEnum):
    """De onde veio o valor de um campo (§6, D07)."""

    MESSAGE = "message"
    LLM = "llm"
    RULE = "rule"
    HARNESS = "harness"
    MANAGER = "manager"
    REQUESTER = "requester"


PriorityLevel = Literal["Crítica", "Alta", "Normal", "Baixa"]
DependencyStatus = Literal["Pendente", "Resolvida"]

_DIMENSIONS_RE = re.compile(r"^\s*(\d{3,4})\s*[x×X]\s*(\d{3,4})\s*(?:px)?\s*$")


def normalize_dimensions(value: str) -> str:
    """'1080x1350' → '1080 × 1350 px' (D09). Valores em outro formato ficam como estão."""
    match = _DIMENSIONS_RE.match(value)
    if not match:
        return value
    return f"{match.group(1)} × {match.group(2)} px"


class Dependency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dependency: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    status: DependencyStatus = "Pendente"


DuplicateCriterion = Literal[
    "same_brand_type_supplier", "same_brand_type_campaign", "similar_title"
]


class DuplicateCandidate(BaseModel):
    """Tarefa aberta parecida encontrada na triagem (§8.8, D35): vai no 409 do approve."""

    model_config = ConfigDict(extra="forbid")

    task_id: int
    title: str = Field(min_length=1)
    criteria: list[DuplicateCriterion] = Field(min_length=1)
    jaccard: float = Field(ge=0, le=1)


class RequiredFile(BaseModel):
    """Arquivo obrigatório com a origem do item (D28): itens de regra são recalculados."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    origin: FieldOrigin


class ContentFields(BaseModel):
    """Campos de conteúdo do briefing: os que podem vir da mensagem (via LLM) ou do gestor."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    company: str | None = None
    brand: str | None = None
    campaign: str | None = None
    supplier: str | None = None
    objective: str | None = None
    audience: str | None = None
    message_tone: str | None = None
    channel: str | None = None
    format: str | None = None
    dimensions: str | None = None
    product: str | None = None
    price: str | None = None
    validity: str | None = None
    cta: str | None = None
    deadline: date | None = None
    duration: str | None = None
    concept: str | None = None
    location: str | None = None
    participants: str | None = None
    shoot_date: date | None = None
    headline: str | None = None
    landing_page: str | None = None
    link: str | None = None
    publish_period: str | None = None
    size: str | None = None
    quantity: str | None = None
    material: str | None = None
    finishing: str | None = None
    event_name: str | None = None
    event_date: date | None = None
    event_time: str | None = None
    participants_count: str | None = None
    budget: str | None = None
    deliverables: str | None = None

    @field_validator("dimensions")
    @classmethod
    def _normalize_dimensions(cls, value: str | None) -> str | None:
        return None if value is None else normalize_dimensions(value)


EXTRACTABLE_FIELDS: tuple[str, ...] = tuple(ContentFields.model_fields)
DATE_FIELDS: frozenset[str] = frozenset(
    name for name, info in ContentFields.model_fields.items() if info.annotation == date | None
)


class Demand(ContentFields):
    request_id: UUID = Field(default_factory=uuid4)
    requester: str
    department: str
    task_type: str | None = None

    priority: PriorityLevel | None = None
    priority_score: float | None = Field(default=None, ge=0, le=100)
    priority_locked: bool = False
    assigned_to: str | None = None
    assignment_locked: bool = False
    approver: str | None = None

    dependencies: list[Dependency] = Field(default_factory=list)
    required_files: list[RequiredFile] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    is_promotional: bool = False
    published_error: bool = False  # D24: necessário para recalcular prioridade (§8.5)
    briefing_score: int = Field(default=0, ge=0, le=100)
    classification_confidence: float = Field(default=0.0, ge=0, le=1)
    type_confirmed: bool = False
    status: RequestStatus = RequestStatus.RECEIVED
    field_origin: dict[str, FieldOrigin] = Field(default_factory=dict)
    external_task_id: str | None = None
    # D35: duplicidade encontrada na triagem; a demanda vive em requests.demand (JSONB),
    # então este campo não exige migração.
    duplicate_of: DuplicateCandidate | None = None

    @field_validator("field_origin")
    @classmethod
    def _origin_keys_are_fields(cls, value: dict[str, FieldOrigin]) -> dict[str, FieldOrigin]:
        unknown = sorted(set(value) - set(cls.model_fields))
        if unknown:
            raise ValueError(f"field_origin com campos inexistentes: {', '.join(unknown)}")
        return value
