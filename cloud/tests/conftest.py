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


@pytest.fixture
def config(tmp_path: Path) -> CloudConfig:
    return CloudConfig(
        data_dir=tmp_path,
        public_url="https://mosael.test",
        cookie_secure=False,
    )


@pytest.fixture
def app(config: CloudConfig):
    return create_app(config)


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


def signup(client: TestClient, email: str = "alice@example.com", password: str = PASSWORD) -> dict:
    response = client.post(api("/signup"), json={"email": email, "password": password})
    assert response.status_code == 201, response.text
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
