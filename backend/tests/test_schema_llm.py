import pytest
from pydantic import ValidationError

from app.schemas.demand import EXTRACTABLE_FIELDS
from app.schemas.llm import LLMInterpretation

SPEC_EXAMPLE = {
    "classification": {"type": "Arte", "confidence": 0.96},
    "extracted": {"brand": "Construjá", "supplier": "Krona", "deadline": "2026-10-20"},
    "is_promotional": True,
    "published_error": False,
    "dependencies": [
        {"dependency": "Aprovação de preço", "owner": "Compras", "status": "Pendente"}
    ],
    "files": ["Planilha de preços"],
}


def test_parses_spec_example() -> None:
    interp = LLMInterpretation.model_validate(SPEC_EXAMPLE)

    assert interp.classification.type == "Arte"
    assert interp.classification.confidence == 0.96
    assert interp.extracted.brand == "Construjá"
    assert interp.extracted.supplier == "Krona"
    assert interp.extracted.deadline == "2026-10-20"
    assert interp.is_promotional is True
    assert interp.dependencies[0].owner == "Compras"
    assert interp.files == ["Planilha de preços"]


def test_optional_parts_default_empty() -> None:
    interp = LLMInterpretation.model_validate(
        {"classification": {"type": "Outro", "confidence": 0.4}, "extracted": {}}
    )

    assert interp.is_promotional is False
    assert interp.published_error is False
    assert interp.dependencies == []
    assert interp.files == []
    assert interp.extracted.provided() == {}


def test_classification_is_required() -> None:
    with pytest.raises(ValidationError):
        LLMInterpretation.model_validate({"extracted": {}})


def test_raw_values_are_kept_for_guardrails() -> None:
    """Tipo fora da lista, confiança fora de [0,1] e datas não ISO são tratados nos guardrails
    (§8.2), não rejeitados aqui: o schema só garante a forma."""
    interp = LLMInterpretation.model_validate(
        {
            "classification": {"type": "Mágica", "confidence": 1.7},
            "extracted": {"deadline": "amanhã", "price": 19.9, "quantity": 500},
        }
    )

    assert interp.classification.type == "Mágica"
    assert interp.classification.confidence == 1.7
    assert interp.extracted.deadline == "amanhã"
    assert interp.extracted.price == "19.9"
    assert interp.extracted.quantity == "500"


def test_unknown_extracted_keys_are_preserved_for_audit() -> None:
    interp = LLMInterpretation.model_validate(
        {
            "classification": {"type": "Arte", "confidence": 0.9},
            "extracted": {"brand": "Ferjá", "cor_favorita": "azul", "priority": "Crítica"},
        }
    )

    assert interp.extracted.provided() == {"brand": "Ferjá"}
    assert interp.extracted.unknown_keys() == {"cor_favorita": "azul", "priority": "Crítica"}


def test_null_values_are_not_considered_provided() -> None:
    interp = LLMInterpretation.model_validate(
        {"classification": {"type": "Arte", "confidence": 0.9}, "extracted": {"price": None}}
    )

    assert interp.extracted.provided() == {}


def test_extracted_fields_match_demand_extractable_fields() -> None:
    from app.schemas.llm import ExtractedFields

    assert set(ExtractedFields.model_fields) == set(EXTRACTABLE_FIELDS)


def test_tool_input_schema_is_generated_from_model() -> None:
    schema = LLMInterpretation.tool_input_schema()

    assert schema["type"] == "object"
    assert set(schema["required"]) == {"classification", "extracted"}
    extracted = schema["properties"]["extracted"]
    assert set(extracted["properties"]) == set(EXTRACTABLE_FIELDS)
    assert "$defs" not in str(schema)  # schema autocontido, sem $ref
