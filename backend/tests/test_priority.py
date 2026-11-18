"""AC09 — Priority Engine (SPEC §8.5, D20, D26, D32)."""

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.core.config import AppConfig, PriorityBand, load_app_config
from app.engines.priority import compute_priority
from app.llm.fake_client import FakeLLMClient
from app.schemas.demand import Demand, Dependency
from app.services.pipeline import process_message

CONFIG: AppConfig = load_app_config()
TZ = ZoneInfo("America/Sao_Paulo")
MONDAY = date(2026, 10, 19)
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)  # segunda de manhã (D20)


def _at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(MONDAY + timedelta(days=day_offset), datetime.min.time(), TZ).replace(
        hour=hour, minute=minute
    )


def _demand(**fields: Any) -> Demand:
    return Demand(requester="Ana", department="Comercial", **fields)


def _case_06(**overrides: Any) -> Demand:
    fields: dict[str, Any] = {
        "task_type": "Arte",
        "is_promotional": True,
        "brand": "Construjá",
        "supplier": "Krona",
        "price": "Conforme planilha anexada",
        "deadline": MONDAY + timedelta(days=1),
        "dependencies": [Dependency(dependency="Aprovação de preço", owner="Compras")],
    }
    fields.update(overrides)
    return _demand(**fields)


def _priority(demand: Demand, now: datetime = NOW, config: AppConfig = CONFIG) -> Any:
    return compute_priority(demand, config=config, now=now, tz=TZ)


# --- AC09 ----------------------------------------------------------------------------------


def test_example_90_80_40_70_is_alta() -> None:
    """AC09: urgência 90, impacto 80, dependências 40, risco 70 → 76,5 → Alta (caso 06)."""
    result = _priority(_case_06())

    assert result.factors["urgency"] == 90
    assert result.factors["impact"] == 80
    assert result.factors["dependencies"] == 40
    assert result.factors["risk"] == 70
    assert result.factors["hours_to_deadline"] == 33
    assert result.score == 76.5
    assert result.level == "Alta"
    assert result.locked is False


def test_case_02_is_70_5_alta() -> None:
    """D20: caso 02 pela manhã → 70,5 → Alta."""
    result = _priority(_case_06(dependencies=[]))
    assert (result.score, result.level) == (70.5, "Alta")


def test_deadline_under_24h_is_critical() -> None:
    """AC09: prazo < 24 h → urgência 100 e Crítica."""
    result = _priority(_case_06(), now=_at(0, 19))  # 23 h até amanhã às 18h

    assert result.factors["urgency"] == 100
    assert result.level == "Crítica"
    assert any("Crítica" in reason for reason in result.reasons)


def test_deadline_today_and_overdue_are_critical() -> None:
    today = _priority(_case_06(deadline=MONDAY))
    overdue = _priority(_case_06(deadline=MONDAY - timedelta(days=2)))

    assert (today.factors["urgency"], today.level) == (100, "Crítica")
    assert (overdue.factors["urgency"], overdue.level) == (100, "Crítica")
    assert overdue.factors["hours_to_deadline"] < 0


def test_exactly_24h_is_not_critical() -> None:
    """D32: < 24 é estrito; 24 h exatas dá urgência 90 e não eleva para Crítica."""
    result = _priority(_case_06(), now=_at(0, 18))

    assert result.factors["hours_to_deadline"] == 24
    assert result.factors["urgency"] == 90
    assert result.level == "Alta"


def _pipeline_demand(message: str) -> Demand:
    return process_message(
        _demand(), [message], llm=FakeLLMClient(), config=CONFIG, now=NOW, tz=TZ
    ).demand


def test_urgente_does_not_change_priority() -> None:
    """AC09: a palavra "urgente" não altera prazo nem prioridade."""
    text = (
        "Preciso de um feed 1080x1350 da Construjá para divulgar a promoção Krona amanhã. "
        "Os produtos e preços estão na planilha anexada e a promoção vale até sexta."
    )
    plain = _pipeline_demand(text)
    urgent = _pipeline_demand("URGENTE! " + text + " É urgente, urgentíssimo.")

    assert urgent.deadline == plain.deadline
    assert _priority(urgent) == _priority(plain)


def test_urgente_without_date_has_no_deadline() -> None:
    demand = _pipeline_demand("Arte urgente da Construjá")

    assert demand.deadline is None
    result = _priority(demand)
    assert result.factors["urgency"] == CONFIG.priorities.urgency_without_deadline
    assert result.factors["hours_to_deadline"] is None


def test_priority_locked_is_not_recalculated() -> None:
    """AC09: prioridade definida pelo gestor (priority_locked) não é recalculada."""
    demand = _case_06(deadline=MONDAY, priority="Baixa", priority_score=12.0, priority_locked=True)

    result = _priority(demand)

    assert result.locked is True
    assert (result.level, result.score) == ("Baixa", 12.0)
    assert result.factors == {}
    assert result.reasons == ["Prioridade definida pelo gestor; não recalculada."]


def test_published_error_is_impact_100_risk_100_critical() -> None:
    """AC09/D26: o Fake não preenche published_error, então a demanda é montada aqui."""
    demand = _demand(
        task_type="Relatório",
        published_error=True,
        deadline=MONDAY + timedelta(days=30),
    )

    result = _priority(demand)

    assert result.factors["impact"] == 100
    assert result.factors["risk"] == 100
    assert result.level == "Crítica"
    assert any("erro" in reason.lower() for reason in result.reasons)


def test_event_today_is_critical() -> None:
    demand = _demand(task_type="Evento", event_date=MONDAY, deadline=MONDAY + timedelta(days=30))
    assert _priority(demand).level == "Crítica"


def test_event_tomorrow_is_not_elevated() -> None:
    demand = _demand(
        task_type="Evento", event_date=MONDAY + timedelta(days=1), deadline=MONDAY + timedelta(30)
    )
    assert _priority(demand).level != "Crítica"


# --- Fatores -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "urgency"),
    [
        (_at(0, 18, 1), 100),  # 23h59 até amanhã 18h
        (_at(-1, 18), 90),  # 48 h
        (_at(-1, 17), 60),  # 49 h
        (_at(-4, 18), 60),  # 120 h
        (_at(-4, 17), 35),  # 121 h
        (_at(-9, 18), 35),  # 240 h
        (_at(-9, 17), 15),  # 241 h
    ],
)
def test_urgency_by_hours(now: datetime, urgency: int) -> None:
    demand = _demand(task_type="Arte", deadline=MONDAY + timedelta(days=1))
    assert _priority(demand, now=now).factors["urgency"] == urgency


def test_deadline_is_counted_at_18h_local_time() -> None:
    """A hora do prazo vem de priorities.json; o 'agora' em UTC é convertido para APP_TIMEZONE."""
    now_utc = NOW.astimezone(ZoneInfo("UTC"))
    demand = _demand(task_type="Arte", deadline=MONDAY + timedelta(days=1))
    assert _priority(demand, now=now_utc).factors["hours_to_deadline"] == 33


def test_naive_now_is_local_time() -> None:
    demand = _demand(task_type="Arte", deadline=MONDAY + timedelta(days=1))
    naive = NOW.replace(tzinfo=None)
    assert _priority(demand, now=naive).factors["hours_to_deadline"] == 33


@pytest.mark.parametrize(
    ("fields", "impact"),
    [
        ({"task_type": "Arte"}, 60),
        ({"task_type": "Arte", "is_promotional": True}, 80),
        ({"task_type": "Evento", "is_promotional": True}, 85),  # máximo, nunca reduz
        ({"task_type": "Relatório"}, 35),
        ({"task_type": None}, 40),  # sem tipo → impacto de "Outro"
        ({"task_type": "Arte", "published_error": True}, 100),
    ],
)
def test_impact(fields: dict[str, Any], impact: int) -> None:
    assert _priority(_demand(**fields)).factors["impact"] == impact


@pytest.mark.parametrize(("pending", "score"), [(0, 0), (1, 40), (2, 70), (3, 90), (5, 90)])
def test_dependencies_count_only_pending(pending: int, score: int) -> None:
    dependencies = [Dependency(dependency=f"D{i}", owner="Compras") for i in range(pending)]
    dependencies.append(Dependency(dependency="Resolvida", owner="Krona", status="Resolvida"))

    result = _priority(_demand(task_type="Arte", dependencies=dependencies))

    assert result.factors["dependencies"] == score


@pytest.mark.parametrize(
    ("fields", "risk"),
    [
        ({"published_error": True, "is_promotional": True, "price": "10"}, 100),
        ({"is_promotional": True, "price": "Conforme planilha anexada"}, 70),
        ({"is_promotional": True, "supplier": "Krona"}, 50),
        ({"task_type": "Vídeo", "supplier": "Krona"}, 50),  # D32: qualquer com fornecedor
        ({"price": "10"}, 30),  # preço sem promoção não conta
        ({}, 30),
    ],
)
def test_risk(fields: dict[str, Any], risk: int) -> None:
    fields.setdefault("task_type", "Arte")
    assert _priority(_demand(**fields)).factors["risk"] == risk


# --- Faixas e elevação ---------------------------------------------------------------------


def test_up_to_72h_raises_to_at_least_alta() -> None:
    """Relatório com prazo em 57 h: 39 pontos (Baixa) → elevado para Alta."""
    result = _priority(_demand(task_type="Relatório", deadline=MONDAY + timedelta(days=2)))

    assert result.score == 39
    assert result.level == "Alta"
    assert any("72" in reason for reason in result.reasons)


def test_beyond_72h_keeps_band() -> None:
    result = _priority(_demand(task_type="Relatório", deadline=MONDAY + timedelta(days=3)))

    assert result.factors["hours_to_deadline"] == 81
    assert (result.score, result.level) == (39, "Baixa")


def test_elevation_never_lowers() -> None:
    """Se a faixa da pontuação já é maior que a da elevação, ela fica."""
    bands = [
        PriorityBand(level="Crítica", min=30),
        PriorityBand(level="Alta", min=20),
        PriorityBand(level="Normal", min=10),
        PriorityBand(level="Baixa", min=0),
    ]
    config = CONFIG.model_copy(
        update={"priorities": CONFIG.priorities.model_copy(update={"bands": bands})}
    )

    result = _priority(
        _demand(task_type="Relatório", deadline=MONDAY + timedelta(days=2)), config=config
    )

    assert result.level == "Crítica"


@pytest.mark.parametrize(
    ("score_fields", "level"),
    [
        ({"task_type": "Relatório"}, "Baixa"),  # 20×0,4 + 35×0,3 + 0 + 30×0,15 = 23
        (
            {
                "task_type": "Evento",
                "is_promotional": True,
                "supplier": "Krona",
                "deadline": MONDAY + timedelta(days=4),
            },
            "Normal",
        ),  # 60×0,4 + 85×0,3 + 0 + 50×0,15 = 57
    ],
)
def test_band_from_score(score_fields: dict[str, Any], level: str) -> None:
    assert _priority(_demand(**score_fields)).level == level


def test_reasons_explain_each_factor() -> None:
    reasons = _priority(_case_06()).reasons

    assert reasons[0].startswith("Urgência 90")
    assert reasons[1].startswith("Impacto 80")
    assert reasons[2].startswith("Dependências 40")
    assert reasons[3].startswith("Risco 70")
    assert reasons[4] == "Pontuação 76,5 → Alta"


def test_audit_payload() -> None:
    result = _priority(_case_06())

    payload = result.audit_payload()

    assert payload["action"] == "priority_calculated"
    assert payload["new_value"]["level"] == "Alta"
    assert payload["new_value"]["score"] == 76.5
    assert payload["new_value"]["reasons"] == result.reasons


def test_input_demand_is_not_mutated() -> None:
    demand = _case_06()
    snapshot = demand.model_copy(deep=True)

    _priority(demand)

    assert demand == snapshot
