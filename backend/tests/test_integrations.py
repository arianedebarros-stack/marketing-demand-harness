"""AC14 — cria a tarefa após a aprovação: local e Asana simulado com respx (SPEC §11, D38).

Nenhum teste usa token real nem chama a API do Asana: o respx intercepta toda requisição httpx,
e uma requisição sem rota simulada falha o teste.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import Settings
from app.integrations.asana import ASANA_TASKS_URL, AsanaError, AsanaTaskManager
from app.integrations.local import LocalTaskManager
from app.main import app
from app.models import Task

FAKE_TOKEN = "token-de-teste-nao-real"
REQUEST_ID = UUID("6f1c2d3e-4b5a-4c6d-8e7f-90a1b2c3d4e5")
PROJECT = "1200000000000001"
GID = "1209999999999999"
CASE_02 = (
    "Preciso de um feed 1080x1350 da Construjá para divulgar a promoção Krona amanhã. "
    "Os produtos e preços estão na planilha anexada e a promoção vale até sexta."
)


def _task(**fields: Any) -> Task:
    data: dict[str, Any] = {
        "id": 7,
        "request_id": REQUEST_ID,
        "title": "Arte | Promoção Krona | Construjá",
        "briefing": "TÍTULO: Arte | Promoção Krona | Construjá\nPRAZO: 20/10/2026",
        "deadline": date(2026, 10, 20),
    }
    data.update(fields)
    return Task(**data)


def _asana() -> AsanaTaskManager:
    return AsanaTaskManager(token=SecretStr(FAKE_TOKEN), project_gid=PROJECT)


def _created(gid: str = GID) -> httpx.Response:
    return httpx.Response(201, json={"data": {"gid": gid, "resource_type": "task"}})


# --- Local ---------------------------------------------------------------------------------


def test_local_returns_mkt_id() -> None:
    assert LocalTaskManager().create_task(_task(id=42)) == "MKT-42"


# --- Asana: requisição (§11) ---------------------------------------------------------------


@respx.mock
def test_asana_posts_task_with_spec_payload() -> None:
    route = respx.post(ASANA_TASKS_URL).mock(return_value=_created())

    external_id = _asana().create_task(_task())

    assert external_id == GID
    assert route.call_count == 1
    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert request.headers["Accept"] == "application/json"
    assert json.loads(request.content) == {
        "data": {
            "name": "Arte | Promoção Krona | Construjá",
            "notes": (
                "TÍTULO: Arte | Promoção Krona | Construjá\nPRAZO: 20/10/2026\n\n"
                f"ID DA DEMANDA: {REQUEST_ID}"
            ),
            "due_on": "2026-10-20",
            "projects": [PROJECT],
        }
    }


@respx.mock
def test_asana_without_deadline_omits_due_on() -> None:
    route = respx.post(ASANA_TASKS_URL).mock(return_value=_created())

    _asana().create_task(_task(deadline=None))

    assert "due_on" not in json.loads(route.calls.last.request.content)["data"]


# --- Asana: falhas (D04, D38) --------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503])
@respx.mock
def test_asana_http_error_raises_without_retry(status: int) -> None:
    body = {"errors": [{"message": "Not Authorized"}]}
    route = respx.post(ASANA_TASKS_URL).mock(return_value=httpx.Response(status, json=body))

    with pytest.raises(AsanaError) as exc:
        _asana().create_task(_task())

    assert route.call_count == 1  # sem nova tentativa: evita tarefa duplicada no Asana
    assert exc.value.status_code == status
    assert str(status) in str(exc.value)
    assert "Not Authorized" in str(exc.value)
    assert FAKE_TOKEN not in str(exc.value)


@respx.mock
def test_asana_network_error_raises() -> None:
    respx.post(ASANA_TASKS_URL).mock(side_effect=httpx.ConnectTimeout("timeout"))

    with pytest.raises(AsanaError, match="conexão"):
        _asana().create_task(_task())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(201, json={"data": {}}),
        httpx.Response(201, json={"other": 1}),
        httpx.Response(201, text="não é json"),
        httpx.Response(201, json={"data": {"gid": ""}}),
    ],
)
@respx.mock
def test_asana_response_without_gid_raises(response: httpx.Response) -> None:
    respx.post(ASANA_TASKS_URL).mock(return_value=response)

    with pytest.raises(AsanaError, match="gid"):
        _asana().create_task(_task())


def test_asana_error_body_that_is_not_json() -> None:
    with respx.mock:
        respx.post(ASANA_TASKS_URL).mock(return_value=httpx.Response(502, text="Bad Gateway"))
        with pytest.raises(AsanaError, match="502"):
            _asana().create_task(_task())


# --- Settings e escolha do conector (D38) --------------------------------------------------


def _settings(**values: Any) -> Settings:
    return Settings.model_validate(
        {"task_manager": "local", "asana_token": None, "asana_project_gid": None, **values}
    )


def test_default_task_manager_is_local() -> None:
    assert Settings.model_fields["task_manager"].default == "local"
    assert isinstance(deps.build_task_manager(_settings()), LocalTaskManager)


def test_asana_selected_by_settings() -> None:
    settings = _settings(task_manager="asana", asana_token=FAKE_TOKEN, asana_project_gid=PROJECT)

    manager = deps.build_task_manager(settings)

    assert isinstance(manager, AsanaTaskManager)
    assert manager.project_gid == PROJECT
    assert manager.name == "asana"


@pytest.mark.parametrize(
    "values",
    [
        {"asana_token": None, "asana_project_gid": PROJECT},
        {"asana_token": FAKE_TOKEN, "asana_project_gid": None},
        {"asana_token": "  ", "asana_project_gid": "  "},
    ],
)
def test_asana_without_credentials_is_a_config_error(values: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="ASANA_TOKEN e ASANA_PROJECT_GID"):
        _settings(task_manager="asana", **values)


def test_from_settings_guards_missing_credentials() -> None:
    """Defesa extra para settings montadas sem validação (model_construct)."""
    with pytest.raises(ValueError, match="obrigatórios"):
        AsanaTaskManager.from_settings(Settings.model_construct(task_manager="asana"))


def test_token_is_not_in_repr() -> None:
    assert FAKE_TOKEN not in repr(_asana())


# --- AC14 pela API: aprovação cria a tarefa no Asana simulado ------------------------------


def _pending(client: TestClient) -> str:
    body = {"requester_name": "Ana", "department": "Comercial", "channel": "chat"}
    view = client.post("/requests", json={**body, "message": CASE_02}).json()
    assert view["demand"]["status"] == "PENDING_APPROVAL"
    return str(view["demand"]["request_id"])


@respx.mock
def test_approve_creates_task_in_asana(client: TestClient, session: Session) -> None:
    """AC14: depois da aprovação, a tarefa vai para o Asana e o gid vira external_task_id."""
    route = respx.post(ASANA_TASKS_URL).mock(return_value=_created())
    app.dependency_overrides[deps.get_task_manager] = _asana
    request_id = _pending(client)
    assert route.call_count == 0  # nada vai para o Asana antes da aprovação (AC13)

    view = client.post(f"/requests/{request_id}/approve", json={}).json()

    assert view["demand"]["status"] == "TASK_CREATED"
    assert view["demand"]["external_task_id"] == GID
    [task] = client.get("/tasks").json()
    assert task["external_task_id"] == GID
    created = next(e for e in view["audit"] if e["action"] == "task_created")
    assert created["new_value"]["connector"] == "asana"
    sent = json.loads(route.calls.last.request.content)["data"]
    assert sent["name"] == task["title"]
    # D38: o id da demanda no texto ajuda a reconhecer uma duplicata no Asana.
    assert sent["notes"] == f"{task['briefing']}\n\nID DA DEMANDA: {request_id}"
    assert sent["due_on"] == task["deadline"]


@respx.mock
def test_asana_failure_keeps_approved_and_retry_works(client: TestClient) -> None:
    """D04: Asana fora do ar deixa a demanda em APPROVED; approve de novo cria a tarefa."""
    route = respx.post(ASANA_TASKS_URL)
    route.side_effect = [httpx.Response(503, json={"errors": [{"message": "down"}]}), _created()]
    app.dependency_overrides[deps.get_task_manager] = _asana
    request_id = _pending(client)

    failed = client.post(f"/requests/{request_id}/approve", json={})
    assert failed.status_code == 502
    assert "503" in failed.json()["detail"]
    view = client.get(f"/requests/{request_id}").json()
    assert view["demand"]["status"] == "APPROVED"
    assert view["audit"][-1]["action"] == "task_creation_failed"
    assert client.get("/tasks").json() == []

    retry = client.post(f"/requests/{request_id}/approve", json={}).json()
    assert retry["demand"]["status"] == "TASK_CREATED"
    assert retry["demand"]["external_task_id"] == GID
    assert route.call_count == 2
