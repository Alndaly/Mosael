from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_health_supports_get_and_head() -> None:
    client = TestClient(app)

    get = client.get("/api/health")
    assert get.status_code == 200
    assert get.json() == {"status": "ok"}

    head = client.head("/api/health")
    assert head.status_code == 204
    assert head.content == b""
