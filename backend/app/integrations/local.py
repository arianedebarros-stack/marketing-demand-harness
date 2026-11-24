"""LocalTaskManager (SPEC §11): a tarefa já está em ``tasks``; o id externo é ``MKT-<n>``."""

from __future__ import annotations

from app.models import Task


class LocalTaskManager:
    name = "local"

    def create_task(self, task: Task) -> str:
        if task.id is None:
            raise ValueError("a tarefa precisa estar gravada (flush) antes de criar o id externo")
        return f"MKT-{task.id}"
