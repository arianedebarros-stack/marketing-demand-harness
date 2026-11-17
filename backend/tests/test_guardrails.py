"""AC03 — o harness não deixa o LLM inventar dados (SPEC §8.2, D10, D27)."""

from typing import Any

import pytest

from app.core.config import AppConfig, load_app_config
from app.engines.guardrails import GuardrailEvent, apply_guardrails
from app.schemas.demand import FieldOrigin
from app.schemas.llm import LLMInterpretation

CONFIG: AppConfig = load_app_config()


def _interp(
    extracted: dict[str, Any] | None = None,
    type_: str = "Arte",
    confidence: float = 0.9,
    **extra: Any,
) -> LLMInterpretation:
    return LLMInterpretation.model_validate(
        {
            "classification": {"type": type_, "confidence": confidence},
            "extracted": extracted or {},
            **extra,
        }
    )


def _run(
    extracted: dict[str, Any],
    text: str,
    origin: dict[str, FieldOrigin] | None = None,
    **kwargs: Any,
) -> tuple[dict[str, str], list[GuardrailEvent]]:
    result = apply_guardrails(
        _interp(extracted, **kwargs),
        requester_text=text,
        config=CONFIG,
        field_origin=origin or {},
    )
    return result.interpretation.extracted.provided(), result.events


def _reasons(events: list[GuardrailEvent]) -> dict[str, str]:
    return {e.field: e.reason for e in events}


# --- Preço e números (D10) --------------------------------------------------------------


def test_invented_price_is_discarded() -> None:
    kept, events = _run({"price": "R$ 19,90"}, "Faz uma arte da Construjá para amanhã.")

    assert "price" not in kept
    assert _reasons(events) == {"price": "number_not_in_text"}


def test_price_with_digits_in_text_is_kept() -> None:
    kept, events = _run({"price": "R$ 19,90"}, "Cimento por 19,90 o saco.")

    assert kept["price"] == "R$ 19,90"
    assert events == []


def test_price_digits_must_match_not_just_exist() -> None:
    """D10: '1080x1350' no texto não autoriza um preço inventado."""
    kept, events = _run({"price": "R$ 13,50"}, "Feed 1080x1350 da Construjá.")

    assert "price" not in kept
    assert _reasons(events) == {"price": "number_not_in_text"}


def test_price_from_attachment_is_kept() -> None:
    kept, _ = _run({"price": "Conforme planilha anexada"}, "Os preços estão na planilha anexada.")
    assert kept["price"] == "Conforme planilha anexada"

    kept, _ = _run({"price": "Conforme tabela"}, "Segue a tabela de preços.")
    assert kept["price"] == "Conforme tabela"


def test_price_without_digits_needs_attachment_mention() -> None:
    kept, events = _run({"price": "Conforme planilha anexada"}, "Faz promoção da Krona.")

    assert "price" not in kept
    assert _reasons(events) == {"price": "number_not_in_text"}


def test_price_with_digits_is_not_saved_by_attachment_mention() -> None:
    """D27: com dígitos, o valor precisa estar no texto, mesmo havendo planilha."""
    kept, _ = _run({"price": "R$ 10,00"}, "Os preços estão na planilha.")

    assert "price" not in kept


@pytest.mark.parametrize("field", ["quantity", "budget", "participants_count"])
def test_numeric_fields_need_their_digits_in_text(field: str) -> None:
    kept, events = _run({field: "500"}, "Evento com 500 pessoas e verba de 500.")
    assert kept[field] == "500"
    assert events == []

    kept, events = _run({field: "300"}, "Evento com muita gente.")
    assert field not in kept
    assert _reasons(events) == {field: "number_not_in_text"}


def test_numeric_fields_do_not_get_attachment_exception() -> None:
    kept, _ = _run({"quantity": "Conforme planilha"}, "Quantidades na planilha.")

    assert "quantity" not in kept


# --- Produto ----------------------------------------------------------------------------


def test_product_with_word_in_text_is_kept() -> None:
    kept, events = _run({"product": "Cimento CP-II"}, "Arte do cimento da Construjá.")

    assert kept["product"] == "Cimento CP-II"
    assert events == []


def test_invented_product_is_discarded() -> None:
    kept, events = _run({"product": "Torneira Docol"}, "Faz uma arte da Construjá.")

    assert "product" not in kept
    assert _reasons(events) == {"product": "product_not_in_text"}


def test_product_short_words_do_not_count() -> None:
    """Só palavras com 4+ letras contam ('da', 'kit' não autorizam)."""
    kept, _ = _run({"product": "Kit da Tigre"}, "Arte do kit da loja.")

    assert "product" not in kept


def test_product_from_attachment_is_kept() -> None:
    kept, _ = _run({"product": "Conforme planilha anexada"}, "São 3 produtos do anexo.")

    assert kept["product"] == "Conforme planilha anexada"


def test_product_match_ignores_accents_and_case() -> None:
    kept, _ = _run({"product": "Argamassa Colante"}, "arte da ARGAMASSA para lojistas")

    assert kept["product"] == "Argamassa Colante"


# --- Datas ------------------------------------------------------------------------------


def test_date_with_temporal_reference_is_kept() -> None:
    kept, events = _run({"deadline": "2026-10-20"}, "Arte para amanhã.")

    assert kept["deadline"] == "2026-10-20"
    assert events == []


@pytest.mark.parametrize(
    "text", ["Arte para sexta-feira.", "Entrega 25/10.", "Até 2026-10-30.", "Dia 5 de novembro."]
)
def test_temporal_references_accepted(text: str) -> None:
    kept, _ = _run({"deadline": "2026-10-30"}, text)

    assert kept["deadline"] == "2026-10-30"


def test_date_without_temporal_reference_is_discarded() -> None:
    """'urgente' não é prazo."""
    kept, events = _run({"deadline": "2026-10-20"}, "Preciso de uma arte urgente.")

    assert "deadline" not in kept
    assert _reasons(events) == {"deadline": "no_temporal_reference"}


@pytest.mark.parametrize("value", ["amanhã", "20/10/2026", "2026-02-30", "2026-10-20T18:00"])
def test_non_iso_or_impossible_date_is_discarded(value: str) -> None:
    kept, events = _run({"deadline": value}, "Arte para amanhã.")

    assert "deadline" not in kept
    assert _reasons(events) == {"deadline": "invalid_date"}


@pytest.mark.parametrize("field", ["shoot_date", "event_date"])
def test_all_date_fields_are_checked(field: str) -> None:
    kept, events = _run({field: "2026-11-02"}, "Vídeo na loja.")

    assert field not in kept
    assert _reasons(events) == {field: "no_temporal_reference"}


def test_validity_needs_temporal_reference() -> None:
    """D27: vigência inventada também é descartada (não precisa ser ISO)."""
    kept, _ = _run({"validity": "Até 30/10"}, "A promoção vale até 30/10.")
    assert kept["validity"] == "Até 30/10"

    kept, events = _run({"validity": "2026-10-30"}, "Faz promoção da Krona.")
    assert "validity" not in kept
    assert _reasons(events) == {"validity": "no_temporal_reference"}


# --- Marca ------------------------------------------------------------------------------


def test_unknown_brand_is_discarded() -> None:
    kept, events = _run({"brand": "MegaObras"}, "Arte da MegaObras.")

    assert "brand" not in kept
    assert _reasons(events) == {"brand": "unknown_brand"}


def test_supplier_as_brand_is_discarded() -> None:
    kept, events = _run({"brand": "Krona", "supplier": "Krona"}, "Arte da Krona.")

    assert "brand" not in kept
    assert kept["supplier"] == "Krona"
    assert _reasons(events) == {"brand": "unknown_brand"}


def test_brand_is_matched_without_accent_and_canonicalized() -> None:
    kept, events = _run({"brand": "CONSTRUJA"}, "arte da construja")

    assert kept["brand"] == "Construjá"
    assert [(e.field, e.reason, e.replacement) for e in events] == [
        ("brand", "brand_canonicalized", "Construjá")
    ]


# --- Tipo e confiança -------------------------------------------------------------------


def test_unknown_type_becomes_outro() -> None:
    result = apply_guardrails(
        _interp(type_="Mágica"), requester_text="x", config=CONFIG, field_origin={}
    )

    assert result.interpretation.classification.type == "Outro"
    assert [(e.field, e.reason, e.value, e.replacement) for e in result.events] == [
        ("task_type", "unknown_type", "Mágica", "Outro")
    ]


def test_type_is_matched_without_accent() -> None:
    result = apply_guardrails(
        _interp(type_="video"), requester_text="x", config=CONFIG, field_origin={}
    )

    assert result.interpretation.classification.type == "Vídeo"


@pytest.mark.parametrize(("raw", "clamped"), [(1.7, 1.0), (-0.2, 0.0)])
def test_confidence_is_clamped(raw: float, clamped: float) -> None:
    result = apply_guardrails(
        _interp(confidence=raw), requester_text="x", config=CONFIG, field_origin={}
    )

    assert result.interpretation.classification.confidence == clamped
    assert _reasons(result.events) == {"classification_confidence": "confidence_clamped"}


# --- Qualquer campo ---------------------------------------------------------------------


def test_unknown_keys_are_ignored_and_reported() -> None:
    kept, events = _run(
        {"brand": "Ferjá", "cor_favorita": "azul", "priority": "Crítica"}, "Arte da Ferjá."
    )

    assert kept == {"brand": "Ferjá"}
    assert _reasons(events) == {"cor_favorita": "unknown_field", "priority": "unknown_field"}


def test_manager_field_is_never_overwritten() -> None:
    kept, events = _run(
        {"objective": "Vender mais", "brand": "Ferjá"},
        "Arte da Ferjá para vender mais.",
        origin={"objective": FieldOrigin.MANAGER, "brand": FieldOrigin.LLM},
    )

    assert kept == {"brand": "Ferjá"}
    assert _reasons(events) == {"objective": "manager_field"}


def test_valid_interpretation_passes_untouched() -> None:
    interp = _interp(
        {
            "brand": "Construjá",
            "supplier": "Krona",
            "format": "Feed",
            "dimensions": "1080x1350",
            "product": "Conforme planilha anexada",
            "price": "Conforme planilha anexada",
            "validity": "2026-10-23",
            "deadline": "2026-10-20",
        },
        is_promotional=True,
        published_error=True,
        dependencies=[{"dependency": "Aprovação de preço", "owner": "Compras"}],
        files=["Planilha de preços"],
    )
    text = (
        "Preciso de um feed 1080x1350 da Construjá para divulgar a promoção Krona amanhã. "
        "Os produtos e preços estão na planilha anexada e a promoção vale até sexta."
    )

    result = apply_guardrails(interp, requester_text=text, config=CONFIG, field_origin={})

    assert result.events == []
    assert result.interpretation == interp
    assert result.interpretation.published_error is True


def test_input_is_not_mutated() -> None:
    interp = _interp({"price": "R$ 5", "extra": 1}, type_="Mágica", confidence=2)

    apply_guardrails(interp, requester_text="nada", config=CONFIG, field_origin={})

    assert interp.extracted.price == "R$ 5"
    assert interp.extracted.unknown_keys() == {"extra": 1}
    assert interp.classification.type == "Mágica"
    assert interp.classification.confidence == 2


def test_event_audit_payload() -> None:
    _, events = _run({"price": "R$ 9"}, "sem números")

    assert events[0].audit_payload() == {
        "action": "guardrail_discard",
        "previous_value": {"field": "price", "value": "R$ 9"},
        "new_value": {"reason": "number_not_in_text", "replacement": None},
    }
