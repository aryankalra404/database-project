from fastapi.testclient import TestClient

import app.main as main


async def unavailable_database() -> None:
    raise ConnectionError("database unavailable")


def test_frontend_loads_when_database_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "open", unavailable_database)

    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "SAHVS" in response.text


def test_health_explains_missing_database(monkeypatch) -> None:
    monkeypatch.setattr(main.repository, "open", unavailable_database)

    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.get("/api/health")

    assert response.status_code == 503
    assert "Set DATABASE_URL" in response.json()["detail"]


def test_vercel_skips_localhost_database_when_url_is_missing(monkeypatch) -> None:
    open_attempted = False

    async def track_open() -> None:
        nonlocal open_attempted
        open_attempted = True

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(main.repository, "open", track_open)

    with TestClient(main.app, raise_server_exceptions=False) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert open_attempted is False
