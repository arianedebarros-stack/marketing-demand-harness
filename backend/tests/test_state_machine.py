import pytest

from app.core.state_machine import (
    ALLOWED_TRANSITIONS,
    FINAL_STATES,
    InvalidTransition,
    can_transition,
    is_final,
    transition,
)
from app.schemas.demand import RequestStatus as S

NON_FINAL = [s for s in S if s not in {S.TASK_CREATED, S.CANCELLED, S.REJECTED, S.ERROR}]

# Fluxo principal da SPEC §7 (sem os atalhos para CANCELLED/ERROR).
FLOW = [
    (S.RECEIVED, S.PARSED),
    (S.PARSED, S.VALIDATING),
    (S.VALIDATING, S.NEEDS_INFORMATION),
    (S.NEEDS_INFORMATION, S.VALIDATING),
    (S.VALIDATING, S.READY_FOR_TRIAGE),
    (S.READY_FOR_TRIAGE, S.TRIAGED),
    (S.TRIAGED, S.PENDING_APPROVAL),
    (S.PENDING_APPROVAL, S.APPROVED),
    (S.APPROVED, S.TASK_CREATED),
    (S.PENDING_APPROVAL, S.REJECTED),  # §7 + D02
    (S.PENDING_APPROVAL, S.VALIDATING),  # nova mensagem do solicitante
]
ESCAPES = [(s, target) for s in NON_FINAL for target in (S.CANCELLED, S.ERROR)]
VALID = FLOW + ESCAPES


@pytest.mark.parametrize(("current", "target"), VALID)
def test_valid_transitions(current: S, target: S) -> None:
    assert can_transition(current, target)
    assert transition(current, target) is target


def test_table_has_exactly_the_spec_transitions() -> None:
    table = {(src, dst) for src, targets in ALLOWED_TRANSITIONS.items() for dst in targets}

    assert table == set(VALID)
    assert set(ALLOWED_TRANSITIONS) == set(S)


def test_final_states() -> None:
    assert {S.TASK_CREATED, S.CANCELLED, S.REJECTED, S.ERROR} == FINAL_STATES
    for state in FINAL_STATES:
        assert is_final(state)
        assert ALLOWED_TRANSITIONS[state] == frozenset()
    for state in NON_FINAL:
        assert not is_final(state)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.RECEIVED, S.TASK_CREATED),  # pular tudo
        (S.NEEDS_INFORMATION, S.READY_FOR_TRIAGE),  # sem revalidar
        (S.VALIDATING, S.PENDING_APPROVAL),  # sem triagem
        (S.TRIAGED, S.APPROVED),  # sem passar pelo Approval Gate
        (S.READY_FOR_TRIAGE, S.TASK_CREATED),  # criar tarefa sem aprovação
        (S.PENDING_APPROVAL, S.TASK_CREATED),  # criar tarefa sem APPROVED
        (S.APPROVED, S.VALIDATING),  # reabrir depois de aprovado
        (S.APPROVED, S.REJECTED),  # rejeitar depois de aprovado
        (S.TASK_CREATED, S.CANCELLED),  # estado final
        (S.CANCELLED, S.RECEIVED),  # estado final
        (S.REJECTED, S.PENDING_APPROVAL),  # estado final
        (S.ERROR, S.ERROR),  # estado final
        (S.VALIDATING, S.VALIDATING),  # auto-transição
        (S.PARSED, S.RECEIVED),  # voltar no fluxo
    ],
)
def test_invalid_transitions_raise(current: S, target: S) -> None:
    assert not can_transition(current, target)

    with pytest.raises(InvalidTransition) as exc:
        transition(current, target)

    assert exc.value.current is current
    assert exc.value.target is target
    assert current.value in str(exc.value)
    assert target.value in str(exc.value)


def test_invalid_transition_exposes_audit_payload() -> None:
    with pytest.raises(InvalidTransition) as exc:
        transition(S.RECEIVED, S.APPROVED)

    assert exc.value.audit_payload() == {
        "action": "invalid_transition",
        "previous_value": {"status": "RECEIVED"},
        "new_value": {"status": "APPROVED"},
    }
