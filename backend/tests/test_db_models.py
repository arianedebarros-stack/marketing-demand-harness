"""T14 — models SQLAlchemy e restrições do banco (SPEC §10, D35)."""

from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditLog, DependencyRow, Message, RequestRow, Task, User
from app.schemas.demand import Demand, Dependency, DuplicateCandidate, RequestStatus

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))


def _request(session: Session, demand: Demand | None = None) -> RequestRow:
    demand = demand or Demand(requester="Ana", department="Comercial")
    row = RequestRow.from_demand(demand, channel="chat", now=NOW)
    session.add(row)
    session.flush()
    return row


def _task(session: Session, request: RequestRow, **fields: object) -> Task:
    data: dict[str, object] = {
        "request_id": request.id,
        "title": "Arte | Promoção Krona | Construjá",
        "type": "Arte",
        "brand": "Construjá",
        "supplier": "Krona",
        "briefing": "TÍTULO: Arte | Promoção Krona | Construjá",
        "briefing_score": 100,
        "created_at": NOW,
    }
    data.update(fields)
    task = Task(**data)
    session.add(task)
    session.flush()
    return task


def test_request_stores_whole_demand_as_jsonb(session: Session) -> None:
    """A demanda inteira (inclusive duplicate_of, D35) vai em requests.demand."""
    demand = Demand(
        requester="Ana",
        department="Comercial",
        task_type="Arte",
        deadline=date(2026, 10, 20),
        status=RequestStatus.PENDING_APPROVAL,
        dependencies=[Dependency(dependency="Aprovação de preço", owner="Compras")],
        duplicate_of=DuplicateCandidate(
            task_id=7, title="Arte | Promoção Krona | Construjá",
            criteria=["similar_title"], jaccard=1.0,
        ),
    )  # fmt: skip
    row = _request(session, demand)
    session.expire_all()

    loaded = session.get(RequestRow, demand.request_id)

    assert loaded is not None
    assert loaded.to_demand() == demand
    assert loaded.status == "PENDING_APPROVAL"
    assert (loaded.requester, loaded.department, loaded.channel) == ("Ana", "Comercial", "chat")
    assert loaded.created_at == NOW == loaded.updated_at
    assert row.id == demand.request_id


def test_update_demand_keeps_columns_in_sync(session: Session) -> None:
    row = _request(session)
    later = NOW.replace(hour=10)

    demand = row.to_demand().model_copy(update={"status": RequestStatus.NEEDS_INFORMATION})
    row.update_demand(demand, now=later)
    session.flush()
    session.expire_all()

    loaded = session.get(RequestRow, row.id)
    assert loaded is not None
    assert loaded.status == "NEEDS_INFORMATION"
    assert loaded.to_demand().status is RequestStatus.NEEDS_INFORMATION
    assert loaded.updated_at == later


def test_update_demand_rejects_other_request(session: Session) -> None:
    row = _request(session)
    other = Demand(requester="Bia", department="RH")

    with pytest.raises(ValueError):
        row.update_demand(other, now=NOW)


def test_messages_belong_to_request(session: Session) -> None:
    row = _request(session)
    session.add_all(
        [
            Message(request_id=row.id, role="requester", text="Faz uma arte", created_at=NOW),
            Message(request_id=row.id, role="assistant", text="Qual marca?", created_at=NOW),
        ]
    )
    session.flush()

    texts = session.scalars(
        select(Message.text).where(Message.request_id == row.id).order_by(Message.id)
    ).all()
    assert texts == ["Faz uma arte", "Qual marca?"]


def test_task_with_dependencies(session: Session) -> None:
    task = _task(session, _request(session), blocked=True, deadline=date(2026, 10, 20))
    session.add(DependencyRow(task_id=task.id, description="Aprovação de preço", owner="Compras"))
    session.flush()
    session.expire_all()

    loaded = session.get(Task, task.id)
    assert loaded is not None
    assert loaded.status == "Aberta"
    assert loaded.blocked is True
    assert [(d.description, d.status) for d in loaded.dependencies] == [
        ("Aprovação de preço", "Pendente")
    ]


def test_task_ids_are_integers(session: Session) -> None:
    """D25: ids de tarefa são inteiros; ids de demanda são UUID."""
    task = _task(session, _request(session))
    assert isinstance(task.id, int)


def test_user_table(session: Session) -> None:
    session.add(User(name="Gestor de Marketing", role="manager", created_at=NOW))
    session.flush()
    assert session.scalar(select(User.role)) == "manager"


@pytest.mark.parametrize(
    ("model", "fields"),
    [
        (AuditLog, {"actor": "robo", "action": "x", "timestamp": NOW}),
        (Message, {"role": "bot", "text": "x", "created_at": NOW}),
        (Task, {"status": "Bloqueada"}),
        (Task, {"priority": "Urgentíssima"}),
        (DependencyRow, {"status": "Talvez"}),
        (User, {"name": "X", "role": "admin", "created_at": NOW}),
    ],
)
def test_check_constraints(session: Session, model: type, fields: dict[str, object]) -> None:
    """Valores fora das listas da SPEC são recusados pelo banco."""
    request = _request(session)
    if model is Message:
        fields = {**fields, "request_id": request.id}
    if model is DependencyRow:
        task = _task(session, request)
        fields = {"task_id": task.id, "description": "x", "owner": "y", **fields}
    with pytest.raises(IntegrityError):
        if model is Task:
            _task(session, request, **fields)
        else:
            session.add(model(**fields))
            session.flush()


@pytest.mark.parametrize("status", ["Aberta", "Concluída"])
def test_task_statuses_accepted(session: Session, status: str) -> None:
    assert _task(session, _request(session), status=status).status == status


def test_request_status_constraint(session: Session) -> None:
    row = _request(session)
    row.status = "INVENTADO"
    with pytest.raises(IntegrityError):
        session.flush()


def test_audit_needs_existing_request(session: Session) -> None:
    session.add(AuditLog(request_id=uuid4(), actor="harness", action="x", timestamp=NOW))
    with pytest.raises(IntegrityError):
        session.flush()
