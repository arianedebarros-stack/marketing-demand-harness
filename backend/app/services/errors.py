"""Erros de domínio que a API converte em códigos HTTP (§9)."""

from __future__ import annotations

from app.schemas.api import DuplicateConflict


class NotFoundError(Exception):
    """Demanda, tarefa ou dependência inexistente → 404."""


class ConflictError(Exception):
    """Operação incompatível com o estado atual → 409."""


class UnprocessableError(Exception):
    """Valor fora das listas de config (tipo, responsável) → 422."""


class DuplicateTaskError(ConflictError):
    """Há tarefa aberta parecida; o cliente usa ``force_new`` ou ``link-existing`` (§8.8)."""

    def __init__(self, conflict: DuplicateConflict) -> None:
        self.conflict = conflict
        super().__init__(conflict.detail)


class TaskCreationError(Exception):
    """O sistema de tarefas falhou; a demanda fica em APPROVED (D04) → 502."""
