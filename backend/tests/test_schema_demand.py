from datetime import date
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.demand import (
    DATE_FIELDS,
    EXTRACTABLE_FIELDS,
    Demand,
    Dependency,
    FieldOrigin,
    RequestStatus,
    RequiredFile,
    normalize_dimensions,
)


def _demand(**overrides: object) -> Demand:
    data: dict[str, object] = {"requester": "Ana", "department": "Comercial"}
    data.update(overrides)
    return Demand.model_validate(data)


def test_minimal_demand_has_spec_defaults() -> None:
    demand = _demand()

    assert isinstance(demand.request_id, UUID)
    assert demand.status is RequestStatus.RECEIVED
    assert demand.brand is None
    assert demand.deadline is None
    assert demand.dependencies == []
    assert demand.required_files == []
    assert demand.missing_information == []
    assert demand.is_promotional is False
    assert demand.published_error is False
    assert demand.briefing_score == 0
    assert demand.classification_confidence == 0.0
    assert demand.type_confirmed is False
    assert demand.priority is None
    assert demand.priority_locked is False
    assert demand.assignment_locked is False
    assert demand.field_origin == {}
    assert demand.external_task_id is None


def test_all_spec_fields_exist() -> None:
    spec_fields = {
        "request_id", "requester", "department", "company", "brand", "task_type", "campaign",
        "supplier", "objective", "audience", "message_tone", "channel", "format", "dimensions",
        "product", "price", "validity", "cta", "deadline", "duration", "concept", "location",
        "participants", "shoot_date", "headline", "landing_page", "link", "publish_period",
        "size", "quantity", "material", "finishing", "event_name", "event_date", "event_time",
        "participants_count", "budget", "deliverables", "priority", "priority_score",
        "priority_locked", "assigned_to", "assignment_locked", "approver", "dependencies",
        "required_files", "missing_information", "is_promotional", "briefing_score",
        "classification_confidence", "type_confirmed", "status", "field_origin",
        "external_task_id",
    }  # fmt: skip

    assert spec_fields <= set(Demand.model_fields)


def test_extractable_fields_exclude_harness_controlled_fields() -> None:
    assert "brand" in EXTRACTABLE_FIELDS
    assert "deadline" in EXTRACTABLE_FIELDS
    for controlled in (
        "requester", "department", "task_type", "priority", "assigned_to", "status",
        "briefing_score", "field_origin", "external_task_id", "is_promotional",
    ):  # fmt: skip
        assert controlled not in EXTRACTABLE_FIELDS
    assert set(EXTRACTABLE_FIELDS) <= set(Demand.model_fields)
    assert set(DATE_FIELDS) == {"deadline", "shoot_date", "event_date"}


def test_date_fields_parse_iso_and_serialize_iso() -> None:
    demand = _demand(deadline="2026-10-20")

    assert demand.deadline == date(2026, 10, 20)
    assert demand.model_dump(mode="json")["deadline"] == "2026-10-20"


def test_invalid_date_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _demand(deadline="20/10/2026")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1080x1350", "1080 × 1350 px"),
        ("1080 X 1920", "1080 × 1920 px"),
        ("1200×1500px", "1200 × 1500 px"),
        ("1080 × 1350 px", "1080 × 1350 px"),
        ("A4", "A4"),
    ],
)
def test_dimensions_are_normalized(raw: str, expected: str) -> None:
    assert normalize_dimensions(raw) == expected
    assert _demand(dimensions=raw).dimensions == expected


def test_scores_are_bounded() -> None:
    with pytest.raises(ValidationError):
        _demand(briefing_score=101)
    with pytest.raises(ValidationError):
        _demand(classification_confidence=1.2)
    with pytest.raises(ValidationError):
        _demand(priority_score=-1)


def test_priority_level_must_be_known() -> None:
    assert _demand(priority="Alta").priority == "Alta"
    with pytest.raises(ValidationError):
        _demand(priority="Urgentíssima")


def test_status_rejects_blocked_and_unknown() -> None:
    assert _demand(status="PENDING_APPROVAL").status is RequestStatus.PENDING_APPROVAL
    # D03: BLOCKED é flag da tarefa, não estado da demanda.
    with pytest.raises(ValidationError):
        _demand(status="BLOCKED")


def test_field_origin_accepts_known_origins_for_known_fields() -> None:
    demand = _demand(brand="Construjá", field_origin={"brand": "message", "cta": "rule"})

    assert demand.field_origin["brand"] is FieldOrigin.MESSAGE
    assert demand.field_origin["cta"] is FieldOrigin.RULE


def test_field_origin_rejects_unknown_origin_or_field() -> None:
    with pytest.raises(ValidationError):
        _demand(field_origin={"brand": "chute"})
    with pytest.raises(ValidationError, match="campo_inexistente"):
        _demand(field_origin={"campo_inexistente": "llm"})


def test_dependency_defaults_to_pending() -> None:
    dep = Dependency(dependency="Aprovação de preço", owner="Compras")

    assert dep.status == "Pendente"
    with pytest.raises(ValidationError):
        Dependency(dependency="x", owner="y", status="Talvez")


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _demand(cor_favorita="azul")


def test_required_file_keeps_origin() -> None:
    demand = _demand(required_files=[{"name": "Logo Krona", "origin": "rule"}])

    assert demand.required_files == [RequiredFile(name="Logo Krona", origin=FieldOrigin.RULE)]
    assert demand.model_dump(mode="json")["required_files"] == [
        {"name": "Logo Krona", "origin": "rule"}
    ]


@pytest.mark.parametrize(
    "item",
    [{"name": "", "origin": "rule"}, {"name": "Logo", "origin": "chute"}, "Logo Krona"],
)
def test_required_file_rejects_invalid_items(item: object) -> None:
    with pytest.raises(ValidationError):
        _demand(required_files=[item])
