"""可选 TOTP 双因素:设置、登录挑战、恢复码、关闭。"""

from __future__ import annotations

import time

from conftest import PASSWORD, api, rows, signup
from cloud.mfa import normalize_recovery_code, totp_code


def enable_mfa(client) -> tuple[str, list[str]]:
    setup = client.post(api("/mfa/setup"))
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    enabled = client.post(api("/mfa/enable"), json={"code": totp_code(secret, step=int(time.time() // 30))})
    assert enabled.status_code == 200, enabled.text
    return secret, enabled.json()["recovery_codes"]


def login_challenge(client, email: str = "alice@example.com") -> dict:
    response = client.post(api("/login"), json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mfa_required"] is True
    assert "set-cookie" not in response.headers
    return body


def test_mfa_is_optional_and_a_totp_code_finishes_login(client):
    user = signup(client)
    assert user["mfa_enabled"] is False
    assert client.get(api("/mfa")).json() == {"enabled": False, "recovery_codes_remaining": 0}

    secret, recovery = enable_mfa(client)
    assert len(recovery) == 10
    assert client.get(api("/mfa")).json()["enabled"] is True

    client.post(api("/logout"))
    challenge = login_challenge(client)
    assert challenge["methods"] == ["totp", "recovery"]

    wrong = client.post(api("/mfa/verify"), json={"ticket": challenge["ticket"], "code": "000000"})
    assert wrong.status_code == 401
    assert wrong.json()["error"] == "mfa_code_invalid"

    code = totp_code(secret, step=int(time.time() // 30) + 1)
    done = client.post(api("/mfa/verify"), json={"ticket": challenge["ticket"], "code": code})
    assert done.status_code == 200, done.text
    assert done.json()["user"]["mfa_enabled"] is True
    assert client.get(api("/me")).status_code == 200


def test_a_recovery_code_works_once(client):
    signup(client)
    _, recovery = enable_mfa(client)
    client.post(api("/logout"))

    challenge = login_challenge(client)
    first = client.post(
        api("/mfa/verify"),
        json={"ticket": challenge["ticket"], "code": normalize_recovery_code(recovery[0])},
    )
    assert first.status_code == 200, first.text
    assert first.json()["user"]["mfa_enabled"] is True
    client.post(api("/logout"))

    challenge = login_challenge(client)
    replay = client.post(
        api("/mfa/verify"),
        json={"ticket": challenge["ticket"], "code": normalize_recovery_code(recovery[0])},
    )
    assert replay.status_code == 401
    assert replay.json()["error"] == "mfa_code_invalid"


def test_mfa_can_be_disabled_with_a_current_code(client):
    signup(client)
    secret, _ = enable_mfa(client)

    code = totp_code(secret, step=int(time.time() // 30) + 1)
    disabled = client.post(api("/mfa/disable"), json={"code": code})
    assert disabled.status_code == 200, disabled.text
    assert disabled.json() == {"enabled": False}
    assert client.get(api("/mfa")).json()["enabled"] is False

    client.post(api("/logout"))
    response = client.post(api("/login"), json={"email": "alice@example.com", "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json()["user"]["mfa_enabled"] is False
    assert "set-cookie" in response.headers


def test_email_code_login_also_requires_mfa(client, sender):
    signup(client)
    secret, _ = enable_mfa(client)
    client.post(api("/logout"))

    assert client.post(api("/login/code"), json={"email": "alice@example.com"}).status_code == 200
    code = sender.last_code("alice@example.com", "login")
    response = client.post(api("/login/code/verify"), json={"email": "alice@example.com", "code": code})
    assert response.status_code == 200, response.text
    assert response.json()["mfa_required"] is True

    done = client.post(
        api("/mfa/verify"),
        json={"ticket": response.json()["ticket"], "code": totp_code(secret, step=int(time.time() // 30) + 1)},
    )
    assert done.status_code == 200, done.text


def test_ticket_is_stored_as_a_hash_and_attempts_are_limited(client, db_path):
    signup(client)
    enable_mfa(client)
    client.post(api("/logout"))
    challenge = login_challenge(client)
    stored = [row[0] for row in rows(db_path, "SELECT ticket_hash FROM cloud_mfa_tickets")]
    assert challenge["ticket"] not in stored

    for _ in range(5):
        response = client.post(api("/mfa/verify"), json={"ticket": challenge["ticket"], "code": "000000"})
    assert response.status_code == 429
    assert response.json()["error"] == "mfa_attempts_exceeded"


def test_the_same_totp_step_cannot_be_replayed(client):
    signup(client)
    secret, _ = enable_mfa(client)
    client.post(api("/logout"))

    step = int(time.time() // 30) + 1
    code = totp_code(secret, step=step)
    first = login_challenge(client)
    assert client.post(api("/mfa/verify"), json={"ticket": first["ticket"], "code": code}).status_code == 200
    client.post(api("/logout"))

    second = login_challenge(client)
    replay = client.post(api("/mfa/verify"), json={"ticket": second["ticket"], "code": code})
    assert replay.status_code == 401
    assert replay.json()["error"] == "mfa_code_invalid"
