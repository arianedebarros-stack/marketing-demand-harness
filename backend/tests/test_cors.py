"""CORS para o frontend (T18, D39): o navegador em :3000 chama a API em :8000."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app

FRONTEND = "http://localhost:3000"


def _preflight(client: TestClient, origin: str) -> dict[str, str]:
    response = client.options(
        "/requests",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    return dict(response.headers)


def test_frontend_origin_is_allowed() -> None:
    headers = _preflight(TestClient(app), FRONTEND)

    assert headers.get("access-control-allow-origin") == FRONTEND
    assert "POST" in headers.get("access-control-allow-methods", "")
    assert "PATCH" in headers.get("access-control-allow-methods", "")


def test_other_origin_is_not_allowed() -> None:
    headers = _preflight(TestClient(app), "http://evil.example")

    assert "access-control-allow-origin" not in headers


def test_simple_get_from_frontend_has_cors_header() -> None:
    response = TestClient(app).get("/health", headers={"Origin": FRONTEND})

    assert response.headers.get("access-control-allow-origin") == FRONTEND


def test_cors_origins_default_is_local_frontend() -> None:
    assert Settings(_env_file=None).cors_origin_list == [FRONTEND]


def test_cors_origins_accepts_comma_separated_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", " http://localhost:3000 , https://mkt.example ,")

    assert Settings(_env_file=None).cors_origin_list == [FRONTEND, "https://mkt.example"]
