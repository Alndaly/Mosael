"""官方账号:公开身份里的 `official`、注册不能自封、以及"它可以正常登录"。

**官方标记是公开信息**,所以它跟着 `display_name` / `handle` / `avatar_seed` 一起出现在
每个公开响应里;email 仍然只在 `/me` 这个"本人"形状里。官方号的密码由部署配置
(`CLOUD_OFFICIAL_PASSWORD`)决定,不是"永远登不上"的特殊账号。
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
#: 运维从环境变量 `CLOUD_OFFICIAL_PASSWORD` 交给种子命令的那个值;测试里直接传给种子函数。
OFFICIAL_PASSWORD = "Official-Horse-9"


def _seed_official_account(config, *, password: str = "") -> None:
    """只建官方账号(空 bundle)。密码是"部署时配的那一个",不配就没有。"""
    from cloud.official import seed_official

    seed_official(
        config.resolved_database_url,
        {"plugins": [], "workflows": []},
        password=password,
    )


def test_official_account_with_a_configured_password_can_log_in(client, config, db_path):
    """② 有密码 → 官方号就是**普通登录账号**:密码登录 200、拿到会话、`/me` 是本人。"""
    _seed_official_account(config, password=OFFICIAL_PASSWORD)

    response = client.post(
        api("/login"), json={"email": OFFICIAL_EMAIL, "password": OFFICIAL_PASSWORD}
    )
    assert response.status_code == 200, response.text
    user = response.json()["user"]
    assert user["email"] == OFFICIAL_EMAIL
    assert user["handle"] == "mosael"
    assert user["official"] is True

    me = client.get(api("/me"))
    assert me.status_code == 200, me.text
    assert me.json()["user"]["email"] == OFFICIAL_EMAIL
    assert me.json()["user"]["official"] is True
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_sessions") == 1


def test_official_account_with_a_configured_password_rejects_a_wrong_one(client, config, db_path):
    """② 可登录不等于免验证:密码错仍然是 401,不区分"官方号 / 密码错"。"""
    _seed_official_account(config, password=OFFICIAL_PASSWORD)

    response = client.post(api("/login"), json={"email": OFFICIAL_EMAIL, "password": PASSWORD})
    assert response.status_code == 401, response.text
    assert response.json()["error"] == "invalid_credentials"
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_sessions") == 0


def test_official_account_without_a_password_is_401_not_403(client, config, db_path):
    """② 没设密码 → 密码登录 401（不是 403）:别在响应里暴露"这是官方号"。"""
    _seed_official_account(config)

    response = client.post(api("/login"), json={"email": OFFICIAL_EMAIL, "password": PASSWORD})
    assert response.status_code == 401, response.text
    assert response.json()["error"] == "invalid_credentials"
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_sessions") == 0


def test_official_login_code_is_delivered_and_signs_in(client, config, db_path, sender):
    """② 官方号的登录验证码**恢复投递**;码换会话不再被 `open_session` 403。"""
    _seed_official_account(config, password=OFFICIAL_PASSWORD)

    response = client.post(api("/login/code"), json={"email": OFFICIAL_EMAIL})
    assert response.status_code == 200, response.text
    assert response.json() == {"sent": True}
    codes = sender.codes(OFFICIAL_EMAIL, "login")
    assert len(codes) == 1

    verify = client.post(
        api("/login/code/verify"), json={"email": OFFICIAL_EMAIL, "code": codes[0]}
    )
    assert verify.status_code == 200, verify.text
    assert verify.json()["user"]["official"] is True
    assert client.get(api("/me")).json()["user"]["email"] == OFFICIAL_EMAIL
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_sessions") == 1


def test_official_login_codes_are_rate_limited_like_any_account(client, config, sender):
    """②④ 官方号没有限流后门:同一邮箱的 60 秒冷却对它同样生效。"""
    _seed_official_account(config, password=OFFICIAL_PASSWORD)

    first = client.post(api("/login/code"), json={"email": OFFICIAL_EMAIL})
    assert first.status_code == 200, first.text
    second = client.post(api("/login/code"), json={"email": OFFICIAL_EMAIL})
    assert second.status_code == 429, second.text
    assert second.json()["error"] == "email_code_cooldown"
    assert len(sender.codes(OFFICIAL_EMAIL, "login")) == 1
