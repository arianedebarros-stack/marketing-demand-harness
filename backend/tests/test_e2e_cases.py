"""Casos 01–06 da SPEC §17 de ponta a ponta pela API, com FakeLLMClient (T15).

Inclui o teste de integração da triagem automática: da mensagem até PENDING_APPROVAL (D34).
"""

from typing import Any

from fastapi.testclient import TestClient

from app.core.config import get_app_config

CONFIG = get_app_config()
FERJA = CONFIG.brands["ferja"]
CONSTRUJA = CONFIG.brands["construja"]
CASE_02 = (
    "Preciso de um feed 1080x1350 da Construjá para divulgar a promoção Krona amanhã. "
    "Os produtos e preços estão na planilha anexada e a promoção vale até sexta."
)


def _post(client: TestClient, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    response = client.post(url, json=body if body is not None else {})
    assert response.status_code in (200, 201), response.text
    data: dict[str, Any] = response.json()
    return data


def _create(client: TestClient, message: str) -> dict[str, Any]:
    return _post(
        client,
        "/requests",
        {"requester_name": "Ana", "department": "Comercial", "channel": "chat", "message": message},
    )


def _rid(view: dict[str, Any]) -> str:
    return str(view["demand"]["request_id"])


def test_case_01_needs_information_and_no_task(client: TestClient) -> None:
    view = _create(client, "Faz uma arte da Krona.")

    assert view["demand"]["status"] == "NEEDS_INFORMATION"
    assert [q["fields"] for q in view["questions"]] == [
        ["brand"],
        ["objective"],
        ["channel", "format"],
        ["product", "price"],
        ["validity"],
        ["deadline"],
    ]
    assert client.get("/tasks").json() == []


def test_case_02_complete_request(client: TestClient) -> None:
    view = _create(client, CASE_02)
    demand = view["demand"]

    assert (demand["task_type"], demand["brand"], demand["supplier"]) == (
        "Arte",
        "Construjá",
        "Krona",
    )
    assert (demand["channel"], demand["format"], demand["dimensions"]) == (
        "Instagram",
        "Feed",
        "1080 × 1350 px",
    )
    assert demand["briefing_score"] == 100
    assert demand["priority"] == "Alta"
    assert demand["status"] == "PENDING_APPROVAL"


def test_case_03_ferja(client: TestClient) -> None:
    demand = _create(client, CASE_02.replace("Construjá", "Ferjá"))["demand"]

    assert demand["brand"] == "Ferjá"
    assert demand["audience"] == "Consumidor final"
    assert demand["cta"] == FERJA.mandatory_cta
    assert demand["cta"] != CONSTRUJA.mandatory_cta


def test_case_04_promotion_without_price(client: TestClient) -> None:
    view = _create(client, "Faz promoção da Krona.")

    assert view["demand"]["price"] is None
    assert view["next_action"] == "CONFIRM_TYPE"


def test_case_05_duplicate_returns_409(client: TestClient) -> None:
    first = _rid(_create(client, CASE_02))
    _post(client, f"/requests/{first}/approve")
    [existing] = client.get("/tasks").json()

    second = _create(client, CASE_02)
    assert second["demand"]["duplicate_of"]["task_id"] == existing["id"]

    response = client.post(f"/requests/{_rid(second)}/approve", json={})

    assert response.status_code == 409
    body = response.json()
    assert body["task"]["id"] == existing["id"]
    assert body["task"]["title"] == "Arte | Promoção Krona | Construjá"
    assert body["duplicate"]["criteria"] == ["same_brand_type_supplier", "similar_title"]
    assert len(client.get("/tasks").json()) == 1
    view = client.get(f"/requests/{_rid(second)}").json()
    assert view["demand"]["status"] == "PENDING_APPROVAL"
    assert view["audit"][-1]["action"] == "duplicate_found"


def test_case_05_force_new_creates_second_task(client: TestClient) -> None:
    first = _rid(_create(client, CASE_02))
    _post(client, f"/requests/{first}/approve")
    second = _rid(_create(client, CASE_02))

    view = _post(client, f"/requests/{second}/approve", {"force_new": True})

    assert view["demand"]["status"] == "TASK_CREATED"
    assert "duplicate_overridden" in [e["action"] for e in view["audit"]]
    assert len(client.get("/tasks").json()) == 2


def test_case_05_link_existing_cancels_request(client: TestClient) -> None:
    first = _rid(_create(client, CASE_02))
    _post(client, f"/requests/{first}/approve")
    [existing] = client.get("/tasks").json()
    second = _rid(_create(client, CASE_02))

    view = _post(client, f"/requests/{second}/link-existing", {"task_id": existing["id"]})

    assert view["demand"]["status"] == "CANCELLED"
    assert view["demand"]["external_task_id"] == existing["external_task_id"]
    assert view["audit"][-2]["action"] == "linked_to_existing"
    assert len(client.get("/tasks").json()) == 1
    missing = client.post(f"/requests/{_rid(_create(client, CASE_02))}/link-existing",
                          json={"task_id": 999999})  # fmt: skip
    assert missing.status_code == 404


def test_case_06_conversation_to_blocked_task(client: TestClient) -> None:
    """Caso 06: 100%; Alta; Designer A; dependência Compras; tarefa criada bloqueada."""
    rid = _rid(_create(client, "Preciso de uma arte da Krona para amanhã."))
    _post(client, f"/requests/{rid}/answers", {"message": "Construjá"})
    view = _post(
        client,
        f"/requests/{rid}/answers",
        {
            "message": "Instagram feed. São 3 produtos da planilha anexada. Promoção válida "
            "até sexta. Ainda aguardando aprovação de preço por Compras."
        },
    )

    demand = view["demand"]
    assert demand["briefing_score"] == 100
    assert demand["priority"] == "Alta"
    assert demand["assigned_to"] == "designer-a"
    assert demand["dependencies"] == [
        {"dependency": "Aprovação de preço", "owner": "Compras", "status": "Pendente"}
    ]

    approved = _post(client, f"/requests/{rid}/approve")

    assert approved["demand"]["status"] == "TASK_CREATED"
    [task] = client.get("/tasks").json()
    assert task["blocked"] is True
    assert task["assigned_to"] == "designer-a"
    assert "RESPONSÁVEL: Designer A" in task["briefing"]
    assert "DEPENDÊNCIAS: Aprovação de preço (Compras, Pendente)" in task["briefing"]


def test_triage_integration_from_message_to_pending_approval(client: TestClient) -> None:
    """D34: uma mensagem completa vai sozinha até PENDING_APPROVAL, com a triagem gravada."""
    view = _create(client, CASE_02)
    demand = view["demand"]

    transitions = [
        e["new_value"]["status"] for e in view["audit"] if e["action"] == "status_transition"
    ]
    assert transitions == [
        "PARSED",
        "VALIDATING",
        "READY_FOR_TRIAGE",
        "TRIAGED",
        "PENDING_APPROVAL",
    ]
    assert demand["status"] == "PENDING_APPROVAL"
    assert view["next_action"] == "AWAIT_APPROVAL"
    # prioridade, responsável, dependências e duplicidade gravados na demanda
    assert (demand["priority"], demand["priority_score"]) == ("Alta", 70.5)
    assert demand["assigned_to"] == "designer-a"
    assert demand["approver"] == CONFIG.task_types.approver_default
    assert demand["dependencies"] == []
    assert demand["duplicate_of"] is None
    actions = [e["action"] for e in view["audit"]]
    for action in ("priority_calculated", "assignment_calculated", "dependencies_checked",
                   "no_duplicate"):  # fmt: skip
        assert action in actions
    # e persistidos: a leitura seguinte devolve o mesmo
    assert client.get(f"/requests/{_rid(view)}").json()["demand"] == demand
