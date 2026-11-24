"""Tabelas do banco (SPEC §10, D25, D35).

A demanda inteira fica em ``requests.demand`` (JSONB); as colunas ``requester``,
``department`` e ``status`` são cópias para consulta e ficam em sincronia via
``RequestRow.update_demand``. Listas fechadas da SPEC viram ``CHECK`` no banco.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, get_args

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.schemas.api import AuditActor
from app.schemas.demand import Demand, DependencyStatus, PriorityLevel, RequestStatus

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

AUDIT_ACTORS: tuple[str, ...] = get_args(AuditActor)
MESSAGE_ROLES = ("requester", "assistant")
USER_ROLES = ("requester", "manager")
TASK_STATUSES = ("Aberta", "Concluída")  # "Bloqueada" é a flag blocked (D03, D13)
PRIORITY_LEVELS: tuple[str, ...] = get_args(PriorityLevel)
DEPENDENCY_STATUSES: tuple[str, ...] = get_args(DependencyStatus)


def _in(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


def _timestamp() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {dict[str, Any]: JSONB}


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in("role", USER_ROLES), name="role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = _timestamp()


class RequestRow(Base):
    __tablename__ = "requests"
    __table_args__ = (
        CheckConstraint(_in("status", tuple(s.value for s in RequestStatus)), name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    requester: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(200))
    channel: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), index=True)
    demand: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _timestamp()
    updated_at: Mapped[datetime] = _timestamp()

    messages: Mapped[list[Message]] = relationship(
        back_populates="request", order_by="Message.id", cascade="all, delete-orphan"
    )

    @classmethod
    def from_demand(cls, demand: Demand, *, channel: str, now: datetime) -> RequestRow:
        return cls(
            id=demand.request_id,
            requester=demand.requester,
            department=demand.department,
            channel=channel,
            status=demand.status.value,
            demand=demand.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        )

    def to_demand(self) -> Demand:
        return Demand.model_validate(self.demand)

    def update_demand(self, demand: Demand, *, now: datetime) -> None:
        """Grava a nova versão da demanda e mantém as colunas de consulta em sincronia."""
        if demand.request_id != self.id:
            raise ValueError("a demanda pertence a outra solicitação")
        self.demand = demand.model_dump(mode="json")
        self.requester = demand.requester
        self.department = demand.department
        self.status = demand.status.value
        self.updated_at = now


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (CheckConstraint(_in("role", MESSAGE_ROLES), name="role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requests.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _timestamp()

    request: Mapped[RequestRow] = relationship(back_populates="messages")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(_in("status", TASK_STATUSES), name="status"),
        CheckConstraint(f"priority IS NULL OR {_in('priority', PRIORITY_LEVELS)}", name="priority"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # D25: inteiro
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("requests.id"), index=True)
    external_task_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    type: Mapped[str] = mapped_column(String(50))
    brand: Mapped[str | None] = mapped_column(String(100))
    supplier: Mapped[str | None] = mapped_column(String(100))
    campaign: Mapped[str | None] = mapped_column(String(200))
    assigned_to: Mapped[str | None] = mapped_column(String(50), index=True)
    priority: Mapped[str | None] = mapped_column(String(20))
    deadline: Mapped[date | None] = mapped_column(Date)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    status: Mapped[str] = mapped_column(
        String(20), default="Aberta", server_default="Aberta", index=True
    )
    briefing: Mapped[str] = mapped_column(Text)
    briefing_score: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _timestamp()

    dependencies: Mapped[list[DependencyRow]] = relationship(
        back_populates="task", order_by="DependencyRow.id", cascade="all, delete-orphan"
    )


class DependencyRow(Base):
    __tablename__ = "dependencies"
    __table_args__ = (CheckConstraint(_in("status", DEPENDENCY_STATUSES), name="status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="Pendente", server_default="Pendente")

    task: Mapped[Task] = relationship(back_populates="dependencies")


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (CheckConstraint(_in("actor", AUDIT_ACTORS), name="actor"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("requests.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    actor: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(64), index=True)
    previous_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    timestamp: Mapped[datetime] = _timestamp()


__all__ = [
    "AuditLog",
    "Base",
    "DependencyRow",
    "Message",
    "RequestRow",
    "Task",
    "User",
]
