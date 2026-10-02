"""本地开发模式:零依赖起得来、dev-seed 幂等、服务自己出文件、固定验证码只在开发环境收。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import make_url

from community.app import create_app
from community.cli import main as cli_main
from community.config import Settings
from community.db import make_engine

API = "/api/community/v1"


@pytest.fixture
def dev_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("COMMUNITY_DATABASE_URL", "COMMUNITY_STORAGE_DIR", "COMMUNITY_TEST_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("COMMUNITY_ENV", "development")
    monkeypatch.setenv("COMMUNITY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("COMMUNITY_DEV_SMS_CODE", "000000")
    monkeypatch.setenv("COMMUNITY_LOG_FORMAT", "text")
    return tmp_path / "data"


def test_开发环境的缺省值(tmp_path: Path) -> None:
    dev = Settings(env="development", data_dir=str(tmp_path))
    assert make_url(dev.database_url).database == str((tmp_path / "community.db").resolve())
    assert dev.storage_dir == str(tmp_path / "media") and dev.serve_media is True
    assert dev.cookie_secure is False and dev.media_url_prefix == "/api/community/media"
    assert dev.public_url == "http://localhost:3100"
    prod = Settings(env="production")
    assert any("COMMUNITY_PUBLIC_URL" in one for one in prod.problems())
    assert prod.cookie_secure is True and prod.serve_media is False and prod.media_url_prefix == "/community-media"


def test_数据目录名里带百分号_库还落在这个目录里(tmp_path: Path) -> None:
    # SQLAlchemy 2.1 起解析 URL 会把库名里的 `%41` 反转义成 `A`;手拼 `sqlite:///{路径}` 的话,
    # 建出来的库在另一个(不存在的)目录里,连接直接失败。
    data = tmp_path / "a%41b"
    data.mkdir()
    engine = make_engine(Settings(env="development", data_dir=str(data)).database_url)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("create table t (x int)")
        assert (data / "community.db").is_file()
    finally:
        engine.dispose()


def test_固定验证码只在开发环境收() -> None:
    with pytest.raises(ValidationError):
        Settings(env="production", dev_sms_code="000000")
    with pytest.raises(ValidationError):
        Settings(env="test", dev_sms_code="000000")


def test_dev_seed_之后整个社区能在本地逛(dev_env: Path, capsys) -> None:
    assert cli_main(["dev-seed"]) == 0
    assert cli_main(["dev-seed"]) == 0
    out = capsys.readouterr().out
    password = (dev_env / "dev-credentials.txt").read_text(encoding="utf-8").split("password=")[1].strip()
    assert password in out and (dev_env / "dev-jwt-key.pem").is_file()

    with TestClient(create_app(), base_url="http://localhost") as client:
        login = client.post(f"{API}/auth/password/login", json={"login": "admin", "password": password})
        assert login.status_code == 200 and "Secure" not in login.headers["set-cookie"]
        admin = {"Authorization": f"Bearer {login.json()['access_token']}"}
        queue = client.get(f"{API}/admin/queue", headers=admin).json()["items"]
        #: 待审核的:一个插件,和一个声明为真人的人物(资产里的真人先审核,ADR 0027 §4)。
        assert sorted((one["kind"], one["item"]["plugin_id"] or one["item"]["title"]) for one in queue) == [
            ("asset", "示例真人主播"),
            ("plugin", "dev.demo.pending"),
        ]
        assets = client.get(f"{API}/assets").json()["items"]
        assert sorted(one["asset_kind"] for one in assets) == ["character", "location", "prop"]

        workflows = client.get(f"{API}/workflows", params={"official": "false"}).json()["items"]
        assert len(workflows) == 3 and any(one["has_code"] for one in workflows)
        assert [one["id"] for one in client.get(f"{API}/plugins/index.json").json()["plugins"]] == ["dev.demo.greeter"]

        series = client.get(f"{API}/stats/timeseries", params={"metric": "downloads", "days": 30}).json()["points"]
        assert sum(point["value"] for point in series) > 0

        board = client.get(f"{API}/shares/demo-board").json()
        kinds = [item["kind"] for item in board["snapshot"]["items"]]
        assert kinds.count("image") == 3 and "note" in kinds and "document" in kinds
        media = next(iter(board["media"].values()))
        served = client.get(media["url"])
        assert served.status_code == 200 and served.headers["content-type"] == "image/png"
        assert served.headers["x-content-type-options"] == "nosniff"
        assert client.get(f"{API}/shares/demo-board/og.png").status_code == 200

        # 固定验证码
        client.post(f"{API}/auth/sms/send", json={"phone": "+8613800138111", "purpose": "login"})
        sms = client.post(f"{API}/auth/sms/login", json={"phone": "+8613800138111", "code": "000000", "agree_terms_version": "1"})
        assert sms.status_code == 201
