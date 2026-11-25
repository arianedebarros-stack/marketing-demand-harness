"""GET /audit (T19, D40): o Registro (§13, tela 5) e o título na RequestView (Approval Gate)."""

import uuid
from typing import Any

from fastapi.testclient import TestClient

CASE_01 = "Faz uma arte da Krona."
CASE_02 = (
    "Preciso de um feed 1080x1350 da Construjá para divulgar a promoção Krona amanhã. "
    "Os produtos e preços estão na planilha anexada e a promoção vale até sexta."
)


def _create(client: TestClient, message: str) -> dict[str, Any]:
    body = {"requester_name": "Ana", "department": "Comercial", "channel": "chat"}
    response = client.post("/requests", json={**body, "message": message})
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


def _id(view: dict[str, Any]) -> str:
    return str(view["demand"]["request_id"])


def test_audit_lists_every_request_newest_first(client: TestClient) -> None:
    first = _create(client, CASE_01)
    second = _create(client, CASE_02)

    response = client.get("/audit")

    assert response.status_code == 200
    entries = response.json()
    ids = [e["id"] for e in entries]
    assert ids == sorted(ids, reverse=True)
    assert {e["request_id"] for e in entries} == {_id(first), _id(second)}
    assert len(entries) == len(first["audit"]) + len(second["audit"])
    assert {"id", "request_id", "task_id", "actor", "action", "timestamp"} <= set(entries[0])


def test_audit_filters_by_request(client: TestClient) -> None:
    first = _create(client, CASE_01)
    _create(client, CASE_02)

    entries = client.get("/audit", params={"request_id": _id(first)}).json()

    assert [e["id"] for e in entries] == [e["id"] for e in reversed(first["audit"])]


def test_audit_includes_task_events(client: TestClient) -> None:
    request_id = _id(_create(client, CASE_02))
    client.post(f"/requests/{request_id}/approve", json={})
    [task] = client.get("/tasks").json()
    client.post(f"/tasks/{task['id']}/complete")

    entries = client.get("/audit", params={"request_id": request_id}).json()

    assert entries[0]["action"] == "task_completed"
    assert entries[0]["task_id"] == task["id"]


def test_audit_limit_and_cursor(client: TestClient) -> None:
    _create(client, CASE_01)
    everything = client.get("/audit").json()

    page = client.get("/audit", params={"limit": 3}).json()
    rest = client.get("/audit", params={"before": page[-1]["id"]}).json()

    assert page == everything[:3]
    assert rest == everything[3:]


def test_audit_invalid_params_are_422(client: TestClient) -> None:
    assert client.get("/audit", params={"limit": 0}).status_code == 422
    assert client.get("/audit", params={"limit": 1001}).status_code == 422
    assert client.get("/audit", params={"request_id": "x"}).status_code == 422


def test_audit_unknown_request_is_empty(client: TestClient) -> None:
    response = client.get("/audit", params={"request_id": str(uuid.uuid4())})

    assert response.status_code == 200
    assert response.json() == []


def test_audit_route_does_not_write_audit(client: TestClient) -> None:
    _create(client, CASE_01)
    before = len(client.get("/audit").json())

    client.get("/audit")

    assert len(client.get("/audit").json()) == before


# --- Título na RequestView (Approval Gate, §13 tela 3) ---------------------------------------


def test_request_view_carries_title_from_briefing_engine(client: TestClient) -> None:
    view = _create(client, CASE_02)

    assert view["title"] == "Arte | Promoção Krona | Construjá"
    assert client.get(f"/requests/{_id(view)}").json()["title"] == view["title"]


def test_title_matches_created_task(client: TestClient) -> None:
    request_id = _id(_create(client, CASE_02))

    view = client.post(f"/requests/{request_id}/approve", json={}).json()

    [task] = client.get("/tasks").json()
    assert view["title"] == task["title"]
