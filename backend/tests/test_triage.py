"""Triagem automática depois de READY_FOR_TRIAGE (D01, D34, D36)."""

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.core.config import AppConfig, load_app_config
from app.core.state_machine import InvalidTransition
from app.engines.assignment import OpenTask
from app.engines.dedupe import ExistingTask
from app.llm.fake_client import FakeLLMClient
from app.schemas.demand import Demand, FieldOrigin, RequestStatus
from app.services.pipeline import process_message
from app.services.triage import TriageNotReadyError, run_triage

CONFIG: AppConfig = load_app_config()
TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)
S = RequestStatus
CASE_02 = (
    "Preciso de um feed 1080x1350 da Construjá para divulgar a promoção Krona amanhã. "
    "Os produtos e preços estão na planilha anexada e a promoção vale até sexta."
)
CASE_06 = (
    "Preciso de uma arte da Krona para amanhã.",
    "Construjá",
    "Instagram feed. São 3 produtos da planilha anexada. Promoção válida até sexta. "
    "Ainda aguardando aprovação de preço por Compras.",
)


def _ready(*messages: str) -> Demand:
    demand = Demand(requester="Ana", department="Comercial")
    history: list[str] = []
    for message in messages:
        history.append(message)
        demand = process_message(
            demand, history, llm=FakeLLMClient(), config=CONFIG, now=NOW, tz=TZ
        ).demand
    assert demand.status is S.READY_FOR_TRIAGE
    return demand


def _triage(
    demand: Demand,
    open_tasks: list[OpenTask] | None = None,
    existing: list[ExistingTask] | None = None,
) -> Any:
    return run_triage(
        demand,
        open_tasks=open_tasks or [],
        existing_tasks=existing or [],
        config=CONFIG,
        now=NOW,
        tz=TZ,
    )


def _existing(**fields: Any) -> ExistingTask:
    data: dict[str, Any] = {
        "id": 7,
        "title": "Arte | Promoção Krona | Construjá",
        "brand": "Construjá",
        "task_type": "Arte",
        "supplier": "Krona",
        "campaign": None,
        "created_at": NOW - timedelta(days=1),
        "is_open": True,
    }
    data.update(fields)
    return ExistingTask(**data)


def test_case_06_triage_reaches_pending_approval() -> None:
    """Caso 06: Alta, Designer A, dependência Compras, aguardando aprovação."""
    result = _triage(_ready(*CASE_06))
    demand = result.demand

    assert demand.status is S.PENDING_APPROVAL
    assert result.next_action == "AWAIT_APPROVAL"
    assert (demand.priority, demand.priority_score) == ("Alta", 76.5)
    assert demand.assigned_to == "designer-a"
    assert demand.approver == CONFIG.task_types.approver_default
    assert [(d.dependency, d.owner, d.status) for d in demand.dependencies] == [
        ("Aprovação de preço", "Compras", "Pendente")
    ]
    assert demand.duplicate_of is None
    for name in ("priority", "assigned_to", "approver"):
        assert demand.field_origin[name] is FieldOrigin.HARNESS


def test_triage_events_cover_each_engine() -> None:
    result = _triage(_ready(*CASE_06))
    actions = [e.action for e in result.events]

    assert actions == [
        "status_transition",
        "priority_calculated",
        "assignment_calculated",
        "dependencies_checked",
        "no_duplicate",
        "field_registered",
        "field_registered",
        "field_registered",
        "status_transition",
    ]
    deps = next(e for e in result.events if e.action == "dependencies_checked")
    assert deps.new_value == {"pending": 1, "blocked": True}


def test_triage_records_duplicate_on_demand() -> None:
    """Caso 05: a tarefa aberta parecida vai para duplicate_of (D35)."""
    result = _triage(_ready(CASE_02), existing=[_existing()])

    duplicate = result.demand.duplicate_of
    assert duplicate is not None
    assert (duplicate.task_id, duplicate.title) == (7, "Arte | Promoção Krona | Construjá")
    assert duplicate.criteria == ["same_brand_type_supplier", "similar_title"]
    assert result.demand.status is S.PENDING_APPROVAL


def test_triage_clears_stale_duplicate() -> None:
    demand = _triage(_ready(CASE_02), existing=[_existing()]).demand
    again = demand.model_copy(update={"status": S.READY_FOR_TRIAGE})

    assert _triage(again).demand.duplicate_of is None


def test_open_tasks_change_assignee() -> None:
    open_tasks = [OpenTask(assigned_to="designer-a", priority="Normal") for _ in range(5)]
    assert _triage(_ready(CASE_02), open_tasks=open_tasks).demand.assigned_to == "designer-b"


def test_locked_priority_and_assignee_are_kept() -> None:
    demand = _ready(CASE_02).model_copy(
        update={
            "priority": "Baixa",
            "priority_score": 10.0,
            "priority_locked": True,
            "assigned_to": "designer-b",
            "assignment_locked": True,
            "field_origin": {
                **_ready(CASE_02).field_origin,
                "priority": FieldOrigin.MANAGER,
                "assigned_to": FieldOrigin.MANAGER,
            },
        }
    )

    out = _triage(demand).demand

    assert (out.priority, out.priority_score, out.assigned_to) == ("Baixa", 10.0, "designer-b")
    assert out.field_origin["priority"] is FieldOrigin.MANAGER


def test_manager_approver_is_kept() -> None:
    demand = _ready(CASE_02).model_copy(update={"approver": "Diretoria"})
    assert _triage(demand).demand.approver == "Diretoria"


def test_no_candidate_leaves_assignee_empty() -> None:
    """D33: sem candidato, assigned_to fica vazio."""
    team = [m for m in CONFIG.team if "Arte" not in m.skills]
    config = CONFIG.model_copy(update={"team": team})
    result = run_triage(
        _ready(CASE_02), open_tasks=[], existing_tasks=[], config=config, now=NOW, tz=TZ
    )

    assert result.demand.assigned_to is None
    assert "assigned_to" not in result.demand.field_origin


def test_rerun_in_pending_approval_keeps_state() -> None:
    """POST /triage em PENDING_APPROVAL recalcula sem sair do estado."""
    pending = _triage(_ready(CASE_02)).demand

    result = _triage(pending, existing=[_existing()])

    assert result.demand.status is S.PENDING_APPROVAL
    assert result.demand.duplicate_of is not None
    assert "status_transition" not in [e.action for e in result.events]


def test_triage_requires_100_percent() -> None:
    demand = _ready(CASE_02).model_copy(update={"briefing_score": 80})
    with pytest.raises(TriageNotReadyError):
        _triage(demand)


@pytest.mark.parametrize("status", [S.NEEDS_INFORMATION, S.APPROVED, S.TASK_CREATED, S.CANCELLED])
def test_triage_in_other_states_is_invalid(status: RequestStatus) -> None:
    demand = _ready(CASE_02).model_copy(update={"status": status})
    with pytest.raises(InvalidTransition):
        _triage(demand)


def test_input_is_not_mutated() -> None:
    demand = _ready(CASE_02)
    snapshot = demand.model_copy(deep=True)

    _triage(demand)

    assert demand == snapshot


def test_deadline_date_is_kept() -> None:
    assert _triage(_ready(CASE_02)).demand.deadline == date(2026, 10, 20)
