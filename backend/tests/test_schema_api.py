from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.api import (
    ApproveBody,
    AuditEntry,
    CreateRequestBody,
    DemandPatch,
    MessageBody,
    Question,
    RequestView,
)
from app.schemas.demand import Demand


def _view(**overrides: object) -> RequestView:
    data: dict[str, object] = {
        "demand": Demand(requester="Ana", department="Comercial"),
        "next_action": "REQUEST_INFORMATION",
        "questions": [{"fields": ["channel", "format"], "text": "Qual canal e formato?"}],
        "score_band": "Incompleto",
        "audit": [],
    }
    data.update(overrides)
    return RequestView.model_validate(data)


def test_request_view_has_spec_shape() -> None:
    view = _view()

    # §9 mais ``title`` (D40), derivado da demanda para o Approval Gate.
    assert set(RequestView.model_fields) == {
        "demand", "title", "next_action", "questions", "score_band", "audit",
    }  # fmt: skip
    assert view.questions[0] == Question(fields=["channel", "format"], text="Qual canal e formato?")
    dumped = view.model_dump(mode="json")
    assert dumped["demand"]["status"] == "RECEIVED"


@pytest.mark.parametrize(
    "action", ["REQUEST_INFORMATION", "CONFIRM_TYPE", "AWAIT_APPROVAL", "DONE", "CANCELLED"]
)
def test_next_action_accepts_spec_values(action: str) -> None:
    assert _view(next_action=action).next_action == action


def test_next_action_rejects_other_values() -> None:
    with pytest.raises(ValidationError):
        _view(next_action="CREATE_TASK")


@pytest.mark.parametrize("band", ["Incompleto", "Parcial", "Quase pronto", "Pronto para produção"])
def test_score_band_accepts_spec_values(band: str) -> None:
    assert _view(score_band=band).score_band == band


def test_score_band_rejects_other_values() -> None:
    with pytest.raises(ValidationError):
        _view(score_band="Ótimo")


def test_question_needs_at_least_one_field() -> None:
    with pytest.raises(ValidationError):
        Question(fields=[], text="?")


def test_audit_entry_actor_is_restricted() -> None:
    entry = AuditEntry(
        id=1,
        request_id=None,
        task_id=None,
        actor="harness",
        action="state_transition",
        previous_value={"status": "RECEIVED"},
        new_value={"status": "PARSED"},
        timestamp=datetime(2026, 10, 19, 9, 0, tzinfo=UTC),
    )
    assert entry.actor == "harness"

    with pytest.raises(ValidationError):
        AuditEntry.model_validate({**entry.model_dump(), "actor": "sistema"})


def test_create_request_body_requires_non_blank_message() -> None:
    body = CreateRequestBody(
        requester_name="Ana", department="Comercial", channel="chat", message="  Faz uma arte. "
    )
    assert body.message == "Faz uma arte."

    with pytest.raises(ValidationError):
        CreateRequestBody(requester_name="Ana", department="Comercial", channel="chat", message=" ")
    with pytest.raises(ValidationError):
        MessageBody(message="")


def test_approve_body_defaults_force_new_false() -> None:
    assert ApproveBody().force_new is False


def test_demand_patch_accepts_editable_fields_only() -> None:
    patch = DemandPatch.model_validate(
        {"priority": "Crítica", "assigned_to": "designer-b", "deadline": "2026-10-21"}
    )
    assert patch.provided() == {
        "priority": "Crítica",
        "assigned_to": "designer-b",
        "deadline": patch.deadline,
    }

    for forbidden in ("status", "briefing_score", "field_origin", "priority_locked"):
        with pytest.raises(ValidationError):
            DemandPatch.model_validate({forbidden: "x"})


def test_demand_patch_fields_exist_in_demand() -> None:
    assert set(DemandPatch.model_fields) <= set(Demand.model_fields)
