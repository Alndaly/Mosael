"""身份:昵称 / 短名 / 头像种子,以及"注册即登录"。

身份是**可选的账号状态**:注册不填,第一次发布 / 评论时才要。这里钉住校验、唯一性、保留字,
以及公开响应只出三列这件事(那条扫描在 test_shares.py 里跨接口做)。
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from conftest import api, request_signup_code, scalar, signup

from community_helpers import identity_body, make_identity

HANDLE_RE = re.compile(r"^[a-z0-9_-]{1,24}$")


def test_signup_is_immediately_signed_in(client, db_path):
    """E:注册成功即登录。响应直接带会话 cookie,紧接着 GET /me 就是 200。"""
    code = request_signup_code(client)
    response = client.post(
        api("/signup"),
        json={"email": "alice@example.com", "code": code, "password": "Correct-Horse-9"},
    )
    assert response.status_code == 201, response.text
    assert "mosael_cloud_session=" in response.headers.get("set-cookie", "")

    me = client.get(api("/me"))
    assert me.status_code == 200, me.text
    assert me.json()["user"]["email"] == "alice@example.com"
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_sessions") == 1


def test_put_me_sets_name_and_derives_handle_and_avatar_seed(client, db_path):
    signup(client)

    # 注册时没有身份:三列都是空。
    before = client.get(api("/me")).json()["user"]
    # 注册已经给了一个默认身份(默认昵称 = 默认短名),不再是从 NULL 开始。
    assert before["display_name"], "注册后应当已经有默认昵称"
    assert before["handle"] and HANDLE_RE.fullmatch(before["handle"]), before["handle"]
    assert before["avatar_seed"], "注册后也应当有头像种子(自动色块要有东西算)"

    updated = client.put(api("/me"), json=identity_body("Alice"))
    assert updated.status_code == 200, updated.text
    user = updated.json()["user"]
    assert user["display_name"] == "Alice"
    assert HANDLE_RE.fullmatch(user["handle"]), user["handle"]
    assert 1 <= len(user["avatar_seed"]) <= 16

    # 落库的是同样的三列;email 仍是账号自己的。
    assert scalar(db_path, "SELECT display_name FROM cloud_users") == "Alice"
    assert scalar(db_path, "SELECT handle FROM cloud_users") == user["handle"]


def test_explicit_handle_is_normalized_and_avatar_seed_is_stable(client):
    signup(client)
    first = client.put(api("/me"), json={"display_name": "Alice", "handle": "Alice-01"}).json()["user"]
    assert first["handle"] == "alice-01"
    seed = first["avatar_seed"]

    again = client.put(api("/me"), json={"display_name": "Alice Cooper"}).json()["user"]
    assert again["avatar_seed"] == seed
    assert again["handle"] == "alice-01"


def test_handle_must_use_only_lowercase_letters_digits_hyphen_underscore(client):
    signup(client)
    for bad in ("has space", "sla/sh", "dot.name", "ünicode", "x" * 25):
        response = client.put(api("/me"), json=identity_body("Alice", bad))
        assert response.status_code == 422, (bad, response.text)
        assert response.json()["error"] == "handle_invalid"


def test_reserved_handles_are_409(client):
    signup(client)
    for reserved in ("admin", "api", "u", "me", "users"):
        response = client.put(api("/me"), json=identity_body("Alice", reserved))
        assert response.status_code == 409, (reserved, response.text)
        assert response.json()["error"] == "handle_reserved"
        assert response.json()["message"]["zh"] and response.json()["message"]["en"]


def test_handle_conflict_is_409_with_a_human_message(client, app):
    signup(client, email="alice@example.com")
    make_identity(client, "Alice", "shared-name")

    other = TestClient(app)
    try:
        signup(other, email="bob@example.com")
        response = other.put(api("/me"), json=identity_body("Bob", "shared-name"))
        assert response.status_code == 409, response.text
        assert response.json()["error"] == "handle_taken"
        assert response.json()["message"]["zh"] and response.json()["message"]["en"]
    finally:
        other.close()


def test_display_name_must_be_non_empty_and_bounded(client):
    signup(client)
    empty = client.put(api("/me"), json=identity_body("   "))
    assert empty.status_code == 422
    assert empty.json()["error"] == "display_name_required"

    too_long = client.put(api("/me"), json=identity_body("x" * 41))
    assert too_long.status_code == 422
    assert too_long.json()["error"] == "display_name_too_long"


def test_put_me_requires_a_session(client):
    response = client.put(api("/me"), json=identity_body("Alice"))
    assert response.status_code == 401
    assert response.json()["error"] == "not_authenticated"
