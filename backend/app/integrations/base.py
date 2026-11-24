"""Interface do sistema de tarefas (SPEC §11)."""

from __future__ import annotations

from typing import Protocol

from app.models import Task


class TaskManagerConnector(Protocol):
    name: str

    def create_task(self, task: Task) -> str:
        """Cria a tarefa no sistema externo e devolve o id externo."""
        ...
