"""AC04 e AC05 — Validator: faltantes e perguntas (SPEC §8.4, §7, D29)."""

from datetime import date
from typing import Any

import pytest

from app.core.config import AppConfig, load_app_config
from app.engines.validator import QUESTIONS, TYPE_FIELD, validate_demand
from app.schemas.demand import Demand, FieldOrigin

CONFIG: AppConfig = load_app_config()
UNIVERSAL = CONFIG.task_types.universal_required


def _demand(**fields: Any) -> Demand:
    fields.setdefault("classification_confidence", 0.95)
    return Demand(requester="Ana", department="Comercial", **fields)


def _complete_arte_promo(**overrides: Any) -> Demand:
    """Caso 02 depois das regras: Arte promocional com todos os campos."""
    fields: dict[str, Any] = {
        "task_type": "Arte",
        "is_promotional": True,
        "brand": "Construjá",
        "supplier": "Krona",
        "objective": "Divulgar promoção Krona",
        "audience": "Lojistas",
        "message_tone": "Comercial",
        "channel": "Instagram",
        "format": "Feed",
        "product": "Conforme planilha anexada",
        "price": "Conforme planilha anexada",
        "validity": "2026-11-20",
        "deadline": date(2026, 11, 18),
    }
    fields.update(overrides)
    return _demand(**fields)


def _asked(demand: Demand) -> list[list[str]]:
    return [q.fields for q in validate_demand(demand, config=CONFIG).questions]


# --- AC04 · faltantes ----------------------------------------------------------------------


def test_missing_fields_arte_promo() -> None:
    """AC04: Arte promocional exige universais + canal/formato + produto/preço/vigência."""
    demand = _demand(task_type="Arte", is_promotional=True, supplier="Krona")

    result = validate_demand(demand, config=CONFIG)

    assert result.required == [
        "requester",
        "brand",
        "objective",
        "audience",
        "message_tone",
        "deadline",
        "channel",
        "format",
        "product",
        "price",
        "validity",
    ]
    assert result.missing == [f for f in result.required if f != "requester"]
    assert result.ready is False


def test_non_promotional_arte_does_not_require_promo_fields() -> None:
    result = validate_demand(_demand(task_type="Arte"), config=CONFIG)
    assert not {"product", "price", "validity"} & set(result.required)


def test_required_comes_from_config_type() -> None:
    result = validate_demand(_demand(task_type="Vídeo"), config=CONFIG)
    assert result.required == [*UNIVERSAL, *CONFIG.task_types.types["Vídeo"].required]


def test_complete_demand_is_ready() -> None:
    result = validate_demand(_complete_arte_promo(), config=CONFIG)

    assert result.missing == []
    assert result.questions == []
    assert result.score.score == 100
    assert result.score.band == "Pronto para produção"
    assert result.ready is True


def test_blank_text_counts_as_missing() -> None:
    result = validate_demand(_complete_arte_promo(objective="   "), config=CONFIG)

    assert result.missing == ["objective"]
    assert result.ready is False


# --- AC05 · perguntas ----------------------------------------------------------------------


def test_questions_only_missing() -> None:
    """AC05: só os faltantes são perguntados; nenhum campo preenchido aparece."""
    demand = _complete_arte_promo(objective=None, validity=None)

    result = validate_demand(demand, config=CONFIG)

    asked = {f for q in result.questions for f in q.fields}
    assert asked == {"objective", "validity"}
    assert [q.text for q in result.questions] == [
        QUESTIONS[("objective",)],
        QUESTIONS[("validity",)],
    ]


def test_case_01_questions() -> None:
    """Caso 01 ("Faz uma arte da Krona."): marca, objetivo, canal/formato, produtos/preços,
    vigência e prazo — sem público e tom, que virão da marca."""
    demand = _demand(task_type="Arte", supplier="Krona", is_promotional=True)

    assert _asked(demand) == [
        ["brand"],
        ["objective"],
        ["channel", "format"],
        ["product", "price"],
        ["validity"],
        ["deadline"],
    ]


def test_missing_brand_skips_audience_and_tone_questions() -> None:
    demand = _complete_arte_promo(brand=None, audience=None, message_tone=None)

    result = validate_demand(demand, config=CONFIG)

    assert result.missing == ["brand", "audience", "message_tone"]
    assert [q.fields for q in result.questions] == [["brand"]]


def test_audience_asked_when_brand_known() -> None:
    demand = _complete_arte_promo(audience=None)
    assert _asked(demand) == [["audience"]]


def test_channel_and_format_grouped() -> None:
    demand = _complete_arte_promo(channel=None, format=None)

    result = validate_demand(demand, config=CONFIG)

    assert len(result.questions) == 1
    assert result.questions[0].fields == ["channel", "format"]
    assert result.questions[0].text == QUESTIONS[("channel", "format")]


def test_product_and_price_grouped() -> None:
    demand = _complete_arte_promo(product=None, price=None)
    assert _asked(demand) == [["product", "price"]]


@pytest.mark.parametrize(
    ("missing", "expected"),
    [("channel", ["channel"]), ("format", ["format"]), ("product", ["product"])],
)
def test_partial_group_asks_only_missing_field(missing: str, expected: list[str]) -> None:
    result = validate_demand(_complete_arte_promo(**{missing: None}), config=CONFIG)

    assert [q.fields for q in result.questions] == [expected]
    assert result.questions[0].text == QUESTIONS[tuple(expected)]


def test_every_configured_field_has_a_question() -> None:
    """Todo campo obrigatório em config/ tem texto de pergunta (individual)."""
    fields = set(UNIVERSAL) | {TYPE_FIELD}
    for rule in CONFIG.task_types.types.values():
        fields |= set(rule.required) | set(rule.promo_required)

    missing_texts = sorted(f for f in fields if (f,) not in QUESTIONS)
    assert missing_texts == []
    assert all(text.strip() for text in QUESTIONS.values())


@pytest.mark.parametrize("task_type", sorted(CONFIG.task_types.types))
def test_empty_demand_of_any_type_asks_only_missing(task_type: str) -> None:
    result = validate_demand(_demand(task_type=task_type, is_promotional=True), config=CONFIG)

    asked = [f for q in result.questions for f in q.fields]
    assert len(asked) == len(set(asked))
    assert set(asked) <= set(result.missing)
    assert "requester" not in asked


# --- Tipo incerto (§7, D29) ----------------------------------------------------------------


def test_missing_type_asks_only_type() -> None:
    demand = _demand(task_type=None, brand="Construjá", objective="Divulgar")

    result = validate_demand(demand, config=CONFIG)

    assert result.needs_type_confirmation is True
    assert result.missing == [TYPE_FIELD]
    assert [q.fields for q in result.questions] == [[TYPE_FIELD]]
    assert result.required == [*UNIVERSAL, TYPE_FIELD]
    # requester, brand, objective preenchidos de 7 (6 universais + tipo)
    assert result.score.score == 43
    assert result.ready is False


def test_low_confidence_type_asks_only_type() -> None:
    """Confiança < 0,70 sem confirmação: só confirmar o tipo; o score nunca chega a 100%."""
    demand = _complete_arte_promo(classification_confidence=0.5)

    result = validate_demand(demand, config=CONFIG)

    assert result.needs_type_confirmation is True
    assert result.missing == [TYPE_FIELD]
    assert result.score.filled == len(UNIVERSAL)
    assert result.score.total == len(UNIVERSAL) + 1
    assert result.score.score < 100
    assert result.ready is False


def test_confidence_at_threshold_is_accepted() -> None:
    threshold = CONFIG.task_types.classification_threshold
    result = validate_demand(
        _complete_arte_promo(classification_confidence=threshold), config=CONFIG
    )
    assert result.needs_type_confirmation is False
    assert result.ready is True


def test_confirmed_type_ignores_low_confidence() -> None:
    demand = _complete_arte_promo(classification_confidence=0.3, type_confirmed=True)
    assert validate_demand(demand, config=CONFIG).ready is True


def test_manager_type_ignores_low_confidence() -> None:
    demand = _complete_arte_promo(
        classification_confidence=0.3, field_origin={"task_type": FieldOrigin.MANAGER}
    )
    assert validate_demand(demand, config=CONFIG).ready is True


def test_unknown_type_needs_confirmation() -> None:
    demand = _complete_arte_promo(task_type="Holograma", type_confirmed=True)
    assert validate_demand(demand, config=CONFIG).missing == [TYPE_FIELD]


def test_input_demand_is_not_mutated() -> None:
    demand = _demand(task_type="Arte", is_promotional=True)
    snapshot = demand.model_copy(deep=True)

    validate_demand(demand, config=CONFIG)

    assert demand == snapshot
