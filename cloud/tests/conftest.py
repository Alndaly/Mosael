"""MosaelCloud 的测试底座:每个测试一个临时数据目录、一个自己的 SQLite 库、不连外网。

`create_app(config)` 是显式工厂 —— 生产入口(`cloud.main:app`)才从环境变量读配置。测试因此可以
同时起好几个互不相干的 Cloud 实例(两套身份隔离那条用例需要)。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import urlencode

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from cloud.app import create_app
from cloud.config import CloudConfig
from cloud.oauth import OAuthProviderError, ProviderIdentity, code_challenge

API = "/api/cloud/v1"
PASSWORD = "Correct-Horse-9"


def api(path: str) -> str:
    return f"{API}{path}"


class RecordingSender:
    """测试用的假发信器:**绝不真发**。

    它记下"发给了谁、什么码",测试因此既能断言投递对象,又能拿到码走完注册 / 登录 ——
    不需要 Mailpit,也不需要外网。
    """

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def ensure_ready(self) -> None:
        """假 sender 永远"配置好了" —— 测试不依赖 SMTP 环境。"""

    def send_code(self, *, email: str, purpose: str, code: str) -> None:
        self.sent.append({"email": email, "purpose": purpose, "code": code})

    def codes(self, email: str, purpose: str) -> list[str]:
        return [
            item["code"]
            for item in self.sent
            if item["email"] == email and item["purpose"] == purpose
        ]

    def last_code(self, email: str, purpose: str) -> str:
        found = self.codes(email, purpose)
        assert found, f"没有向 {email} 发过 {purpose} 验证码"
        return found[-1]


class RecordingSmsSender:
    """测试用假短信发送器:**绝不真发**。"""

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def ensure_ready(self) -> None:
        """假 sender 永远可用。"""

    def send_code(self, *, phone: str, purpose: str, code: str) -> None:
        self.sent.append({"phone": phone, "purpose": purpose, "code": code})

    def last_code(self, phone: str, purpose: str) -> str:
        found = [item["code"] for item in self.sent if item["phone"] == phone and item["purpose"] == purpose]
        assert found, f"没有向 {phone} 发过 {purpose} 验证码"
        return found[-1]


def build_app(
    config: CloudConfig,
    sender: RecordingSender | None = None,
    sms_sender: RecordingSmsSender | None = None,
):
    """建一个注入了假发信器 / 假短信器的 app。测试里所有 app 都必须经过这里(或显式注入)。"""
    return create_app(config, code_sender=sender or RecordingSender(), sms_sender=sms_sender or RecordingSmsSender())


@pytest.fixture
def config(tmp_path: Path) -> CloudConfig:
    return CloudConfig(
        data_dir=tmp_path,
        public_url="https://mosael.test",
        cookie_secure=False,
        mfa_key=Fernet.generate_key().decode("ascii"),
    )


@pytest.fixture
def sender() -> RecordingSender:
    return RecordingSender()


@pytest.fixture
def sms_sender() -> RecordingSmsSender:
    return RecordingSmsSender()


@pytest.fixture
def app(config: CloudConfig, sender: RecordingSender, sms_sender: RecordingSmsSender):
    return create_app(config, code_sender=sender, sms_sender=sms_sender)


@pytest.fixture
def client(app):
    made = TestClient(app)
    yield made
    made.close()


@pytest.fixture
def db_path(config: CloudConfig) -> Path:
    return config.data_dir / "cloud.db"


def rows(db_path: Path, sql: str, params: tuple = ()) -> list[tuple]:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(sql, params).fetchall()


def scalar(db_path: Path, sql: str, params: tuple = ()):
    found = rows(db_path, sql, params)
    return found[0][0] if found else None


def request_signup_code(client: TestClient, email: str = "alice@example.com") -> str:
    response = client.post(api("/signup/code"), json={"email": email})
    assert response.status_code == 200, response.text
    return client.app.state.code_sender.last_code(email.strip().lower(), "signup")


def signup(client: TestClient, email: str = "alice@example.com", password: str = PASSWORD) -> dict:
    code = request_signup_code(client, email)
    response = client.post(api("/signup"), json={"email": email, "code": code, "password": password})
    assert response.status_code == 201, response.text
    return response.json()["user"]


def request_phone_code(client: TestClient, phone: str = "13800138000") -> str:
    response = client.post(api("/login/sms/code"), json={"phone": phone})
    assert response.status_code == 200, response.text
    return client.app.state.sms_sender.last_code("+8613800138000", "login")


def login_phone(client: TestClient, phone: str = "13800138000") -> dict:
    code = request_phone_code(client, phone)
    response = client.post(api("/login/sms/verify"), json={"phone": phone, "code": code})
    assert response.status_code == 200, response.text
    return response.json()["user"]


def request_login_code(client: TestClient, email: str = "alice@example.com") -> str:
    response = client.post(api("/login/code"), json={"email": email})
    assert response.status_code == 200, response.text
    return client.app.state.code_sender.last_code(email.strip().lower(), "login")


def login_code(client: TestClient, email: str = "alice@example.com") -> dict:
    code = request_login_code(client, email)
    response = client.post(api("/login/code/verify"), json={"email": email, "code": code})
    assert response.status_code == 200, response.text
    return response.json()["user"]


def login(client: TestClient, email: str = "alice@example.com", password: str = PASSWORD) -> dict:
    response = client.post(api("/login"), json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["user"]


def signed_in(client: TestClient, email: str = "alice@example.com", password: str = PASSWORD) -> dict:
    signup(client, email=email, password=password)
    return login(client, email=email, password=password)


# ---------------------------------------------------------------------------
# 第三方登录(OAuth)的假 provider
#
# 测试**绝不真连 GitHub / Google**:和发信一样,这里注入假实现。它仍然会像真 provider 那样
# 校验 PKCE(S256(verifier) == authorize 时收到的 challenge)与 redirect_uri,这样"回调必须
# 用同一个回调地址"也能被测试钉住,而不是只测一个不校验的桩。
# ---------------------------------------------------------------------------

class FakeOAuthProvider:
    """记录 authorize / exchange / userinfo 三次交互,并像真 provider 一样验 PKCE。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.provider_user_id = f"{name}-user-1"
        self.email = "alice@example.com"
        self.email_verified = True
        self.fail_exchange = ""
        self.fail_userinfo = ""
        self.challenges: dict[str, str] = {}
        self.redirect_uris: dict[str, str] = {}
        self.codes: dict[str, tuple[str, str]] = {}
        self.authorize_calls: list[dict[str, str]] = []
        self.exchange_calls: list[dict[str, str]] = []
        self.userinfo_calls = 0

    def authorize_url(self, *, config, redirect_uri, state, code_challenge) -> str:
        self.challenges[state] = code_challenge
        self.redirect_uris[state] = redirect_uri
        self.authorize_calls.append(
            {"redirect_uri": redirect_uri, "state": state, "code_challenge": code_challenge}
        )
        query = {
            "client_id": f"fake-{self.name}-client",
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"https://{self.name}.test/authorize?{urlencode(query)}"

    def issue_code(self, state: str, code: str = "fake-code") -> str:
        self.codes[code] = (self.challenges[state], self.redirect_uris[state])
        return code

    def exchange_code(self, *, config, code, redirect_uri, code_verifier) -> str:
        self.exchange_calls.append({"code": code, "redirect_uri": redirect_uri})
        if self.fail_exchange:
            raise OAuthProviderError(self.fail_exchange, "raw provider detail")
        stored = self.codes.pop(code, None)
        if stored is None:
            raise OAuthProviderError("invalid_grant", "unknown code")
        challenge, authorized_redirect = stored
        if code_challenge(code_verifier) != challenge:
            raise OAuthProviderError("invalid_grant", "pkce mismatch")
        if redirect_uri != authorized_redirect:
            raise OAuthProviderError("invalid_grant", "redirect_uri mismatch")
        return f"access-token-for-{self.provider_user_id}"

    def fetch_identity(self, *, config, access_token) -> ProviderIdentity:
        self.userinfo_calls += 1
        if self.fail_userinfo:
            raise OAuthProviderError(self.fail_userinfo, "raw userinfo detail")
        return ProviderIdentity(
            provider_user_id=self.provider_user_id,
            email=self.email,
            email_verified=self.email_verified,
            display_name="Test Person",
        )


@pytest.fixture
def oauth_providers() -> dict[str, FakeOAuthProvider]:
    return {"github": FakeOAuthProvider("github"), "google": FakeOAuthProvider("google")}


@pytest.fixture
def oauth_config(tmp_path: Path) -> CloudConfig:
    """**假凭据**。它们只用来把 provider 标成"已配置",不会离开进程。"""
    return CloudConfig(
        data_dir=tmp_path,
        public_url="https://mosael.test",
        cookie_secure=False,
        github_client_id="fake-github-client",
        github_client_secret="fake-github-secret",
        google_client_id="fake-google-client",
        google_client_secret="fake-google-secret",
        mfa_key=Fernet.generate_key().decode("ascii"),
    )


@pytest.fixture
def oauth_app(oauth_config: CloudConfig, sender: RecordingSender, oauth_providers):
    return create_app(
        oauth_config,
        code_sender=sender,
        sms_sender=RecordingSmsSender(),
        oauth_providers=oauth_providers,
    )


@pytest.fixture
def oauth_client(oauth_app):
    made = TestClient(oauth_app)
    yield made
    made.close()


@pytest.fixture
def oauth_db_path(oauth_config: CloudConfig) -> Path:
    return oauth_config.data_dir / "cloud.db"


def execute(db_path: Path, sql: str, params: tuple = ()) -> None:
    """直接改库,用来模拟"库里的 verifier 与 provider 记的 challenge 不一致"。"""
    with sqlite3.connect(db_path) as connection:
        connection.execute(sql, params)
        connection.commit()
