"""GET /requests/{id}/messages (T18, D39): histórico do chat para o frontend (§13, tela 1)."""

import uuid
from typing import Any

from fastapi.testclient import TestClient

CASE_06_FIRST = "Preciso de uma arte da Krona para amanhã."


def _create(client: TestClient, message: str) -> dict[str, Any]:
    body = {"requester_name": "Ana", "department": "Comercial", "channel": "chat"}
    response = client.post("/requests", json={**body, "message": message})
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


def test_messages_list_requester_and_assistant_turns_in_order(client: TestClient) -> None:
    view = _create(client, CASE_06_FIRST)
    request_id = view["demand"]["request_id"]
    client.post(f"/requests/{request_id}/answers", json={"message": "Construjá"})

    response = client.get(f"/requests/{request_id}/messages")

    assert response.status_code == 200
    messages = response.json()
    assert [m["role"] for m in messages] == ["requester", "assistant", "requester", "assistant"]
    assert messages[0]["text"] == CASE_06_FIRST
    assert messages[2]["text"] == "Construjá"
    # O texto do assistente são as perguntas da vez, como a API gravou (D36).
    assert messages[1]["text"]
    assert all({"id", "role", "text", "created_at"} <= set(m) for m in messages)


def test_messages_of_unknown_request_is_404(client: TestClient) -> None:
    response = client.get(f"/requests/{uuid.uuid4()}/messages")

    assert response.status_code == 404


def test_messages_route_does_not_write_audit(client: TestClient) -> None:
    view = _create(client, CASE_06_FIRST)
    request_id = view["demand"]["request_id"]
    before = len(client.get(f"/requests/{request_id}").json()["audit"])

    client.get(f"/requests/{request_id}/messages")

    assert len(client.get(f"/requests/{request_id}").json()["audit"]) == before
