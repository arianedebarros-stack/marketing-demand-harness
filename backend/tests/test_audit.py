"""AC15 — tudo o que o harness faz fica em audit_log (SPEC §15, D35)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session

from app.core.config import AppConfig, load_app_config
from app.core.state_machine import InvalidTransition
from app.engines.assignment import compute_assignment
from app.engines.briefing import build_title
from app.engines.dedupe import ExistingTask, find_duplicate
from app.engines.dependency import resolve_dependency
from app.engines.priority import compute_priority
from app.llm.fake_client import FakeLLMClient
from app.models import RequestRow, Task
from app.schemas.audit import AuditEvent
from app.schemas.demand import Demand, RequestStatus
from app.services import audit
from app.services.pipeline import process_message

CONFIG: AppConfig = load_app_config()
TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)
CASE_06 = (
    "Preciso de uma arte da Krona para amanhã.",
    "Construjá",
    "Instagram feed. São 3 produtos da planilha anexada. Promoção válida até sexta. "
    "Ainda aguardando aprovação de preço por Compras.",
)


def _new_request(session: Session) -> Demand:
    demand = Demand(requester="Ana", department="Comercial")
    session.add(RequestRow.from_demand(demand, channel="chat", now=NOW))
    session.flush()
    return demand


def _run_case_06(session: Session) -> Demand:
    """Roda o caso 06 mensagem a mensagem e grava os eventos de cada rodada."""
    demand = _new_request(session)
    history: list[str] = []
    for minute, message in enumerate(CASE_06):
        history.append(message)
        result = process_message(
            demand, history, llm=FakeLLMClient(), config=CONFIG, now=NOW, tz=TZ
        )
        demand = result.demand
        audit.record_events(
            session,
            result.events,
            request_id=demand.request_id,
            timestamp=NOW + timedelta(minutes=minute),
        )
    session.flush()
    return demand


# --- AC15 ----------------------------------------------------------------------------------


def test_pipeline_events_are_all_recorded(session: Session) -> None:
    """AC15: recebimento, interpretação, classificação, campos, regras, score e transições."""
    demand = _run_case_06(session)

    entries = audit.entries_for_request(session, demand.request_id)
    actions = [e.action for e in entries]

    assert actions.count("message_received") == 3
    assert actions.count("interpretation") == 3
    assert actions.count("classification") == 3
    for action in ("field_registered", "rule_applied", "briefing_score", "status_transition"):
        assert action in actions
    assert entries[-1].action == "status_transition"
    assert entries[-1].new_value == {"status": "READY_FOR_TRIAGE"}
    assert [e.id for e in entries] == sorted(e.id for e in entries)
    assert {e.actor for e in entries} == {"user", "llm", "harness"}
    assert all(e.request_id == demand.request_id for e in entries)


def test_interpretation_keeps_provider(session: Session) -> None:
    demand = _run_case_06(session)

    first = next(
        e for e in audit.entries_for_request(session, demand.request_id)
        if e.action == "interpretation"
    )  # fmt: skip

    assert first.actor == "llm"
    assert isinstance(first.new_value, dict)
    assert first.new_value["provider"] == "fake"


def test_guardrail_discard_is_recorded(session: Session) -> None:
    demand = _new_request(session)
    events = [
        AuditEvent(
            "harness",
            "guardrail_discard",
            {"field": "price", "value": "R$ 9,90"},
            {"reason": "number_not_in_text", "replacement": None},
        )
    ]

    audit.record_events(session, events, request_id=demand.request_id, timestamp=NOW)

    [entry] = audit.entries_for_request(session, demand.request_id)
    assert entry.action == "guardrail_discard"
    assert entry.previous_value == {"field": "price", "value": "R$ 9,90"}


def test_invalid_transition_is_recorded(session: Session) -> None:
    """§7: transição inválida é registrada no audit log."""
    demand = _new_request(session).model_copy(update={"status": RequestStatus.TASK_CREATED})
    with pytest.raises(InvalidTransition) as exc:
        process_message(
            demand, ["Mais uma coisa"], llm=FakeLLMClient(), config=CONFIG, now=NOW, tz=TZ
        )

    audit.record_payload(
        session, exc.value.audit_payload(), actor="harness",
        request_id=demand.request_id, timestamp=NOW,
    )  # fmt: skip

    [entry] = audit.entries_for_request(session, demand.request_id)
    assert entry.action == "invalid_transition"
    assert entry.previous_value == {"status": "TASK_CREATED"}
    assert entry.new_value == {"status": "VALIDATING"}


def test_triage_engines_payloads_are_recorded(session: Session) -> None:
    """Prioridade (com motivos), responsável (com cargas) e duplicidade (§15)."""
    demand = _run_case_06(session)
    priority = compute_priority(demand, config=CONFIG, now=NOW, tz=TZ)
    assignment = compute_assignment(demand, config=CONFIG, open_tasks=[])
    dedupe = find_duplicate(
        demand,
        title=build_title(demand, config=CONFIG),
        tasks=[
            ExistingTask(
                id=9, title="Arte | Promoção Krona | Construjá", brand="Construjá",
                task_type="Arte", supplier="Krona", campaign=None, created_at=NOW, is_open=True,
            )
        ],
        config=CONFIG,
        now=NOW,
    )  # fmt: skip

    for payload in (priority.audit_payload(), assignment.audit_payload(), dedupe.audit_payload()):
        audit.record_payload(
            session, payload, actor="harness", request_id=demand.request_id, timestamp=NOW
        )

    entries = {e.action: e for e in audit.entries_for_request(session, demand.request_id)}
    assert isinstance(entries["priority_calculated"].new_value, dict)
    assert entries["priority_calculated"].new_value["level"] == "Alta"
    assert entries["priority_calculated"].new_value["reasons"] == priority.reasons
    assignment_value = entries["assignment_calculated"].new_value
    assert isinstance(assignment_value, dict)
    loads = assignment_value["loads"]
    assert isinstance(loads, list) and isinstance(loads[0], dict)
    assert loads[0]["name"] == "Designer A"
    assert isinstance(entries["duplicate_found"].new_value, dict)
    assert entries["duplicate_found"].new_value["task_id"] == 9


def test_task_events_are_linked_to_task(session: Session) -> None:
    """Criação de tarefa, resolução de dependência e edições ficam ligadas à tarefa."""
    demand = _run_case_06(session)
    task = Task(
        request_id=demand.request_id, title="Arte | Promoção Krona | Construjá", type="Arte",
        briefing="...", briefing_score=100, blocked=True, created_at=NOW,
    )  # fmt: skip
    session.add(task)
    session.flush()

    audit.record(
        session, actor="harness", action="task_created", request_id=demand.request_id,
        task_id=task.id, new_value={"external_task_id": "MKT-1"}, timestamp=NOW,
    )  # fmt: skip
    resolution = resolve_dependency(demand.dependencies, 0)
    audit.record_payload(
        session, resolution.audit_payload(), actor="user", task_id=task.id, timestamp=NOW
    )
    audit.record(
        session, actor="manager", action="human_edit", request_id=demand.request_id,
        previous_value={"field": "objective", "value": "A"},
        new_value={"field": "objective", "value": "B"}, timestamp=NOW,
    )  # fmt: skip

    task_entries = audit.entries_for_task(session, task.id)
    assert [e.action for e in task_entries] == ["task_created", "dependency_resolved"]
    assert task_entries[1].new_value == {"index": 0, "status": "Resolvida", "blocked": False}
    edit = audit.entries_for_request(session, demand.request_id)[-1]
    assert (edit.actor, edit.action) == ("manager", "human_edit")
    assert edit.previous_value == {"field": "objective", "value": "A"}


# --- Contrato do serviço -------------------------------------------------------------------


def test_timestamp_comes_from_caller(session: Session) -> None:
    demand = _new_request(session)
    when = datetime(2030, 1, 2, 3, 4, tzinfo=TZ)

    audit.record(session, actor="user", action="x", request_id=demand.request_id, timestamp=when)

    [entry] = audit.entries_for_request(session, demand.request_id)
    assert entry.timestamp == when


def test_empty_payloads_are_stored_as_null(session: Session) -> None:
    demand = _new_request(session)
    audit.record_events(
        session, [AuditEvent("harness", "x")], request_id=demand.request_id, timestamp=NOW
    )

    [entry] = audit.entries_for_request(session, demand.request_id)
    assert (entry.previous_value, entry.new_value) == (None, None)


def test_values_are_made_json_safe(session: Session) -> None:
    demand = _new_request(session)
    audit.record(
        session, actor="harness", action="x", request_id=demand.request_id,
        new_value={"deadline": NOW.date(), "id": demand.request_id}, timestamp=NOW,
    )  # fmt: skip

    [entry] = audit.entries_for_request(session, demand.request_id)
    assert entry.new_value == {"deadline": "2026-10-19", "id": str(demand.request_id)}


def test_unknown_actor_is_rejected(session: Session) -> None:
    with pytest.raises(ValueError):
        audit.record(session, actor="robo", action="x", timestamp=NOW)  # type: ignore[arg-type]


def test_naive_timestamp_is_rejected(session: Session) -> None:
    with pytest.raises(ValueError):
        audit.record(session, actor="user", action="x", timestamp=NOW.replace(tzinfo=None))
