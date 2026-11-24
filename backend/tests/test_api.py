"""API (SPEC §9): AC01, AC13 e o contrato de cada rota (D02, D04, D13, D23, D36)."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import deps
from app.core.config import get_app_config
from app.llm.base import InterpretationContext
from app.main import app
from app.models import Message, Task
from app.schemas.llm import LLMInterpretation

CASE_01 = "Faz uma arte da Krona."
CASE_02 = (
    "Preciso de um feed 1080x1350 da Construjá para divulgar a promoção Krona amanhã. "
    "Os produtos e preços estão na planilha anexada e a promoção vale até sexta."
)
CASE_06 = (
    "Preciso de uma arte da Krona para amanhã.",
    "Construjá",
    "Instagram feed. São 3 produtos da planilha anexada. Promoção válida até sexta. "
    "Ainda aguardando aprovação de preço por Compras.",
)


def _create(client: TestClient, message: str, **extra: Any) -> dict[str, Any]:
    body = {"requester_name": "Ana", "department": "Comercial", "channel": "chat"}
    body.update(extra)
    response = client.post("/requests", json={**body, "message": message})
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


def _id(view: dict[str, Any]) -> str:
    return str(view["demand"]["request_id"])


def _pending(client: TestClient, message: str = CASE_02) -> str:
    view = _create(client, message)
    assert view["demand"]["status"] == "PENDING_APPROVAL", view["demand"]["status"]
    return _id(view)


def _actions(view: dict[str, Any]) -> list[str]:
    return [entry["action"] for entry in view["audit"]]


def _task_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Task)) or 0


# --- AC01 · recebe pedido em linguagem natural ---------------------------------------------


def test_create_request(client: TestClient, session: Session) -> None:
    """AC01: cria a demanda, interpreta, roda o pipeline e devolve o RequestView."""
    view = _create(client, CASE_01)

    demand = view["demand"]
    assert demand["status"] == "NEEDS_INFORMATION"
    assert demand["requester"] == "Ana"
    assert demand["department"] == "Comercial"
    assert demand["field_origin"]["requester"] == "requester"
    assert view["next_action"] == "REQUEST_INFORMATION"
    assert view["score_band"] == "Incompleto"
    assert [q["fields"] for q in view["questions"]][0] == ["brand"]
    assert "message_received" in _actions(view)
    roles = session.scalars(select(Message.role).order_by(Message.id)).all()
    assert roles == ["requester", "assistant"]


def test_get_request_returns_current_state(client: TestClient) -> None:
    created = _create(client, CASE_01)

    response = client.get(f"/requests/{_id(created)}")

    assert response.status_code == 200
    view = response.json()
    assert view["demand"] == created["demand"]
    assert view["questions"] == created["questions"]
    assert view["audit"] == created["audit"]


def test_unknown_request_is_404(client: TestClient) -> None:
    response = client.get("/requests/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"requester_name": "Ana", "department": "Comercial", "channel": "chat"},
        {"requester_name": "Ana", "department": "Comercial", "channel": "chat", "message": "  "},
        {"requester_name": "", "department": "C", "channel": "chat", "message": "Oi"},
        {"requester_name": "A", "department": "C", "channel": "chat", "message": "Oi", "x": 1},
    ],
)
def test_invalid_body_is_422(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/requests", json=body).status_code == 422


def test_answers_keep_memory_until_pending_approval(client: TestClient) -> None:
    request_id = _id(_create(client, CASE_06[0]))
    client.post(f"/requests/{request_id}/answers", json={"message": CASE_06[1]})

    response = client.post(f"/requests/{request_id}/answers", json={"message": CASE_06[2]})

    assert response.status_code == 200
    view = response.json()
    assert view["demand"]["status"] == "PENDING_APPROVAL"
    assert view["demand"]["brand"] == "Construjá"
    assert view["demand"]["deadline"] == "2026-10-20"
    assert view["next_action"] == "AWAIT_APPROVAL"
    assert view["questions"] == []


# --- AC13 · exige aprovação ----------------------------------------------------------------


def test_cannot_create_task_without_approval(client: TestClient, session: Session) -> None:
    """AC13: nenhuma tarefa existe antes do approve; approve fora de PENDING_APPROVAL é 409."""
    incomplete = _id(_create(client, CASE_01))
    response = client.post(f"/requests/{incomplete}/approve", json={})
    assert response.status_code == 409
    assert _task_count(session) == 0

    pending = _pending(client)
    assert _task_count(session) == 0
    assert client.get("/tasks").json() == []

    approved = client.post(f"/requests/{pending}/approve", json={})
    assert approved.status_code == 200
    assert _task_count(session) == 1


def test_invalid_transition_is_audited(client: TestClient) -> None:
    request_id = _id(_create(client, CASE_01))

    client.post(f"/requests/{request_id}/approve", json={})

    view = client.get(f"/requests/{request_id}").json()
    assert _actions(view)[-1] == "invalid_transition"
    assert view["audit"][-1]["new_value"] == {"status": "APPROVED"}


# --- Aprovação e tarefa --------------------------------------------------------------------


def test_approve_creates_task(client: TestClient) -> None:
    request_id = _pending(client)

    response = client.post(f"/requests/{request_id}/approve", json={})

    view = response.json()
    assert view["demand"]["status"] == "TASK_CREATED"
    assert view["next_action"] == "DONE"
    external = view["demand"]["external_task_id"]
    assert external.startswith("MKT-")
    [task] = client.get("/tasks").json()
    assert task["external_task_id"] == external
    assert task["title"] == "Arte | Promoção Krona | Construjá"
    assert task["assigned_to"] == "designer-a"
    assert task["priority"] == "Alta"
    assert task["deadline"] == "2026-10-20"
    assert task["status"] == "Aberta"
    assert task["blocked"] is False
    assert task["briefing"].startswith("TÍTULO: Arte | Promoção Krona | Construjá")
    assert task["briefing_score"] == 100
    actions = _actions(view)
    assert actions[-5:] == [
        "no_duplicate",
        "approved",
        "status_transition",
        "task_created",
        "status_transition",
    ]
    assert client.post(f"/requests/{request_id}/approve", json={}).status_code == 409


def test_task_manager_failure_keeps_approved_and_allows_retry(
    client: TestClient, session: Session
) -> None:
    """D04: falha ao criar a tarefa deixa a demanda em APPROVED; approve pode ser repetido."""

    class Broken:
        name = "quebrado"

        def create_task(self, task: Task) -> str:
            raise RuntimeError("fora do ar")

    request_id = _pending(client)
    app.dependency_overrides[deps.get_task_manager] = Broken
    failed = client.post(f"/requests/{request_id}/approve", json={})
    del app.dependency_overrides[deps.get_task_manager]

    assert failed.status_code == 502
    view = client.get(f"/requests/{request_id}").json()
    assert view["demand"]["status"] == "APPROVED"
    assert view["next_action"] == "AWAIT_APPROVAL"
    assert _actions(view)[-1] == "task_creation_failed"
    assert _task_count(session) == 0

    retry = client.post(f"/requests/{request_id}/approve", json={})
    assert retry.status_code == 200
    assert retry.json()["demand"]["status"] == "TASK_CREATED"


def test_reject_and_cancel(client: TestClient) -> None:
    """D02: rejeição em PENDING_APPROVAL; cancelamento em qualquer estado não final."""
    rejected = client.post(f"/requests/{_pending(client)}/reject")
    assert rejected.json()["demand"]["status"] == "REJECTED"
    assert rejected.json()["next_action"] == "CANCELLED"

    request_id = _id(_create(client, CASE_01))
    cancelled = client.post(f"/requests/{request_id}/cancel")
    assert cancelled.json()["demand"]["status"] == "CANCELLED"
    assert client.post(f"/requests/{request_id}/cancel").status_code == 409
    assert client.post(f"/requests/{request_id}/answers", json={"message": "Oi"}).status_code == 409


def test_reject_outside_pending_approval_is_409(client: TestClient) -> None:
    request_id = _id(_create(client, CASE_01))
    assert client.post(f"/requests/{request_id}/reject").status_code == 409


# --- Confirmação de tipo, validação, triagem -----------------------------------------------


def test_confirm_type(client: TestClient) -> None:
    view = _create(client, "Faz promoção da Krona.")
    assert view["next_action"] == "CONFIRM_TYPE"

    response = client.post(f"/requests/{_id(view)}/confirm-type", json={"task_type": "arte"})

    confirmed = response.json()
    assert response.status_code == 200
    assert confirmed["demand"]["task_type"] == "Arte"
    assert confirmed["demand"]["type_confirmed"] is True
    assert confirmed["demand"]["field_origin"]["task_type"] == "requester"
    assert confirmed["next_action"] == "REQUEST_INFORMATION"
    assert "task_type" not in confirmed["demand"]["missing_information"]


def test_confirm_unknown_type_is_422(client: TestClient) -> None:
    view = _create(client, "Faz promoção da Krona.")
    response = client.post(f"/requests/{_id(view)}/confirm-type", json={"task_type": "Holograma"})
    assert response.status_code == 422


def test_validate_reruns_without_llm(client: TestClient) -> None:
    view = _create(client, CASE_01)

    response = client.post(f"/requests/{_id(view)}/validate")

    assert response.status_code == 200
    assert response.json()["demand"]["status"] == "NEEDS_INFORMATION"
    assert _actions(response.json()).count("interpretation") == 1


def test_triage_requires_100_percent(client: TestClient) -> None:
    view = _create(client, CASE_01)

    response = client.post(f"/requests/{_id(view)}/triage")

    assert response.status_code == 409
    assert "exige 100%" in response.json()["detail"]


def test_triage_rerun_in_pending_approval(client: TestClient) -> None:
    request_id = _pending(client)

    response = client.post(f"/requests/{request_id}/triage")

    assert response.status_code == 200
    assert response.json()["demand"]["status"] == "PENDING_APPROVAL"


# --- PATCH (edição humana) -----------------------------------------------------------------


def test_patch_sets_manager_origin_and_audits(client: TestClient) -> None:
    request_id = _id(_create(client, CASE_01))

    response = client.patch(f"/requests/{request_id}", json={"brand": "Ferjá", "objective": "X"})

    view = response.json()
    assert response.status_code == 200
    assert view["demand"]["brand"] == "Ferjá"
    assert view["demand"]["field_origin"]["brand"] == "manager"
    assert view["demand"]["audience"] == "Consumidor final"  # regra da marca rodou de novo
    edits = [e for e in view["audit"] if e["action"] == "human_edit"]
    assert [e["new_value"]["field"] for e in edits] == ["brand", "objective"]
    assert edits[0]["actor"] == "manager"
    assert edits[0]["previous_value"] == {"field": "brand", "value": None}


def test_patch_priority_and_assignee_lock(client: TestClient) -> None:
    request_id = _pending(client)

    response = client.patch(
        f"/requests/{request_id}", json={"priority": "Baixa", "assigned_to": "designer-b"}
    )

    demand = response.json()["demand"]
    assert demand["status"] == "PENDING_APPROVAL"
    assert (demand["priority"], demand["priority_locked"]) == ("Baixa", True)
    assert (demand["assigned_to"], demand["assignment_locked"]) == ("designer-b", True)


def test_patch_null_releases_lock(client: TestClient) -> None:
    request_id = _pending(client)
    client.patch(f"/requests/{request_id}", json={"priority": "Baixa"})

    demand = client.patch(f"/requests/{request_id}", json={"priority": None}).json()["demand"]

    assert demand["priority_locked"] is False
    assert demand["priority"] == "Alta"  # a triagem recalculou


@pytest.mark.parametrize(
    "body",
    [{"status": "APPROVED"}, {"priority_locked": True}, {"task_type": "Holograma"},
     {"assigned_to": "fantasma"}, {"deadline": "amanhã"}],
)  # fmt: skip
def test_patch_rejects_invalid_fields(client: TestClient, body: dict[str, Any]) -> None:
    request_id = _id(_create(client, CASE_01))
    assert client.patch(f"/requests/{request_id}", json=body).status_code == 422


def test_patch_after_task_created_is_409(client: TestClient) -> None:
    request_id = _pending(client)
    client.post(f"/requests/{request_id}/approve", json={})

    assert client.patch(f"/requests/{request_id}", json={"objective": "Y"}).status_code == 409


# --- Tarefas -------------------------------------------------------------------------------


def _approved_case_06(client: TestClient) -> dict[str, Any]:
    request_id = _id(_create(client, CASE_06[0]))
    client.post(f"/requests/{request_id}/answers", json={"message": CASE_06[1]})
    client.post(f"/requests/{request_id}/answers", json={"message": CASE_06[2]})
    client.post(f"/requests/{request_id}/approve", json={})
    [task] = client.get("/tasks").json()
    return dict(task)


def test_resolve_dependency_unblocks_task(client: TestClient) -> None:
    task = _approved_case_06(client)
    assert task["blocked"] is True
    assert task["dependencies"] == [
        {"index": 0, "description": "Aprovação de preço", "owner": "Compras", "status": "Pendente"}
    ]

    response = client.post(f"/tasks/{task['id']}/dependencies/0/resolve")

    resolved = response.json()
    assert response.status_code == 200
    assert resolved["blocked"] is False
    assert resolved["dependencies"][0]["status"] == "Resolvida"
    assert client.post(f"/tasks/{task['id']}/dependencies/5/resolve").status_code == 404
    assert client.post("/tasks/999999/dependencies/0/resolve").status_code == 404


def test_complete_task(client: TestClient) -> None:
    """D13: POST /tasks/{id}/complete."""
    task = _approved_case_06(client)

    response = client.post(f"/tasks/{task['id']}/complete")

    assert response.status_code == 200
    assert response.json()["status"] == "Concluída"
    assert client.post(f"/tasks/{task['id']}/complete").status_code == 409


def test_config_is_read_only_view(client: TestClient) -> None:
    response = client.get("/config")

    assert response.status_code == 200
    data = response.json()
    assert data["brands"]["construja"]["name"] == "Construjá"
    assert data["task_types"]["approver_default"] == get_app_config().task_types.approver_default
    assert client.post("/config", json={}).status_code == 405


# --- LLM indisponível (§9: 502 e fallback) -------------------------------------------------


class _BrokenLLM:
    provider = "anthropic"

    def interpret(self, context: InterpretationContext) -> LLMInterpretation:
        raise RuntimeError("timeout")


def test_llm_failure_falls_back_to_fake(client: TestClient) -> None:
    from app.llm.fake_client import FakeLLMClient
    from app.llm.fallback import FallbackLLMClient

    app.dependency_overrides[deps.get_llm] = lambda: FallbackLLMClient(
        _BrokenLLM(), FakeLLMClient()
    )

    view = _create(client, CASE_01)

    assert view["demand"]["status"] == "NEEDS_INFORMATION"
    fallback = next(e for e in view["audit"] if e["action"] == "llm_fallback")
    assert fallback["new_value"] == {"failed": "anthropic", "used": "fake", "error": "timeout"}
    interpretation = next(e for e in view["audit"] if e["action"] == "interpretation")
    assert interpretation["new_value"]["provider"] == "fake"


def test_llm_failure_without_fallback_is_502(client: TestClient, session: Session) -> None:
    from app.llm.fallback import FallbackLLMClient

    app.dependency_overrides[deps.get_llm] = lambda: FallbackLLMClient(_BrokenLLM(), None)

    body = {"requester_name": "Ana", "department": "C", "channel": "chat", "message": CASE_01}
    response = client.post("/requests", json=body)

    assert response.status_code == 502
    assert _task_count(session) == 0


def test_link_existing_errors(client: TestClient) -> None:
    first = _pending(client)
    client.post(f"/requests/{first}/approve", json={})
    [task] = client.get("/tasks").json()

    incomplete = _id(_create(client, CASE_01))
    assert (
        client.post(
            f"/requests/{incomplete}/link-existing", json={"task_id": task["id"]}
        ).status_code
        == 409
    )

    client.post(f"/tasks/{task['id']}/complete")
    pending = _pending(client)
    response = client.post(f"/requests/{pending}/link-existing", json={"task_id": task["id"]})
    assert response.status_code == 409
    assert "concluída" in response.json()["detail"]
