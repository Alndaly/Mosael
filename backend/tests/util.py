from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import Base, engine, init_db
from app.core.worker_key import WORKER_KEY_HEADER, current_worker_key, issue_worker_key
from app.main import app

PASSWORD = "pass1234"


def _assert_disposable_data_dir() -> None:
    """Refuse to drop_all unless the DB lives in a throwaway temp dir.

    conftest.py points MIBU_DATA_DIR at a mkdtemp() before anything imports settings — but
    conftest only loads under pytest. Calling these helpers directly (e.g. `python -c "from
    tests.util import fresh_client"`) would otherwise resolve to the REAL ~/.mibu-video and
    drop every table in the user's live database. Fail loudly instead of silently wiping it.
    """
    data_dir = Path(settings.data_dir).resolve()
    tmp_root = Path(tempfile.gettempdir()).resolve()
    in_tmp = data_dir == tmp_root or tmp_root in data_dir.parents
    if not os.environ.get("MIBU_DATA_DIR") or not in_tmp:
        raise RuntimeError(
            f"refusing to drop_all: data_dir={data_dir} is not a temp dir. "
            "Run tests through pytest (conftest.py sets MIBU_DATA_DIR); never call "
            "fresh_client() from an ad-hoc `python -c` against the real database."
        )


def fresh_client(username: str = "tester") -> TestClient:
    """Drop/recreate the isolated test DB and return a logged-in client.

    Also mints the publish-worker key. TestClient(app) does not run the lifespan (only the
    context-manager form does), so without this the worker channel has no key issued and every
    worker route answers 401 — correct behaviour for an unstarted backend, but not what a test
    exercising those routes means to assert.
    """
    _assert_disposable_data_dir()
    Base.metadata.drop_all(bind=engine)
    init_db()
    issue_worker_key()
    client = TestClient(app)
    login_as(client, username)
    return client


def worker_client() -> TestClient:
    """A client authenticated as the local publish worker rather than as a user."""
    client = TestClient(app)
    client.headers[WORKER_KEY_HEADER] = current_worker_key() or issue_worker_key()
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
