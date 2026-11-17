from datetime import date

import pytest

from app.core.config import load_app_config
from app.llm.base import InterpretationContext, LLMClient
from app.llm.fake_client import FakeLLMClient
from app.schemas.llm import LLMInterpretation

TODAY = date(2026, 10, 19)  # segunda-feira
TOMORROW = "2026-10-20"
NEXT_FRIDAY = "2026-10-23"

CASE_02 = (
    "Preciso de um feed 1080x1350 da Construjá para divulgar a promoção Krona amanhã. "
    "Os produtos e preços estão na planilha anexada e a promoção vale até sexta."
)


def _interpret(
    *messages: str,
    known: dict[str, object] | None = None,
    asked: list[str] | None = None,
    today: date = TODAY,
) -> LLMInterpretation:
    context = InterpretationContext.build(
        load_app_config(),
        today=today,
        messages=list(messages),
        known_fields=known or {},
        asked_fields=asked or [],
    )
    return FakeLLMClient().interpret(context)


def test_fake_implements_interface() -> None:
    client: LLMClient = FakeLLMClient()
    assert client.provider == "fake"


def test_context_carries_spec_inputs() -> None:
    context = InterpretationContext.build(
        load_app_config(), today=TODAY, messages=["oi"], known_fields={}, asked_fields=["brand"]
    )

    assert context.weekday == "segunda-feira"
    assert "Arte" in context.allowed_types
    assert "Construjá" in context.brand_names
    assert "Krona" in context.suppliers
    assert "deadline" in context.possible_fields
    assert context.asked_fields == ["brand"]


# --- Casos 01–04 da SPEC §17 -------------------------------------------------------------


def test_case_01_arte_krona_without_brand() -> None:
    result = _interpret("Faz uma arte da Krona.")

    assert result.classification.type == "Arte"
    assert result.classification.confidence == 0.92
    assert result.extracted.provided() == {"supplier": "Krona"}
    assert result.extracted.brand is None  # fornecedor nunca vai em brand
    assert result.dependencies == []


def test_case_02_complete_request() -> None:
    result = _interpret(CASE_02)

    assert result.classification.type == "Arte"
    assert result.classification.confidence == 0.92
    assert result.is_promotional is True
    assert result.extracted.provided() == {
        "brand": "Construjá",
        "supplier": "Krona",
        "format": "Feed",
        "dimensions": "1080x1350",
        "objective": "Divulgar a promoção Krona",
        "product": "Conforme planilha anexada",
        "price": "Conforme planilha anexada",
        "validity": NEXT_FRIDAY,
        "deadline": TOMORROW,
    }


def test_case_03_same_request_with_ferja() -> None:
    result = _interpret(CASE_02.replace("Construjá", "Ferjá"))

    assert result.extracted.brand == "Ferjá"
    assert result.extracted.supplier == "Krona"


def test_case_04_promotion_without_price() -> None:
    result = _interpret("Faz promoção da Krona.")

    assert result.classification.type == "Arte"
    assert result.classification.confidence == 0.55
    assert result.is_promotional is True
    assert result.extracted.price is None
    assert result.extracted.product is None
    assert result.extracted.supplier == "Krona"
    assert result.extracted.objective == "Divulgar promoção Krona"


# --- Classificação (§12) -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected_type", "confidence"),
    [
        ("Preciso de um banner para o site", "Banner Site", 0.92),
        ("Vamos gravar um vídeo na loja", "Vídeo", 0.92),
        ("Stand para a feira de outubro", "Evento", 0.92),
        ("Quero um folheto impresso", "Material Impresso", 0.92),
        ("Faz um carrossel", "Arte", 0.92),
        ("Um post para o LinkedIn", "Social Media", 0.92),
        ("Nova campanha de verão", "Campanha", 0.92),
        ("Vídeo e arte para a campanha", "Vídeo", 0.80),  # várias regras: vale a primeira
        ("Preciso de um relatório", "Outro", 0.40),
    ],
)
def test_classification_by_keywords(message: str, expected_type: str, confidence: float) -> None:
    result = _interpret(message)

    assert result.classification.type == expected_type
    assert result.classification.confidence == confidence


def test_classification_uses_whole_history() -> None:
    result = _interpret("Preciso de uma peça da Construjá.", "É um vídeo, na verdade.")

    assert result.classification.type == "Vídeo"
    assert result.classification.confidence == 0.80


# --- Extração (§12) ----------------------------------------------------------------------


def test_brand_matching_ignores_accents_and_case() -> None:
    assert _interpret("arte da construja").extracted.brand == "Construjá"
    assert _interpret("arte do GRUPO JA").extracted.brand == "Grupo Já"
    assert _interpret("já te mando a arte").extracted.brand is None


@pytest.mark.parametrize(
    ("message", "channel", "fmt"),
    [
        ("Arte para stories do Instagram", "Instagram", "Stories"),
        ("Arte para o status do WhatsApp", "WhatsApp", None),
        ("Reels no facebook", "Facebook", "Reels"),
        ("Banner no site", "Site", None),
    ],
)
def test_channel_and_format(message: str, channel: str, fmt: str | None) -> None:
    result = _interpret(message)

    assert result.extracted.channel == channel
    assert result.extracted.format == fmt


@pytest.mark.parametrize(
    ("message", "deadline"),
    [
        ("Arte para hoje", "2026-10-19"),
        ("Arte para amanhã", "2026-10-20"),
        ("Arte para quarta-feira", "2026-10-21"),
        ("Arte para segunda", "2026-10-26"),  # D11: próxima ocorrência a partir de amanhã
        ("Arte para 25/10", "2026-10-25"),
        ("Arte para 05/01", "2027-01-05"),  # D11: dd/mm que já passou vai para o ano seguinte
        ("Arte urgente", None),  # "urgente" não é prazo
        ("Arte para 31/02", None),  # data impossível
    ],
)
def test_deadline_expressions(message: str, deadline: str | None) -> None:
    assert _interpret(message).extracted.deadline == deadline


def test_validity_is_extracted_before_deadline() -> None:
    result = _interpret("Arte da promoção válida até 30/10, preciso para sexta.")

    assert result.extracted.validity == "2026-10-30"
    assert result.extracted.deadline == NEXT_FRIDAY


def test_validity_alone_does_not_become_deadline() -> None:
    result = _interpret("A promoção vale até sexta.")

    assert result.extracted.validity == NEXT_FRIDAY
    assert result.extracted.deadline is None


def test_attachment_fills_product_and_price() -> None:
    result = _interpret("São 3 produtos, estão no anexo.")

    assert result.extracted.product == "Conforme planilha anexada"
    assert result.extracted.price == "Conforme planilha anexada"


def test_objective_from_verb() -> None:
    assert _interpret("Arte para lançar a linha Tigre hoje.").extracted.objective == (
        "Lançar a linha Tigre"
    )


@pytest.mark.parametrize(
    ("message", "dependency", "owner"),
    [
        ("Ainda aguardando aprovação de preço por Compras.", "Aprovação de preço", "Compras"),
        ("Depende de validação do Jurídico.", "Validação", "Jurídico"),
        ("Falta aprovação do preço final.", "Aprovação do preço final", "Compras"),
        ("Ainda não aprovado o texto.", "Aprovação de texto", "Não informado"),
    ],
)
def test_explicit_dependencies(message: str, dependency: str, owner: str) -> None:
    result = _interpret(message)

    assert [(d.dependency, d.owner, d.status) for d in result.dependencies] == [
        (dependency, owner, "Pendente")
    ]


def test_no_dependency_without_explicit_mention() -> None:
    assert _interpret(CASE_02).dependencies == []


# --- Memória e resposta a pergunta única --------------------------------------------------


def test_case_06_history_is_interpreted_as_a_whole() -> None:
    result = _interpret(
        "Preciso de uma arte da Krona para amanhã.",
        "Construjá",
        "Instagram feed. São 3 produtos da planilha anexada. Promoção válida até sexta. "
        "Ainda aguardando aprovação de preço por Compras.",
    )

    assert result.classification.type == "Arte"
    assert result.classification.confidence == 0.92
    assert result.is_promotional is True
    assert result.extracted.provided() == {
        "brand": "Construjá",
        "supplier": "Krona",
        "channel": "Instagram",
        "format": "Feed",
        "objective": "Divulgar promoção Krona",
        "product": "Conforme planilha anexada",
        "price": "Conforme planilha anexada",
        "validity": NEXT_FRIDAY,
        "deadline": TOMORROW,
    }
    assert [(d.dependency, d.owner) for d in result.dependencies] == [
        ("Aprovação de preço", "Compras")
    ]


def test_later_message_overrides_earlier_value() -> None:
    result = _interpret("Arte para amanhã.", "Na verdade é para 25/10.")

    assert result.extracted.deadline == "2026-10-25"


def test_whole_answer_is_value_of_single_asked_field() -> None:
    result = _interpret(
        "Faz uma arte da Construjá para amanhã.",
        "Aumentar as vendas de cimento.",
        known={"brand": "Construjá", "deadline": "2026-10-20"},
        asked=["objective"],
    )

    assert result.extracted.objective == "Aumentar as vendas de cimento"


def test_whole_answer_rule_needs_exactly_one_asked_field() -> None:
    result = _interpret(
        "Faz uma arte da Construjá.",
        "Aumentar as vendas de cimento.",
        asked=["objective", "deadline"],
    )

    assert result.extracted.objective is None


def test_whole_answer_rule_ignored_when_something_new_was_extracted() -> None:
    result = _interpret(
        "Faz uma arte.",
        "Ferjá",
        known={},
        asked=["objective"],
    )

    assert result.extracted.brand == "Ferjá"
    assert result.extracted.objective is None
