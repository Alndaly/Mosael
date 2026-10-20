"""官方账号:公开身份里的 `official`,注册不能自封,以及种子 / 登录闸(③④ 在后面的用例里)。

**官方标记是公开信息**,所以它跟着 `display_name` / `handle` / `avatar_seed` 一起出现在
每个公开响应里;email 仍然只在 `/me` 这个"本人"形状里。
"""

from __future__ import annotations

from conftest import PASSWORD, api, execute, request_signup_code, scalar, signup

from community_helpers import leaves, make_identity, publish_ok


def test_public_identity_carries_official_for_normal_users_false(client, db_path):
    """② 公开 author 带上 official;普通账号是 false。"""
    signup(client)
    make_identity(client, "Alice", "alice")
    share = publish_ok(client)

    assert share["author"] == {
        "display_name": "Alice",
        "handle": "alice",
        "avatar_seed": share["author"]["avatar_seed"],
        "official": False,
    }

    # 部署脚本(种子命令)是唯一会写 true 的地方;这里直接改库模拟"官方号已建好"。
    execute(db_path, "UPDATE cloud_users SET official = 1 WHERE handle = 'alice'")

    listed = client.get(api("/shares")).json()["items"][0]
    assert listed["author"]["official"] is True
    detail = client.get(api(f"/shares/{share['id']}")).json()
    assert detail["author"]["official"] is True
    # 本人形状也从同一份 public_user 里继承,不需要第二处判断。
    assert client.get(api("/me")).json()["user"]["official"] is True


def test_public_responses_with_an_official_author_still_hide_the_email(client, db_path):
    """② official 是公开信息,email 不是:扫描每个公开响应,官方号也一样。"""
    signup(client, email="alice@example.com")
    make_identity(client, "Alice", "alice")
    share = publish_ok(client)
    client.post(api(f"/shares/{share['id']}/comments"), json={"body": "hello"})
    execute(db_path, "UPDATE cloud_users SET official = 1 WHERE handle = 'alice'")

    for response in (
        client.get(api("/shares")),
        client.get(api(f"/shares/{share['id']}")),
        client.get(api(f"/shares/{share['id']}/comments")),
        client.get(api("/users/alice/shares")),
    ):
        assert response.status_code == 200, response.text
        for path, value in leaves(response.json()):
            assert not any(part == "email" for part in path.replace("[", ".").replace("]", "").split(".")), path
            assert "alice@example.com" not in str(value), path


def test_signup_cannot_make_itself_official(client, db_path):
    """② 注册请求里塞 `official: true` 没有用;`PUT /me` 也不能改。"""
    code = request_signup_code(client, "bob@example.com")
    response = client.post(
        api("/signup"),
        json={
            "email": "bob@example.com",
            "code": code,
            "password": PASSWORD,
            "official": True,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["user"]["official"] is False
    assert scalar(db_path, "SELECT official FROM cloud_users WHERE email = 'bob@example.com'") == 0

    assert client.get(api("/me")).json()["user"]["official"] is False

    updated = client.put(api("/me"), json={"display_name": "Bob", "official": True})
    assert updated.status_code == 200, updated.text
    assert updated.json()["user"]["official"] is False
    assert scalar(db_path, "SELECT official FROM cloud_users WHERE email = 'bob@example.com'") == 0


OFFICIAL_EMAIL = "official@mosael.example"


def _seed_official_account(config) -> None:
    """只建官方账号(空 bundle)。④ 关心的是这个账号怎么被挡在登录之外。"""
    from cloud.official import seed_official

    seed_official(config.resolved_database_url, {"plugins": [], "workflows": []})


def test_official_account_has_no_password_to_log_in_with(client, config, db_path):
    """④ 没设密码 → 密码登录那条路对官方号永远是 401;不会发出会话。"""
    _seed_official_account(config)

    response = client.post(api("/login"), json={"email": OFFICIAL_EMAIL, "password": PASSWORD})
    assert response.status_code == 401, response.text
    assert response.json()["error"] == "invalid_credentials"
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_sessions") == 0


def test_official_account_gets_no_login_code_and_no_session(client, config, db_path, sender):
    """④ 发码接口照常回 `sent`,但**不投递**;就算码泄露了,也换不到会话。"""
    _seed_official_account(config)

    response = client.post(api("/login/code"), json={"email": OFFICIAL_EMAIL})
    assert response.status_code == 200, response.text
    assert response.json() == {"sent": True}
    # 与"未注册邮箱"完全同一句响应,但一封都不发: .invalid 域也永远收不到。
    assert sender.codes(OFFICIAL_EMAIL, "login") == []

    # 最坏情况:有人拿到了一个对得上的码(这里直接按真实哈希格式塞一行)。
    # 唯一发会话的入口 `open_session` 仍然拒绝官方账号。
    from datetime import UTC, datetime, timedelta

    from cloud.security import email_code_digest

    code = "424242"
    created = datetime.now(UTC).replace(tzinfo=None)
    execute(
        db_path,
        "INSERT INTO cloud_email_codes (id, email, purpose, code_hash, attempts, request_ip, created_at, expires_at) "
        "VALUES ('leaked', ?, 'login', ?, 0, '203.0.113.9', ?, ?)",
        (
            OFFICIAL_EMAIL,
            email_code_digest(OFFICIAL_EMAIL, "login", code),
            created.strftime("%Y-%m-%d %H:%M:%S.%f"),
            (created + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S.%f"),
        ),
    )
    verify = client.post(api("/login/code/verify"), json={"email": OFFICIAL_EMAIL, "code": code})
    assert verify.status_code == 403, verify.text
    assert verify.json()["error"] == "official_account_cannot_sign_in"
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_sessions") == 0
