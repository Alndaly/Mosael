"""MosaelCloud 的测试底座:每个测试一个临时数据目录、一个自己的 SQLite 库、不连外网。

`create_app(config)` 是显式工厂 —— 生产入口(`cloud.main:app`)才从环境变量读配置。测试因此可以
同时起好几个互不相干的 Cloud 实例(两套身份隔离那条用例需要)。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloud.app import create_app
from cloud.config import CloudConfig

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


def build_app(config: CloudConfig, sender: RecordingSender | None = None):
    """建一个注入了假发信器的 app。测试里所有 app 都必须经过这里(或显式注入)。"""
    return create_app(config, code_sender=sender or RecordingSender())


@pytest.fixture
def config(tmp_path: Path) -> CloudConfig:
    return CloudConfig(
        data_dir=tmp_path,
        public_url="https://mosael.test",
        cookie_secure=False,
    )


@pytest.fixture
def sender() -> RecordingSender:
    return RecordingSender()


@pytest.fixture
def app(config: CloudConfig, sender: RecordingSender):
    return create_app(config, code_sender=sender)


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


def device_code(client: TestClient, name: str = "MacBook Pro") -> dict:
    response = client.post(api("/device/code"), json={"device_name": name})
    assert response.status_code == 200, response.text
    return response.json()
