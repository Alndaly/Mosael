"""GitHub / Google 登录:授权码 + PKCE(S256) + 一次性 state。

**绝不真连第三方**:provider 由 `conftest.FakeOAuthProvider` 注入,它像真 provider 一样校验
PKCE 与 redirect_uri。这里断言的是完整链路(code → token → userinfo → 会话)、三条邮箱规则,
以及每一种失败都把原因说清楚、且不把 provider 的原始报错给用户。
"""

from __future__ import annotations

import sqlite3
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from cloud.oauth import code_challenge
from conftest import api, execute, rows, scalar, signup, signed_in

REDIRECT_GITHUB = "https://mosael.test/api/cloud/v1/oauth/github/callback"
REDIRECT_GOOGLE = "https://mosael.test/api/cloud/v1/oauth/google/callback"


def start(client, provider: str = "github", *, locale: str = "en", from_: str = "login", follow: bool = False):
    return client.get(
        api(f"/oauth/{provider}/start?locale={locale}&from={from_}"),
        follow_redirects=follow,
    )


def start_flow(client, provider: str = "github", **kwargs) -> dict[str, list[str]]:
    response = start(client, provider, **kwargs)
    assert response.status_code == 302, response.text
    assert response.headers["location"].startswith(f"https://{provider}.test/authorize?"), response.text
    return parse_qs(urlsplit(response.headers["location"]).query)


def callback(client, provider: str, state: str, code: str = "", **extra: str):
    query = {"state": state, "code": code, **extra}
    return client.get(api(f"/oauth/{provider}/callback?{urlencode(query)}"), follow_redirects=False)


def assert_failure(response, code: str, *, page: str = "login", locale: str = "en") -> None:
    assert response.status_code == 302, response.text
    assert response.headers["location"] == f"https://mosael.test/{locale}/{page}?oauth_error={code}"
    assert "mosael_cloud_session=" not in response.headers.get("set-cookie", "")


def users_count(db_path) -> int:
    return scalar(db_path, "SELECT COUNT(*) FROM cloud_users")


def identities_count(db_path) -> int:
    return scalar(db_path, "SELECT COUNT(*) FROM cloud_identities")


# ---------------------------------------------------------------------------
# 配置 / 入口
# ---------------------------------------------------------------------------


def test_providers_endpoint_reports_configuration(client, oauth_client):
    unconfigured = client.get(api("/oauth/providers"))
    assert unconfigured.status_code == 200
    assert unconfigured.json() == {"providers": {"github": False, "google": False}}

    configured = oauth_client.get(api("/oauth/providers"))
    assert configured.json() == {"providers": {"github": True, "google": True}}


def test_unconfigured_provider_says_not_enabled_instead_of_pretending(client, db_path):
    response = start(client)
    assert_failure(response, "oauth_not_configured")
    assert scalar(db_path, "SELECT COUNT(*) FROM cloud_oauth_states") == 0

    # 语言与来源页都要回到用户点按钮的那一页。
    zh_signup = start(client, locale="zh", from_="signup")
    assert zh_signup.headers["location"] == (
        "https://mosael.test/zh/signup?oauth_error=oauth_not_configured"
    )


def test_start_redirects_with_pkce_and_callback_derived_from_public_url(oauth_client, oauth_providers):
    query = start_flow(oauth_client)
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [REDIRECT_GITHUB]
    assert query["state"][0]
    # 挑战是 43 字符的 base64url(不带 padding),不是把 verifier 明文送出去。
    assert len(query["code_challenge"][0]) == 43
    assert "=" not in query["code_challenge"][0]
    assert query["code_challenge"][0] != query["state"][0]
    assert oauth_providers["github"].authorize_calls[-1]["redirect_uri"] == REDIRECT_GITHUB

    google = start_flow(oauth_client, "google")
    assert google["redirect_uri"] == [REDIRECT_GOOGLE]


def test_start_sets_a_scoped_httponly_nonce_cookie(oauth_client):
    response = start(oauth_client)
    cookie = response.headers["set-cookie"]
    assert "mosael_cloud_oauth_state=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/api/cloud/v1" in cookie


# ---------------------------------------------------------------------------
# 全链路
# ---------------------------------------------------------------------------


def test_code_to_token_to_userinfo_then_existing_session_path_opens(oauth_client, oauth_providers, oauth_db_path):
    client = oauth_client
    query = start_flow(client)
    state = query["state"][0]
    code = oauth_providers["github"].issue_code(state)

    response = callback(client, "github", state, code)
    assert response.status_code == 302, response.text
    assert response.headers["location"] == "https://mosael.test/en/account?oauth=created"
    assert "mosael_cloud_session=" in response.headers["set-cookie"]
    assert oauth_providers["github"].exchange_calls[-1]["code"] == code
    assert oauth_providers["github"].userinfo_calls == 1

    me = client.get(api("/me"))
    assert me.status_code == 200, me.text
    assert me.json()["user"]["email"] == "alice@example.com"
    assert me.json()["user"]["email_verified_at"] is not None

    # 第三方新建的账号:邮箱已验证、没有密码(以后可走验证码登录),身份行指向它。
    assert scalar(oauth_db_path, "SELECT password_hash FROM cloud_users") is None
    assert scalar(oauth_db_path, "SELECT COUNT(*) FROM cloud_users") == 1
    assert rows(
        oauth_db_path,
        "SELECT provider, provider_user_id FROM cloud_identities",
    ) == [("github", "github-user-1")]
    # state 一次性消费。
    assert scalar(oauth_db_path, "SELECT used_at IS NOT NULL FROM cloud_oauth_states") == 1

    # 没有密码:密码登录明确失败,但邮箱验证码那条路能进 —— 这正是"随时可补一种登录方式"。
    denied = client.post(api("/login"), json={"email": "alice@example.com", "password": "Some-Password-1"})
    assert denied.status_code == 401
    assert denied.json()["error"] == "invalid_credentials"

    from conftest import login_code

    assert login_code(client, email="alice@example.com")["email"] == "alice@example.com"


def test_state_mismatch_and_replay_are_refused(oauth_client, oauth_providers, oauth_db_path):
    client = oauth_client

    # 第一次:拿一个不存在的 state。失败会清掉 nonce cookie,所以下面重新发起一次。
    state = start_flow(client)["state"][0]
    assert_failure(
        callback(client, "github", "not-the-state", oauth_providers["github"].issue_code(state)),
        "oauth_state_invalid",
    )
    assert users_count(oauth_db_path) == 0

    # 第二次:走通,然后拿同一个 state 再放一遍 —— 已被消费。
    state = start_flow(client)["state"][0]
    code = oauth_providers["github"].issue_code(state)
    response = callback(client, "github", state, code)
    assert response.headers["location"] == "https://mosael.test/en/account?oauth=created"
    assert users_count(oauth_db_path) == 1
    assert_failure(callback(client, "github", state, code), "oauth_state_invalid")


def test_nonce_cookie_is_required(oauth_client, oauth_providers, oauth_db_path):
    client = oauth_client
    query = start_flow(client)
    state = query["state"][0]
    code = oauth_providers["github"].issue_code(state)
    client.cookies.delete("mosael_cloud_oauth_state")

    assert_failure(callback(client, "github", state, code), "oauth_state_invalid")
    assert users_count(oauth_db_path) == 0


def test_pkce_mismatch_is_refused(oauth_client, oauth_providers, oauth_db_path):
    client = oauth_client
    query = start_flow(client)
    state = query["state"][0]
    code = oauth_providers["github"].issue_code(state)

    # 模拟库里存的 verifier 与 provider 在 authorize 时收到的 challenge 对不上。
    execute(
        oauth_db_path,
        "UPDATE cloud_oauth_states SET code_verifier = ?",
        ("not-the-verifier-that-made-that-challenge",),
    )
    assert_failure(callback(client, "github", state, code), "oauth_code_rejected")
    assert users_count(oauth_db_path) == 0
    assert scalar(oauth_db_path, "SELECT used_at IS NOT NULL FROM cloud_oauth_states") == 1


# ---------------------------------------------------------------------------
# 邮箱规则
# ---------------------------------------------------------------------------


def test_unverified_email_is_refused_with_a_reason(oauth_client, oauth_providers, oauth_db_path):
    oauth_providers["github"].email_verified = False
    state = start_flow(oauth_client)["state"][0]
    response = callback(oauth_client, "github", state, oauth_providers["github"].issue_code(state))
    assert_failure(response, "oauth_email_unverified")
    assert users_count(oauth_db_path) == 0
    assert identities_count(oauth_db_path) == 0


def test_missing_email_is_refused(oauth_client, oauth_providers, oauth_db_path):
    oauth_providers["github"].email = ""
    state = start_flow(oauth_client)["state"][0]
    assert_failure(
        callback(oauth_client, "github", state, oauth_providers["github"].issue_code(state)),
        "oauth_email_unverified",
    )
    assert users_count(oauth_db_path) == 0


def test_existing_email_binds_to_the_existing_account_without_duplicating_it(
    oauth_client, oauth_providers, oauth_db_path
):
    existing = signup(oauth_client, email="alice@example.com")
    password_hash = scalar(oauth_db_path, "SELECT password_hash FROM cloud_users")

    state = start_flow(oauth_client)["state"][0]
    response = callback(oauth_client, "github", state, oauth_providers["github"].issue_code(state))
    assert response.status_code == 302
    assert response.headers["location"] == "https://mosael.test/en/account?oauth=existing"

    assert users_count(oauth_db_path) == 1
    assert scalar(
        oauth_db_path,
        "SELECT cloud_user_id FROM cloud_identities WHERE provider = 'github'",
    ) == existing["id"]
    # 旧账号的密码和邮箱一个字都没动。
    assert scalar(oauth_db_path, "SELECT password_hash FROM cloud_users") == password_hash
    assert scalar(oauth_db_path, "SELECT email FROM cloud_users") == "alice@example.com"
    assert oauth_client.get(api("/me")).json()["user"]["id"] == existing["id"]


def test_identity_whose_verified_email_belongs_to_another_account_is_a_conflict(
    oauth_client, oauth_providers, oauth_db_path
):
    # GitHub 身份先绑到 bob 的账号。
    oauth_providers["github"].email = "bob@example.com"
    state = start_flow(oauth_client)["state"][0]
    created = callback(oauth_client, "github", state, oauth_providers["github"].issue_code(state))
    assert created.headers["location"] == "https://mosael.test/en/account?oauth=created"
    bob_id = scalar(oauth_db_path, "SELECT cloud_user_id FROM cloud_identities")

    # 另有一个 alice 的账号(注册即登录),清掉它的会话,按"未登录"再走一次。
    signup(oauth_client, email="alice@example.com")
    oauth_client.cookies.delete("mosael_cloud_session")
    oauth_providers["github"].email = "alice@example.com"
    state = start_flow(oauth_client)["state"][0]
    assert_failure(
        callback(oauth_client, "github", state, oauth_providers["github"].issue_code(state)),
        "oauth_identity_conflict",
    )
    assert scalar(oauth_db_path, "SELECT cloud_user_id FROM cloud_identities") == bob_id
    assert identities_count(oauth_db_path) == 1


def test_same_provider_identity_cannot_be_linked_to_another_signed_in_account(
    oauth_client, oauth_providers, oauth_db_path
):
    # 先用 GitHub 建 bob 的账号(身份 github-user-1 指向它)。
    oauth_providers["github"].email = "bob@example.com"
    state = start_flow(oauth_client)["state"][0]
    created = callback(oauth_client, "github", state, oauth_providers["github"].issue_code(state))
    assert created.headers["location"] == "https://mosael.test/en/account?oauth=created"
    bob_id = scalar(oauth_db_path, "SELECT cloud_user_id FROM cloud_identities")

    # 再以 alice 登录,然后试图把这个已属于 bob 的 GitHub 身份绑到 alice 名下。
    signed_in(oauth_client, email="alice@example.com")
    assert oauth_client.get(api("/me")).json()["user"]["email"] == "alice@example.com"

    state = start_flow(oauth_client)["state"][0]
    assert_failure(
        callback(oauth_client, "github", state, oauth_providers["github"].issue_code(state)),
        "oauth_identity_conflict",
    )
    assert scalar(oauth_db_path, "SELECT cloud_user_id FROM cloud_identities") == bob_id
    # 冲突不踢掉当前会话。
    assert oauth_client.get(api("/me")).json()["user"]["email"] == "alice@example.com"


def test_one_account_can_bind_several_providers(oauth_client, oauth_providers, oauth_db_path):
    user = signed_in(oauth_client, email="alice@example.com")
    oauth_providers["github"].email = "alice@example.com"
    oauth_providers["google"].email = "alice@example.com"

    for provider in ("github", "google"):
        state = start_flow(oauth_client, provider)["state"][0]
        response = callback(
            oauth_client,
            provider,
            state,
            oauth_providers[provider].issue_code(state),
        )
        assert response.headers["location"] == "https://mosael.test/en/account?oauth=existing"

    assert users_count(oauth_db_path) == 1
    assert identities_count(oauth_db_path) == 2
    assert {
        row[0]
        for row in rows(oauth_db_path, "SELECT cloud_user_id FROM cloud_identities")
    } == {user["id"]}


# ---------------------------------------------------------------------------
# 失败路径
# ---------------------------------------------------------------------------


def test_user_denied_authorization_is_reported(oauth_client, oauth_providers, oauth_db_path):
    state = start_flow(oauth_client)["state"][0]
    assert_failure(
        callback(oauth_client, "github", state, error="access_denied"),
        "oauth_denied",
    )
    assert users_count(oauth_db_path) == 0


def test_missing_code_is_reported(oauth_client):
    state = start_flow(oauth_client)["state"][0]
    assert_failure(callback(oauth_client, "github", state), "oauth_callback_invalid")


def test_provider_errors_are_not_passed_through_to_the_redirect(oauth_client, oauth_providers):
    oauth_providers["github"].fail_exchange = "server_error"
    state = start_flow(oauth_client)["state"][0]
    response = callback(oauth_client, "github", state, oauth_providers["github"].issue_code(state))
    assert_failure(response, "oauth_provider_error")
    assert "raw provider detail" not in response.headers["location"]

    oauth_providers["github"].fail_exchange = ""
    oauth_providers["github"].fail_userinfo = "server_error"
    state = start_flow(oauth_client)["state"][0]
    response = callback(oauth_client, "github", state, oauth_providers["github"].issue_code(state))
    assert_failure(response, "oauth_provider_error")
    assert "raw userinfo detail" not in response.headers["location"]


def test_failure_redirects_back_to_signup_when_started_there(oauth_client, oauth_providers):
    state = start_flow(oauth_client, locale="zh", from_="signup")["state"][0]
    response = callback(oauth_client, "github", state, "unknown-code")
    assert_failure(response, "oauth_code_rejected", page="signup", locale="zh")


# ---------------------------------------------------------------------------
# 库形状
# ---------------------------------------------------------------------------


def test_identities_are_unique_per_provider_and_raw_oauth_tokens_never_land_in_the_database(
    oauth_client, oauth_providers, oauth_db_path
):
    state = start_flow(oauth_client)["state"][0]
    code = oauth_providers["github"].issue_code(state)
    created = callback(oauth_client, "github", state, code)
    assert created.headers["location"] == "https://mosael.test/en/account?oauth=created"

    with sqlite3.connect(oauth_db_path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert {"cloud_identities", "cloud_oauth_states"} <= tables
        index_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(cloud_identities)")
        }
        assert index_columns == {"id", "provider", "provider_user_id", "cloud_user_id", "created_at"}
        # 原始 access token / 授权码 / state / verifier 都不该落库。
        dump = "\n".join(
            str(row)
            for table in tables
            if table.startswith("cloud_")
            for row in connection.execute(f"SELECT * FROM {table}")
        )
    assert "access-token-for" not in dump
    assert code not in dump
    assert state not in dump

    # 唯一约束在库上,而不只是应用层判断。
    with sqlite3.connect(oauth_db_path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO cloud_identities (id, provider, provider_user_id, cloud_user_id, created_at) "
                "SELECT 'dup', provider, provider_user_id, cloud_user_id, created_at FROM cloud_identities"
            )


# ---------------------------------------------------------------------------
# 真 provider 适配器:只测 URL / PKCE / 邮箱判定,不发任何网络请求
# ---------------------------------------------------------------------------


def test_pkce_s256_matches_the_rfc7636_reference_vector():
    # RFC 7636 附录 B 的固定向量。算错的话真 provider 一定拒,这里先钉住。
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_real_provider_authorize_urls_carry_pkce_and_the_derived_callback(oauth_config):
    from urllib.parse import parse_qs, urlsplit

    from cloud.oauth import GitHubProvider, GoogleProvider

    state = "state-123"
    challenge = code_challenge("verifier-" + "x" * 40)

    github = parse_qs(urlsplit(
        GitHubProvider().authorize_url(
            config=oauth_config,
            redirect_uri=REDIRECT_GITHUB,
            state=state,
            code_challenge=challenge,
        )
    ).query)
    assert github["client_id"] == ["fake-github-client"]
    assert github["redirect_uri"] == [REDIRECT_GITHUB]
    assert github["scope"] == ["read:user user:email"]
    assert github["code_challenge_method"] == ["S256"]
    assert github["code_challenge"] == [challenge]
    assert github["state"] == [state]

    google = parse_qs(urlsplit(
        GoogleProvider().authorize_url(
            config=oauth_config,
            redirect_uri=REDIRECT_GOOGLE,
            state=state,
            code_challenge=challenge,
        )
    ).query)
    assert google["client_id"] == ["fake-google-client"]
    assert google["redirect_uri"] == [REDIRECT_GOOGLE]
    assert google["scope"] == ["openid email profile"]
    assert google["response_type"] == ["code"]
    assert google["code_challenge_method"] == ["S256"]
    assert google["code_challenge"] == [challenge]


def test_github_identity_only_uses_a_verified_email_and_prefers_the_primary(monkeypatch):
    import cloud.oauth as oauth_module

    def fake_get_json(url, headers):
        if url == oauth_module.GitHubProvider.USER_URL:
            return {"id": 42, "login": "octocat", "name": "The Octocat"}
        return [
            {"email": "Old@Example.com", "primary": False, "verified": True},
            {"email": "Primary@Example.com", "primary": True, "verified": True},
            {"email": "unverified@example.com", "primary": False, "verified": False},
        ]

    monkeypatch.setattr(oauth_module, "_get_json", fake_get_json)
    identity = oauth_module.GitHubProvider().fetch_identity(config=None, access_token="token")
    assert identity.provider_user_id == "42"
    assert identity.email == "primary@example.com"
    assert identity.email_verified is True

    def only_unverified(url, headers):
        if url == oauth_module.GitHubProvider.USER_URL:
            return {"id": 43, "login": "octocat"}
        return [{"email": "unverified@example.com", "primary": True, "verified": False}]

    monkeypatch.setattr(oauth_module, "_get_json", only_unverified)
    identity = oauth_module.GitHubProvider().fetch_identity(config=None, access_token="token")
    assert identity.email == ""
    assert identity.email_verified is False


def test_google_identity_requires_email_verified_true(monkeypatch):
    import cloud.oauth as oauth_module

    def profile(value):
        def fake_get_json(url, headers):
            return {"sub": "google-sub-1", "email": "Alice@Example.com", "email_verified": value}
        return fake_get_json

    monkeypatch.setattr(oauth_module, "_get_json", profile(True))
    identity = oauth_module.GoogleProvider().fetch_identity(config=None, access_token="token")
    assert identity.provider_user_id == "google-sub-1"
    assert identity.email == "alice@example.com"
    assert identity.email_verified is True

    monkeypatch.setattr(oauth_module, "_get_json", profile(False))
    identity = oauth_module.GoogleProvider().fetch_identity(config=None, access_token="token")
    assert identity.email_verified is False
