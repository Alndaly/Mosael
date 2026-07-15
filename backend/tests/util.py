from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.db import Base, engine, init_db
from app.main import app

PASSWORD = "pass1234"


def fresh_client(username: str = "tester") -> TestClient:
    """Drop/recreate the isolated test DB and return a logged-in client."""
    Base.metadata.drop_all(bind=engine)
    init_db()
    client = TestClient(app)
    login_as(client, username)
    return client


def login_as(client: TestClient, username: str) -> dict:
    res = client.post("/api/auth/register", json={"username": username, "password": PASSWORD})
    if res.status_code == 409:
        res = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert res.status_code == 200, res.text
    payload = res.json()
    client.headers["Authorization"] = f"Bearer {payload['token']}"
    return payload["user"]


def second_client(username: str = "other") -> TestClient:
    """Another user against the same DB (no reset)."""
    client = TestClient(app)
    login_as(client, username)
    return client
