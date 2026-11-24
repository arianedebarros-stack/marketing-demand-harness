"""AC11 — Assignment Engine: responsável compatível com menor carga (SPEC §8.6, D33)."""

from typing import Any

import pytest

from app.core.config import AppConfig, TeamMember, load_app_config
from app.engines.assignment import OpenTask, compute_assignment
from app.schemas.demand import Demand

CONFIG: AppConfig = load_app_config()
APPROVER = CONFIG.task_types.approver_default


def _demand(**fields: Any) -> Demand:
    return Demand(requester="Ana", department="Comercial", **fields)


def _open(employee_id: str | None, count: int, priority: Any = "Normal") -> list[OpenTask]:
    return [OpenTask(assigned_to=employee_id, priority=priority) for _ in range(count)]


def _assign(task_type: str | None, open_tasks: list[OpenTask] | None = None, **fields: Any) -> Any:
    return compute_assignment(
        _demand(task_type=task_type, **fields), config=CONFIG, open_tasks=open_tasks or []
    )


# --- AC11 ----------------------------------------------------------------------------------


def test_arte_goes_to_designer_a_53_vs_80() -> None:
    """AC11: Designer A (8/15 = 53%) ganha de Designer B (12/15 = 80%)."""
    result = _assign("Arte")

    assert result.employee_id == "designer-a"
    assert result.name == "Designer A"
    loads = [(item.employee_id, round(item.load * 100)) for item in result.loads]
    assert loads == [("designer-a", 53), ("designer-b", 80)]
    assert "53%" in result.reason
    assert result.locked is False


def test_video_goes_to_videomaker() -> None:
    """AC11: Vídeo → Videomaker (único com a skill)."""
    result = _assign("Vídeo")

    assert (result.employee_id, result.name) == ("videomaker", "Videomaker")
    assert [item.employee_id for item in result.loads] == ["videomaker"]


def test_only_compatible_members_are_candidates() -> None:
    """Push: Designer B (80%) e Analista (6/12 = 50%) → Analista."""
    result = _assign("Push")

    assert result.employee_id == "analista"
    assert [item.employee_id for item in result.loads] == ["analista", "designer-b"]


# --- Carga com tarefas abertas -------------------------------------------------------------


def test_open_tasks_increase_load() -> None:
    """Designer A com 5 tarefas abertas: 13/15 = 87% > Designer B 80% → B."""
    result = _assign("Arte", _open("designer-a", 5))

    assert result.employee_id == "designer-b"
    first = result.loads[0]
    assert (first.employee_id, first.open_tasks, round(first.load * 100)) == ("designer-b", 0, 80)
    a = next(item for item in result.loads if item.employee_id == "designer-a")
    assert (a.open_tasks, round(a.load * 100)) == (5, 87)


def test_tasks_of_others_and_unassigned_are_ignored() -> None:
    tasks = _open("videomaker", 10) + _open(None, 10) + _open("ex-colaborador", 10)
    assert _assign("Arte", tasks).employee_id == "designer-a"


def test_tie_on_load_breaks_by_high_priority_open_tasks() -> None:
    """Carga igual (12/15): quem tem menos tarefas Alta/Crítica abertas ganha."""
    tasks = _open("designer-a", 2, "Alta") + _open("designer-a", 2, "Normal")
    tasks += _open("designer-b", 0)

    result = _assign("Arte", tasks)

    assert result.employee_id == "designer-b"
    a = next(item for item in result.loads if item.employee_id == "designer-a")
    assert (a.load, a.high_priority_open) == (pytest.approx(0.8), 2)
    assert "Alta/Crítica" in result.reason


def test_critical_counts_as_high_priority() -> None:
    tasks = _open("designer-a", 1, "Crítica") + _open("designer-a", 3, "Baixa")
    assert _assign("Arte", tasks).employee_id == "designer-b"


def test_full_tie_keeps_team_order() -> None:
    """Empate em carga e em tarefas Alta/Crítica: vale a ordem de team.json."""
    tasks = _open("designer-a", 4, "Normal")
    assert _assign("Arte", tasks).employee_id == "designer-a"


# --- Sem candidato (D33) -------------------------------------------------------------------


def test_no_candidate_leaves_assignee_empty_with_approver_name() -> None:
    """D33: sem candidato, employee_id = None; o nome do approver_default vem para exibição."""
    team = [m for m in CONFIG.team if "Vídeo" not in m.skills]
    config = CONFIG.model_copy(update={"team": team})

    result = compute_assignment(_demand(task_type="Vídeo"), config=config, open_tasks=[])

    assert result.employee_id is None
    assert result.name == APPROVER
    assert result.loads == []
    assert "Vídeo" in result.reason
    assert APPROVER in result.reason


def test_no_type_has_no_candidate() -> None:
    result = _assign(None)

    assert (result.employee_id, result.name) == (None, APPROVER)
    assert "sem tipo" in result.reason


# --- Trava do gestor -----------------------------------------------------------------------


def test_assignment_locked_is_not_recalculated() -> None:
    result = _assign(
        "Arte", _open("designer-b", 20), assigned_to="designer-b", assignment_locked=True
    )

    assert result.locked is True
    assert (result.employee_id, result.name) == ("designer-b", "Designer B")
    assert result.loads == []
    assert result.reason == "Responsável definido pelo gestor; não recalculado."


def test_locked_with_unknown_id_shows_id() -> None:
    result = _assign("Arte", assigned_to="freela-x", assignment_locked=True)
    assert (result.employee_id, result.name) == ("freela-x", "freela-x")


def test_locked_without_assignee_shows_approver() -> None:
    result = _assign("Arte", assignment_locked=True)
    assert (result.employee_id, result.name) == (None, APPROVER)


# --- Geral ---------------------------------------------------------------------------------


def test_capacity_comes_from_config() -> None:
    team = [
        TeamMember(id="x", name="X", skills=["Arte"], capacity=10, open_base=5),
        TeamMember(id="y", name="Y", skills=["Arte"], capacity=40, open_base=10),
    ]
    config = CONFIG.model_copy(update={"team": team})

    result = compute_assignment(_demand(task_type="Arte"), config=config, open_tasks=[])

    assert result.employee_id == "y"  # 25% < 50%


def test_audit_payload() -> None:
    result = _assign("Arte")

    payload = result.audit_payload()

    assert payload["action"] == "assignment_calculated"
    assert payload["new_value"]["employee_id"] == "designer-a"
    assert payload["new_value"]["loads"][0] == {
        "employee_id": "designer-a",
        "name": "Designer A",
        "load": 0.5333,
        "open_tasks": 0,
        "high_priority_open": 0,
    }


def test_locked_audit_action() -> None:
    result = _assign("Arte", assigned_to="designer-b", assignment_locked=True)
    assert result.audit_payload()["action"] == "assignment_locked"


def test_input_demand_is_not_mutated() -> None:
    demand = _demand(task_type="Arte")
    snapshot = demand.model_copy(deep=True)

    compute_assignment(demand, config=CONFIG, open_tasks=_open("designer-a", 3))

    assert demand == snapshot
