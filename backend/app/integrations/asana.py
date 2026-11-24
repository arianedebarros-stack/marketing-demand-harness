"""AsanaTaskManager (SPEC §11, D38): cria a tarefa no Asana e devolve o ``gid``.

``POST https://app.asana.com/api/1.0/tasks`` com ``{"data": {name, notes, due_on, projects}}`` e
``Authorization: Bearer ASANA_TOKEN``. O texto (``notes``) é o briefing seguido do id da
demanda. Não há nova tentativa automática: um POST repetido depois
de um timeout pode criar a tarefa duas vezes. A falha vira ``AsanaError``; a demanda fica em
``APPROVED`` e o gestor chama ``approve`` de novo (D04).
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import SecretStr

from app.core.config import Settings
from app.models import Task

ASANA_TASKS_URL = "https://app.asana.com/api/1.0/tasks"
DEFAULT_TIMEOUT_SECONDS = 20.0


class AsanaError(Exception):
    """Falha ao criar a tarefa no Asana (nunca inclui o token)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class AsanaTaskManager:
    name = "asana"

    def __init__(
        self,
        *,
        token: SecretStr,
        project_gid: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._token = token
        self.project_gid = project_gid
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"AsanaTaskManager(project_gid={self.project_gid!r})"

    @classmethod
    def from_settings(cls, settings: Settings) -> AsanaTaskManager:
        if settings.asana_token is None or settings.asana_project_gid is None:
            raise ValueError("ASANA_TOKEN e ASANA_PROJECT_GID são obrigatórios")
        return cls(token=settings.asana_token, project_gid=settings.asana_project_gid)

    def create_task(self, task: Task) -> str:
        data: dict[str, Any] = {
            "name": task.title,
            # D38: o id da demanda ajuda a reconhecer uma tarefa duplicada no Asana.
            "notes": f"{task.briefing}\n\nID DA DEMANDA: {task.request_id}",
            "projects": [self.project_gid],
        }
        if task.deadline is not None:
            data["due_on"] = task.deadline.isoformat()
        headers = {
            "Authorization": f"Bearer {self._token.get_secret_value()}",
            "Accept": "application/json",
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(ASANA_TASKS_URL, json={"data": data}, headers=headers)
        except httpx.HTTPError as exc:
            raise AsanaError(f"erro de conexão com o Asana: {type(exc).__name__}") from exc

        if response.is_error:
            raise AsanaError(
                f"Asana respondeu {response.status_code}: {_error_message(response)}",
                status_code=response.status_code,
            )
        try:
            gid = response.json()["data"]["gid"]
        except (ValueError, KeyError, TypeError) as exc:
            raise AsanaError("resposta do Asana sem o gid da tarefa") from exc
        if not isinstance(gid, str) or not gid:
            raise AsanaError("resposta do Asana sem o gid da tarefa")
        return gid


def _error_message(response: httpx.Response) -> str:
    """Mensagens de erro do corpo do Asana (``{"errors": [{"message": ...}]}``)."""
    try:
        errors = response.json().get("errors", [])
        messages = [str(e.get("message")) for e in errors if isinstance(e, dict)]
    except (ValueError, AttributeError):
        messages = []
    return "; ".join(messages) or response.reason_phrase or "sem detalhes"
