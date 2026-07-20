"""The publish-worker channel authenticates with a local-file secret.

It has no user session — the worker is an Electron process, not a person — and it was left open
on the reasoning that the backend only listens on 127.0.0.1. A browser does not respect that
boundary: any page the user visits can POST to 127.0.0.1:8800, and these routes required no
credential at all, so a page could claim publish tasks across every workspace, read account
proxy strings with credentials in them, and mark accounts as needing re-login.

What actually separates the worker from a web page is that it can read the local filesystem.
"""

from __future__ import annotations

import os
import stat

from app.core.worker_key import (
    WORKER_KEY_HEADER,
    current_worker_key,
    issue_worker_key,
    key_path,
    verify_worker_key,
)
from tests.util import fresh_client

WORKER_ROUTES = [
    ("post", "/api/publish/worker/claim", {"owner": "local"}),
    ("get", "/api/publish/worker/account/some-id", None),
]


def _call(client, method, path, body):
    return getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)


def test_a_caller_without_the_key_is_refused() -> None:
    """A web page can reach 127.0.0.1 but cannot read the key file."""
    issue_worker_key()
    client = fresh_client()
    del client.headers["Authorization"]  # the channel never used a user session anyway
    for method, path, body in WORKER_ROUTES:
        res = _call(client, method, path, body)
        assert res.status_code == 401, f"{method.upper()} {path} answered {res.status_code}"


def test_a_wrong_key_is_refused() -> None:
    issue_worker_key()
    client = fresh_client()
    client.headers[WORKER_KEY_HEADER] = "0" * 64
    for method, path, body in WORKER_ROUTES:
        assert _call(client, method, path, body).status_code == 401


def test_the_real_key_gets_through_the_gate() -> None:
    client = fresh_client()
    # TestClient(app) without a context manager does not run the lifespan, so mint it here.
    # That the gate refuses everything when no key has been issued is itself correct: an
    # unstarted backend should not have an open worker channel.
    key = issue_worker_key()
    client.headers[WORKER_KEY_HEADER] = key
    # Past the gate the route runs; a made-up account id is a 404, which is the point —
    # it is no longer a 401.
    assert client.get("/api/publish/worker/account/some-id").status_code != 401


def test_the_key_file_is_owner_only() -> None:
    """World-readable would defeat the whole mechanism — any local process could forge it."""
    issue_worker_key()
    mode = os.stat(key_path()).st_mode
    assert not mode & stat.S_IRGRP and not mode & stat.S_IROTH, oct(mode)
    assert not mode & stat.S_IWGRP and not mode & stat.S_IWOTH, oct(mode)


def test_the_file_matches_what_the_gate_expects() -> None:
    issue_worker_key()
    assert key_path().read_text().strip() == current_worker_key()


def test_a_key_from_a_previous_process_stops_working() -> None:
    """Rotating per process means a stale key fails closed rather than lingering."""
    old = issue_worker_key()
    new = issue_worker_key()
    assert old != new
    assert verify_worker_key(old) is False
    assert verify_worker_key(new) is True


def test_verification_rejects_empty_input() -> None:
    issue_worker_key()
    assert verify_worker_key(None) is False
    assert verify_worker_key("") is False
