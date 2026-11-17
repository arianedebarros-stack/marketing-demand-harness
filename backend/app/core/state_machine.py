"""Máquina de estados da demanda (SPEC §7, D02, D03, D05).

Funções puras: não gravam nada. Quem chama registra a transição (ou a recusa) no audit log,
usando ``InvalidTransition.audit_payload()``.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from app.schemas.demand import RequestStatus as S

FINAL_STATES: frozenset[S] = frozenset({S.TASK_CREATED, S.CANCELLED, S.REJECTED, S.ERROR})

_FLOW: dict[S, set[S]] = {
    S.RECEIVED: {S.PARSED},
    S.PARSED: {S.VALIDATING},
    S.VALIDATING: {S.NEEDS_INFORMATION, S.READY_FOR_TRIAGE},
    S.NEEDS_INFORMATION: {S.VALIDATING},
    S.READY_FOR_TRIAGE: {S.TRIAGED},
    S.TRIAGED: {S.PENDING_APPROVAL},
    # APPROVED: aprovação; REJECTED: D02; VALIDATING: nova mensagem do solicitante.
    S.PENDING_APPROVAL: {S.APPROVED, S.REJECTED, S.VALIDATING},
    # Falha ao criar a tarefa mantém APPROVED e permite nova tentativa (D04).
    S.APPROVED: {S.TASK_CREATED},
}


def _build_table() -> Mapping[S, frozenset[S]]:
    table: dict[S, frozenset[S]] = {}
    for state in S:
        if state in FINAL_STATES:
            table[state] = frozenset()
        else:
            # Qualquer estado não final pode ir para CANCELLED ou ERROR.
            table[state] = frozenset(_FLOW.get(state, set()) | {S.CANCELLED, S.ERROR})
    return MappingProxyType(table)


ALLOWED_TRANSITIONS: Mapping[S, frozenset[S]] = _build_table()


class InvalidTransition(Exception):  # noqa: N818 — nome definido na SPEC §7
    def __init__(self, current: S, target: S) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Transição inválida: {current.value} → {target.value}")

    def audit_payload(self) -> dict[str, Any]:
        return {
            "action": "invalid_transition",
            "previous_value": {"status": self.current.value},
            "new_value": {"status": self.target.value},
        }


def is_final(state: S) -> bool:
    return state in FINAL_STATES


def can_transition(current: S, target: S) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def transition(current: S, target: S) -> S:
    """Devolve ``target`` se a transição é permitida; senão levanta ``InvalidTransition``."""
    if not can_transition(current, target):
        raise InvalidTransition(current, target)
    return target
