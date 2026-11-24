"""Duplicidade antes de criar a tarefa (SPEC §8.8, caso 05, D12, D34)."""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.core.config import AppConfig, load_app_config
from app.engines.briefing import build_title
from app.engines.dedupe import ExistingTask, find_duplicate, title_jaccard
from app.llm.fake_client import FakeLLMClient
from app.schemas.demand import Demand
from app.services.pipeline import process_message

CONFIG: AppConfig = load_app_config()
TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)
CASE_02 = (
    "Preciso de um feed 1080x1350 da Construjá para divulgar a promoção Krona amanhã. "
    "Os produtos e preços estão na planilha anexada e a promoção vale até sexta."
)


def _task(task_id: int = 1, days_ago: float = 1, **fields: Any) -> ExistingTask:
    data: dict[str, Any] = {
        "id": task_id,
        "title": "Arte | Promoção Krona | Construjá",
        "brand": "Construjá",
        "task_type": "Arte",
        "supplier": "Krona",
        "campaign": None,
        "created_at": NOW - timedelta(days=days_ago),
        "is_open": True,
    }
    data.update(fields)
    return ExistingTask(**data)


def _demand(**fields: Any) -> Demand:
    base: dict[str, Any] = {
        "task_type": "Arte",
        "brand": "Construjá",
        "supplier": "Krona",
        "is_promotional": True,  # título "Arte | Promoção Krona | Construjá" (D30)
    }
    base.update(fields)
    return Demand(requester="Ana", department="Comercial", **base)


def _find(demand: Demand, tasks: list[ExistingTask], title: str | None = None) -> Any:
    return find_duplicate(
        demand,
        title=title if title is not None else build_title(demand, config=CONFIG),
        tasks=tasks,
        config=CONFIG,
        now=NOW,
    )


# --- Caso 05 -------------------------------------------------------------------------------


def test_case_05_finds_open_task() -> None:
    """Caso 05: caso 02 com "Arte | Promoção Krona | Construjá" já aberta → duplicidade."""
    demand = process_message(
        Demand(requester="Ana", department="Comercial"),
        [CASE_02],
        llm=FakeLLMClient(),
        config=CONFIG,
        now=NOW,
        tz=TZ,
    ).demand
    title = build_title(demand, config=CONFIG)
    existing = _task(task_id=42)

    result = _find(demand, [existing], title)

    assert title == "Arte | Promoção Krona | Construjá"
    assert result.duplicate == existing
    assert result.matches[0].criteria == ["same_brand_type_supplier", "similar_title"]
    assert result.matches[0].jaccard == 1.0


def test_no_open_tasks_no_duplicate() -> None:
    result = _find(_demand(), [])
    assert result.duplicate is None
    assert result.matches == []


# --- Critério 1: marca + tipo + (fornecedor ou campanha) em 30 dias -------------------------


def test_same_brand_type_and_campaign() -> None:
    task = _task(title="Outra coisa", supplier=None, campaign="Black Friday")
    result = _find(_demand(supplier=None, campaign="black friday"), [task])

    assert result.duplicate == task
    assert result.matches[0].criteria == ["same_brand_type_campaign"]


def test_comparison_ignores_accents_and_case() -> None:
    task = _task(title="X", brand="CONSTRUJA", task_type="arte", supplier="krona")
    assert _find(_demand(), [task]).duplicate == task


@pytest.mark.parametrize(
    "changes",
    [{"brand": "Ferjá"}, {"task_type": "Vídeo"}, {"supplier": "Tigre"}],
)
def test_different_brand_type_or_supplier_is_not_duplicate(changes: dict[str, Any]) -> None:
    task = _task(title="Título sem relação nenhuma", **changes)
    assert _find(_demand(), [task]).duplicate is None


def test_null_equals_null_does_not_count() -> None:
    """D12: sem fornecedor e sem campanha dos dois lados não é igualdade."""
    task = _task(title="Título sem relação", supplier=None, campaign=None)
    assert _find(_demand(supplier=None), [task]).duplicate is None


def test_window_of_30_days() -> None:
    inside = _task(title="X", days_ago=30)
    outside = _task(title="X", days_ago=30.01)

    assert _find(_demand(), [inside]).duplicate == inside
    assert _find(_demand(), [outside]).duplicate is None


def test_closed_task_is_ignored() -> None:
    assert _find(_demand(), [_task(is_open=False)]).duplicate is None


# --- Critério 2: Jaccard de palavras do título ---------------------------------------------


def test_similar_title_from_other_supplier_and_old_task() -> None:
    """Jaccard ≥ 0,75 vale sozinho, mesmo fora da janela de 30 dias (só tarefas abertas)."""
    task = _task(title="Arte | Promoção Krona | Construjá", supplier="Tigre", days_ago=90)

    result = _find(_demand(), [task])

    assert result.duplicate == task
    assert result.matches[0].criteria == ["similar_title"]


def test_jaccard_ignores_separator_accents_and_case() -> None:
    """D12: o separador "|" é ignorado."""
    assert title_jaccard("Arte | Promoção Krona | Construjá", "arte promocao KRONA construja") == 1


def test_jaccard_values() -> None:
    # {arte, promocao, krona, construja} x {arte, promocao, tigre, construja} → 3/5
    assert (
        title_jaccard("Arte | Promoção Krona | Construjá", "Arte | Promoção Tigre | Construjá")
        == 0.6
    )
    assert title_jaccard("", "Arte") == 0.0


def test_jaccard_keeps_numbers() -> None:
    """D34: números contam, então "2025" e "2026" são palavras diferentes."""
    assert (
        title_jaccard("Arte | Black Friday 2026 | Ferjá", "Arte | Black Friday 2025 | Ferjá") < 0.75
    )


def test_jaccard_threshold_is_inclusive() -> None:
    # {arte, a, b} x {arte, a, b, c} → 3/4 = 0,75 (conta); x {arte, a, b, c, d, e} → 0,5
    task = _task(title="Arte | A B C", brand="Ferjá")
    assert _find(_demand(), [task], title="Arte | A B").duplicate == task
    other = _task(title="Arte | A B C D E", brand="Ferjá")
    assert _find(_demand(), [other], title="Arte | A B").duplicate is None


# --- Escolha entre várias candidatas -------------------------------------------------------


def test_best_match_prefers_brand_criterion_then_jaccard_then_recent() -> None:
    by_title = _task(task_id=1, title="Arte | Promoção Krona | Construjá", supplier="Tigre")
    by_brand_old = _task(task_id=2, title="Peça antiga", days_ago=20)
    by_brand_new = _task(task_id=3, title="Peça nova", days_ago=2)
    both = _task(task_id=4, days_ago=10)

    result = _find(_demand(), [by_title, by_brand_old, by_brand_new, both])

    assert [m.task.id for m in result.matches] == [4, 3, 2, 1]
    assert result.duplicate == both


def test_audit_payload() -> None:
    result = _find(_demand(), [_task(task_id=42)])

    payload = result.audit_payload()

    assert payload["action"] == "duplicate_found"
    assert payload["new_value"]["task_id"] == 42
    assert payload["new_value"]["criteria"] == ["same_brand_type_supplier", "similar_title"]
    assert _find(_demand(), []).audit_payload()["action"] == "no_duplicate"
