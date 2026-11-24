"""AC10 — dependências explícitas, bloqueio e resolução (SPEC §8.7, D03, D34)."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.core.config import load_app_config
from app.engines.dependency import (
    is_blocked,
    merge_dependencies,
    pending_dependencies,
    resolve_dependency,
)
from app.llm.fake_client import FakeLLMClient
from app.schemas.demand import Demand, Dependency
from app.services.pipeline import process_message

CONFIG = load_app_config()
TZ = ZoneInfo("America/Sao_Paulo")
NOW = datetime(2026, 10, 19, 9, 0, tzinfo=TZ)


def _dep(text: str, owner: str = "Compras", status: str = "Pendente") -> Dependency:
    return Dependency.model_validate({"dependency": text, "owner": owner, "status": status})


def _pipeline(*messages: str) -> Demand:
    demand = Demand(requester="Ana", department="Comercial")
    history: list[str] = []
    for message in messages:
        history.append(message)
        demand = process_message(
            demand, history, llm=FakeLLMClient(), config=CONFIG, now=NOW, tz=TZ
        ).demand
    return demand


# --- AC10 · só dependências explícitas -----------------------------------------------------


def test_explicit_dependency_blocks_task() -> None:
    """AC10 (caso 06): a dependência citada vira pendência e a tarefa nasce bloqueada."""
    demand = _pipeline(
        "Preciso de uma arte da Krona para amanhã.",
        "Construjá",
        "Instagram feed. São 3 produtos da planilha anexada. Promoção válida até sexta. "
        "Ainda aguardando aprovação de preço por Compras.",
    )

    assert demand.dependencies == [_dep("Aprovação de preço", "Compras")]
    assert is_blocked(demand.dependencies) is True


def test_no_dependency_without_explicit_mention() -> None:
    """AC10: preço na planilha não é dependência; nada é inventado."""
    demand = _pipeline(
        "Preciso de um feed 1080x1350 da Construjá para divulgar a promoção Krona amanhã. "
        "Os produtos e preços estão na planilha anexada e a promoção vale até sexta."
    )

    assert demand.dependencies == []
    assert is_blocked(demand.dependencies) is False


def test_dependency_repeated_across_messages_is_kept_once() -> None:
    demand = _pipeline(
        "Arte da Construjá. Aguardando aprovação de preço por Compras.",
        "Ainda aguardando aprovação de preço por Compras.",
    )
    assert demand.dependencies == [_dep("Aprovação de preço", "Compras")]


# --- Merge (deduplicação por texto normalizado) ---------------------------------------------


def test_merge_adds_new_and_keeps_existing_status() -> None:
    current = [_dep("Aprovação de preço", status="Resolvida")]
    new = [_dep("aprovação de PREÇO"), _dep("Fotos do produto", "Krona")]

    merged = merge_dependencies(current, new)

    assert merged == [
        _dep("Aprovação de preço", status="Resolvida"),
        _dep("Fotos do produto", "Krona"),
    ]


@pytest.mark.parametrize(
    "variant",
    ["Aprovação de preço.", "  aprovacao   de preco ", "APROVAÇÃO DE PREÇO!", "Aprovação de preço"],
)
def test_merge_ignores_accents_case_spaces_and_punctuation(variant: str) -> None:
    merged = merge_dependencies([_dep("Aprovação de preço")], [_dep(variant)])
    assert merged == [_dep("Aprovação de preço")]


def test_merge_dedupes_inside_new_list() -> None:
    merged = merge_dependencies([], [_dep("Fotos"), _dep("fotos", "Krona")])
    assert merged == [_dep("Fotos")]


def test_merge_does_not_mutate_inputs() -> None:
    current = [_dep("A")]
    merge_dependencies(current, [_dep("B")])
    assert current == [_dep("A")]


# --- Bloqueio e resolução (D03) ------------------------------------------------------------


def test_blocked_only_with_pending() -> None:
    assert is_blocked([]) is False
    assert is_blocked([_dep("A", status="Resolvida")]) is False
    assert is_blocked([_dep("A", status="Resolvida"), _dep("B")]) is True
    assert pending_dependencies([_dep("A", status="Resolvida"), _dep("B")]) == [_dep("B")]


def test_resolving_last_pending_unblocks() -> None:
    deps = [_dep("Aprovação de preço"), _dep("Fotos", "Krona")]

    first = resolve_dependency(deps, 0)
    assert first.dependencies[0].status == "Resolvida"
    assert first.blocked is True
    assert first.changed is True

    second = resolve_dependency(first.dependencies, 1)
    assert second.blocked is False
    assert [d.status for d in second.dependencies] == ["Resolvida", "Resolvida"]
    assert deps[0].status == "Pendente"  # entrada não é alterada


def test_resolving_twice_is_a_no_op() -> None:
    result = resolve_dependency([_dep("A", status="Resolvida")], 0)

    assert result.changed is False
    assert result.blocked is False


@pytest.mark.parametrize("index", [-1, 1, 5])
def test_invalid_index_raises(index: int) -> None:
    with pytest.raises(IndexError):
        resolve_dependency([_dep("A")], index)


def test_resolution_audit_payload() -> None:
    result = resolve_dependency([_dep("Aprovação de preço"), _dep("Fotos", "Krona")], 0)

    assert result.audit_payload() == {
        "action": "dependency_resolved",
        "previous_value": {
            "index": 0,
            "dependency": "Aprovação de preço",
            "owner": "Compras",
            "status": "Pendente",
        },
        "new_value": {"index": 0, "status": "Resolvida", "blocked": True},
    }
