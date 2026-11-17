"""AC12 — título e briefing final estruturado (SPEC §8.9, D15, D30)."""

from datetime import date
from typing import Any

import pytest

from app.core.config import AppConfig, load_app_config
from app.engines.briefing import build_briefing, build_title
from app.schemas.demand import Demand, Dependency, FieldOrigin, RequiredFile

CONFIG: AppConfig = load_app_config()
CONSTRUJA = CONFIG.brands["construja"]


def _demand(**fields: Any) -> Demand:
    return Demand(requester="Ana", department="Comercial", **fields)


def _case_06(**overrides: Any) -> Demand:
    """Caso 06 depois de regras, validação e triagem."""
    fields: dict[str, Any] = {
        "task_type": "Arte",
        "is_promotional": True,
        "brand": "Construjá",
        "supplier": "Krona",
        "objective": "Divulgar promoção Krona",
        "audience": CONSTRUJA.audience,
        "message_tone": CONSTRUJA.tone,
        "channel": "Instagram",
        "format": "Feed",
        "dimensions": "1080 × 1350 px",
        "product": "3 produtos da planilha anexada",
        "price": "Conforme planilha anexada",
        "validity": "2026-11-20",
        "cta": CONSTRUJA.mandatory_cta,
        "deadline": date(2026, 11, 18),
        "priority": "Alta",
        "priority_score": 76.5,
        "assigned_to": "designer-a",
        "approver": "Gestor de Marketing",
        "dependencies": [Dependency(dependency="Aprovação de preço", owner="Compras")],
        "required_files": [
            RequiredFile(name="Planilha de preços", origin=FieldOrigin.LLM),
            RequiredFile(name="Logo Krona", origin=FieldOrigin.RULE),
            RequiredFile(name="Imagens dos produtos", origin=FieldOrigin.RULE),
        ],
        "briefing_score": 100,
    }
    fields.update(overrides)
    return _demand(**fields)


# --- Título --------------------------------------------------------------------------------


def test_title_promotion_with_supplier() -> None:
    """AC12: exemplo da §8.9."""
    assert build_title(_case_06(), config=CONFIG) == "Arte | Promoção Krona | Construjá"


def test_title_prefers_campaign() -> None:
    demand = _case_06(campaign="Black Friday 2026")
    assert build_title(demand, config=CONFIG) == "Arte | Black Friday 2026 | Construjá"


def test_title_supplier_without_promotion_uses_objective() -> None:
    """D30: "Promoção <fornecedor>" só quando a demanda é promocional."""
    demand = _demand(
        task_type="Vídeo", brand="Ferjá", supplier="Krona", objective="Mostrar o uso do produto"
    )
    assert build_title(demand, config=CONFIG) == "Vídeo | Mostrar o uso do produto | Ferjá"


def test_title_short_objective_takes_first_words() -> None:
    """D30: objetivo curto = primeiras N palavras (N em config), sem reticências."""
    demand = _demand(
        task_type="Arte",
        brand="Construjá",
        objective="Divulgar a  nova linha de tintas premium para lojistas",
    )

    max_words = CONFIG.task_types.title.objective_max_words
    assert max_words == 6
    assert (
        build_title(demand, config=CONFIG) == "Arte | Divulgar a nova linha de tintas | Construjá"
    )


def test_title_skips_empty_parts() -> None:
    assert build_title(_demand(task_type="Arte", brand="Ferjá"), config=CONFIG) == "Arte | Ferjá"
    assert build_title(_demand(task_type="Relatório"), config=CONFIG) == "Relatório"


def test_title_ignores_blank_campaign() -> None:
    assert (
        build_title(_case_06(campaign="  "), config=CONFIG) == "Arte | Promoção Krona | Construjá"
    )


# --- Briefing final ------------------------------------------------------------------------


def test_briefing_template_case_06() -> None:
    """AC12: uma linha "RÓTULO: valor" por campo, na ordem da §8.9 (D15)."""
    briefing = build_briefing(_case_06(), config=CONFIG)

    assert briefing == "\n".join(
        [
            "TÍTULO: Arte | Promoção Krona | Construjá",
            "OBJETIVO: Divulgar promoção Krona",
            "MARCA: Construjá",
            f"PÚBLICO: {CONSTRUJA.audience}",
            "CANAL: Instagram",
            "FORMATO: Feed",
            "DIMENSÃO: 1080 × 1350 px",
            f"MENSAGEM E TOM: {CONSTRUJA.tone}",
            "PRODUTOS: 3 produtos da planilha anexada",
            "PREÇOS: Conforme planilha anexada",
            "VIGÊNCIA: 20/11/2026",
            f"CTA: {CONSTRUJA.mandatory_cta}",
            "PRAZO: 18/11/2026",
            "PRIORIDADE: Alta",
            "RESPONSÁVEL: Designer A",
            "APROVAÇÃO: Gestor de Marketing",
            "DEPENDÊNCIAS: Aprovação de preço (Compras, Pendente)",
            "ARQUIVOS: Planilha de preços; Logo Krona; Imagens dos produtos",
            "BRIEFING SCORE: 100%",
        ]
    )


def test_empty_fields_do_not_appear() -> None:
    briefing = build_briefing(_demand(task_type="Arte", brand="Ferjá"), config=CONFIG)

    assert briefing.splitlines() == [
        "TÍTULO: Arte | Ferjá",
        "MARCA: Ferjá",
        "BRIEFING SCORE: 0%",
    ]


def test_blank_text_does_not_appear() -> None:
    briefing = build_briefing(_case_06(cta="   "), config=CONFIG)
    assert not any(line.startswith("CTA:") for line in briefing.splitlines())


def test_validity_that_is_not_iso_appears_as_is() -> None:
    briefing = build_briefing(_case_06(validity="enquanto durar o estoque"), config=CONFIG)
    assert "VIGÊNCIA: enquanto durar o estoque" in briefing.splitlines()


def test_unknown_assignee_appears_as_id() -> None:
    briefing = build_briefing(_case_06(assigned_to="freela-x"), config=CONFIG)
    assert "RESPONSÁVEL: freela-x" in briefing.splitlines()


def test_multiple_dependencies() -> None:
    demand = _case_06(
        dependencies=[
            Dependency(dependency="Aprovação de preço", owner="Compras"),
            Dependency(dependency="Fotos do produto", owner="Krona", status="Resolvida"),
        ]
    )

    lines = build_briefing(demand, config=CONFIG).splitlines()

    assert (
        "DEPENDÊNCIAS: Aprovação de preço (Compras, Pendente); Fotos do produto (Krona, Resolvida)"
        in lines
    )


def test_title_can_be_passed_in() -> None:
    """O pipeline pode reaproveitar o título já calculado (ex.: o da tarefa existente)."""
    briefing = build_briefing(_case_06(), config=CONFIG, title="Arte | Outro título | Construjá")
    assert briefing.splitlines()[0] == "TÍTULO: Arte | Outro título | Construjá"


# --- Campos próprios do tipo (D30) ---------------------------------------------------------


def test_type_fields_after_cta_before_deadline() -> None:
    demand = _demand(
        task_type="Vídeo",
        brand="Ferjá",
        objective="Mostrar o uso do produto",
        format="Reels",
        duration="30 segundos",
        concept="Antes e depois",
        location="Loja Centro",
        participants="Vendedor",
        shoot_date=date(2026, 11, 25),
        deadline=date(2026, 12, 1),
    )

    lines = build_briefing(demand, config=CONFIG).splitlines()

    assert lines == [
        "TÍTULO: Vídeo | Mostrar o uso do produto | Ferjá",
        "OBJETIVO: Mostrar o uso do produto",
        "MARCA: Ferjá",
        "FORMATO: Reels",
        "DURAÇÃO: 30 segundos",
        "CONCEITO: Antes e depois",
        "LOCAL: Loja Centro",
        "PARTICIPANTES: Vendedor",
        "DATA DA GRAVAÇÃO: 25/11/2026",
        "PRAZO: 01/12/2026",
        "BRIEFING SCORE: 0%",
    ]


def test_type_fields_already_in_main_list_are_not_repeated() -> None:
    """Banner Site exige dimensions, que já está na lista da §8.9."""
    demand = _demand(task_type="Banner Site", dimensions="1920x600", headline="Ofertas")

    lines = build_briefing(demand, config=CONFIG).splitlines()

    assert sum(line.startswith("DIMENSÃO:") for line in lines) == 1
    assert "HEADLINE: Ofertas" in lines


def test_fields_of_other_types_are_not_included() -> None:
    """Só entram os obrigatórios do tipo da demanda."""
    demand = _demand(task_type="Arte", budget="R$ 5.000", location="Loja Centro")
    briefing = build_briefing(demand, config=CONFIG)

    assert "ORÇAMENTO" not in briefing
    assert "LOCAL" not in briefing


@pytest.mark.parametrize("task_type", sorted(CONFIG.task_types.types))
def test_every_type_field_has_a_label(task_type: str) -> None:
    """Todo campo obrigatório de config/ aparece no briefing com rótulo próprio."""
    rule = CONFIG.task_types.types[task_type]
    fields: dict[str, Any] = {f: "x" for f in [*rule.required, *rule.promo_required]}
    for name in ("shoot_date", "event_date"):
        if name in fields:
            fields[name] = date(2026, 12, 1)

    demand = _demand(task_type=task_type, is_promotional=True, **fields)
    lines = build_briefing(demand, config=CONFIG).splitlines()

    assert len(lines) == len(set(lines))
    labels = [line.split(":", 1)[0] for line in lines]
    assert all(label.isupper() for label in labels)
    # título + cada campo + score
    assert len(lines) == 1 + len(fields) + 1


def test_unknown_type_has_no_type_fields() -> None:
    demand = _demand(task_type="Holograma", duration="30 segundos")
    assert build_briefing(demand, config=CONFIG).splitlines() == [
        "TÍTULO: Holograma",
        "BRIEFING SCORE: 0%",
    ]


def test_input_demand_is_not_mutated() -> None:
    demand = _case_06()
    snapshot = demand.model_copy(deep=True)

    build_title(demand, config=CONFIG)
    build_briefing(demand, config=CONFIG)

    assert demand == snapshot
