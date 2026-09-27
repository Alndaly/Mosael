"""测试夹具。

数据库:缺省每个测试一个新的 SQLite 文件;设了 `COMMUNITY_TEST_DATABASE_URL`(CI 里是 Postgres 服务容器)就用它,
每个测试前把表删了重建。短信发送器、人机验证换成假的;存储是临时目录里的 local。
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from community import models
from community.app import create_app
from community.config import Settings
from community.context import Context
from community.db import Base, make_engine, utcnow
from community.models import SmsCode, User
from community.storage import LocalStorage

API = "/api/community/v1"
TERMS = "2026-09"


@dataclass
class FakeSms:
    sent: list[tuple[str, str, str]] = field(default_factory=list)
    fail: bool = False

    def send(self, phone: str, code: str, *, purpose: str, ttl_minutes: int) -> None:
        from community.sms import SmsSendError

        if self.fail:
            raise SmsSendError("LimitExceeded")
        self.sent.append((phone, purpose, code))

    def last_code(self, phone: str | None = None) -> str:
        for sent_phone, _purpose, code in reversed(self.sent):
            if phone is None or sent_phone == phone:
                return code
        raise AssertionError("no code sent")


@dataclass
class FakeCaptcha:
    ok: bool = True
    calls: int = 0

    def verify(self, *, ticket: str, randstr: str, ip: str) -> bool:
        self.calls += 1
        return self.ok and ticket == "good-ticket"


def make_settings(tmp_path: Path, **overrides) -> Settings:
    url = os.environ.get("COMMUNITY_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'community.db'}"
    values = dict(
        env="test",
        database_url=url,
        secret_key="test-secret-" + "x" * 40,
        public_url="https://mosael.test",
        storage_dir=str(tmp_path / "media"),
        terms_version=TERMS,
        write_requests_per_minute=0,
        log_format="text",
    )
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def sms() -> FakeSms:
    return FakeSms()


@pytest.fixture
def ctx(settings: Settings, sms: FakeSms) -> Iterator[Context]:
    engine = make_engine(settings.database_url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    context = Context.build(settings, sms=sms, storage=LocalStorage(settings), engine=engine, captcha=None)
    context.captcha = None
    yield context
    engine.dispose()


@pytest.fixture
def client(ctx: Context) -> Iterator[TestClient]:
    with TestClient(create_app(context=ctx), base_url="https://testserver") as test_client:
        yield test_client


# ---------------- 帮手 ----------------


def age_sms(ctx: Context, seconds: int) -> None:
    """把已经发出的验证码往前挪 `seconds` 秒(测 60 秒不重发、每日上限、过期)。在 Python 里挪:
    SQL 里做时间运算两种库写法不同。"""
    from datetime import timedelta

    with ctx.sessions() as db:
        for row in db.scalars(select(SmsCode)):
            row.created_at -= timedelta(seconds=seconds)
            row.expires_at -= timedelta(seconds=seconds)
        db.commit()


def send_code(client: TestClient, phone: str, purpose: str = "login", **extra) -> None:
    response = client.post(f"{API}/auth/sms/send", json={"phone": phone, "purpose": purpose, **extra})
    assert response.status_code == 204, response.text


def sms_login(client: TestClient, sms: FakeSms, phone: str = "+8613800000001") -> dict:
    send_code(client, phone)
    response = client.post(
        f"{API}/auth/sms/login", json={"phone": phone, "code": sms.last_code(phone), "agree_terms_version": TERMS}
    )
    assert response.status_code in (200, 201), response.text
    return response.json()


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login_as(client: TestClient, ctx: Context, sms: FakeSms, phone: str, *, role: str | None = None) -> dict:
    """登录一个号码,需要的话把它提成某个角色,返回授权头。"""
    body = sms_login(client, sms, phone)
    if role:
        with ctx.sessions() as db:
            db.execute(update(User).where(User.phone == phone).values(role=role))
            db.commit()
    return auth(body["access_token"])


def make_plugin_zip(manifest: dict, files: dict[str, str | bytes] | None = None, *, symlink: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mosael.plugin.json", json.dumps(manifest))
        for name, content in (files or {"main.py": "print('hi')\n"}).items():
            archive.writestr(name, content)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = 0o120777 << 16
            archive.writestr(info, "/etc/passwd")
    return buffer.getvalue()


def plugin_manifest(plugin_id: str = "dev.someone.hello", version: str = "1.0.0", **extra) -> dict:
    return {
        "id": plugin_id,
        "name": {"zh": "你好", "en": "Hello"},
        "version": version,
        "permissions": ["network:example"],
        "homepage": "https://example.test",
        "author": {"name": "Someone", "url": "https://example.test"},
        "runtime": {"kind": "process", "entry": "main.py"},
        "skills": [{"name": "hello", "description": {"zh": "打招呼", "en": "Say hello"}}],
        "tools": {"declare": [{"name": "say_hello", "label": "Say hello", "effects": "none"}]},
        **extra,
    }


def workflow_file(*, with_code: bool = False, name: str = "My Flow") -> bytes:
    nodes = [{"id": "start", "type": "start", "config": {}}, {"id": "t", "type": "template", "config": {"template": "hi"}}]
    edges = [{"id": "e1", "source": "start", "target": "t"}]
    if with_code:
        nodes.append({"id": "c", "type": "code", "config": {"code": "print(1)"}})
        edges.append({"id": "e2", "source": "t", "target": "c"})
    return json.dumps(
        {"format": "mosael-workflow", "version": 1, "name": name, "description": "A flow", "graph": {"nodes": nodes, "edges": edges}}
    ).encode("utf-8")


def now():
    return utcnow()


__all__ = ["API", "TERMS", "models"]
