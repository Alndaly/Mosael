"""「明明装好了,还显示更新」:索引许的新版,下载地址给不出来。

用户撞到的:市场说 Remotion 动画 v0.2.0「有新版」,点「更新」装回的是 0.1.0(下载地址指的那次
发版里还是 0.1.0),而索引照旧说 0.2.0 —— 提示永远不消失。根上的修法是索引改成发版产物(见
test_plugin_market_index_is_a_release_artifact);这里钉住装的那一刻的第二道:

- 「有新版」按语义化版本比先后,不按字符串不相等;
- 从市场点「更新」、下下来的包不比装着的新:预览不给确认卡、安装回 409,都说「还没发布」,
  不报「已更新」,并且市场不再对这一条说「有新版」—— 直到索引的许诺变了。
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import timedelta

import pytest

from app.domain.plugins import registry as market
from app.domain.plugins.versions import compare, is_newer

MANIFEST = {
    "id": "dev.test.anim",
    "name": "动画",
    "version": "0.1.0",
    "homepage": "https://example.com/anim",
    "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {"expose": "all", "declare": [{"name": "go", "description": "跑一下"}]},
}
OLD_TAG_URL = "https://github.com/o/r/releases/download/v1.5.2/dev.test.anim.zip"
NEW_TAG_URL = "https://github.com/o/r/releases/download/v1.5.3/dev.test.anim.zip"


def _zip(version: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mosael.plugin.json", json.dumps({**MANIFEST, "version": version}, ensure_ascii=False))
        archive.writestr("main.py", "print('{}')")
    return buffer.getvalue()


class Test版本先后:
    @pytest.mark.parametrize(
        ("newer", "older"),
        [
            ("0.10.0", "0.9.0"),  # 按数比,不按字面:字面比的话 "0.10.0" < "0.9.0"
            ("1.0.0", "0.99.99"),
            ("0.2.0", "0.1.9"),
            ("1.0.1", "1.0.0"),
            ("v1.2.0", "1.1.0"),  # 允许前缀 v
            ("1.2", "1.1.9"),  # 少写的段按 0
            ("1.0.0", "1.0.0-rc.1"),  # 正式版比同号的预发版新
            ("1.0.0-beta", "1.0.0-alpha"),
            ("1.0.0-alpha.1", "1.0.0-alpha"),  # 段多的在后
            ("1.0.0-alpha.beta", "1.0.0-alpha.1"),  # 字母段排在数字段之后
            ("1.0.0-beta.11", "1.0.0-beta.2"),  # 数字段按数比
            ("1.0.0-rc.1", "1.0.0-beta.11"),
        ],
    )
    def test_新的比旧的新(self, newer: str, older: str) -> None:
        assert compare(newer, older) == 1
        assert compare(older, newer) == -1
        assert is_newer(newer, older) and not is_newer(older, newer)

    def test_同一版不算新(self) -> None:
        assert compare("1.2.0", "v1.2") == 0
        assert compare("1.0.0+build.5", "1.0.0") == 0, "构建信息不参与先后"
        assert not is_newer("0.1.0", "0.1.0")

    def test_比不出先后的退回不相等(self) -> None:
        """插件作者写什么全凭自觉。解析不了时宁可多提示一次,也不把真的新版说成旧版。"""
        assert compare("1.2.3.4", "0.1.0") is None, "四段不是语义化版本"
        assert compare("latest", "0.1.0") is None
        assert is_newer("latest", "0.1.0") and not is_newer("latest", "latest")


@pytest.fixture
def served(monkeypatch):
    """下载地址给的是哪一版:按地址查表,测试里随时改。"""
    table: dict[str, str] = {}
    monkeypatch.setattr(market, "download_archive", lambda url: _zip(table[url]))
    return table


@pytest.fixture
def index(monkeypatch):
    """远端索引里这一条许的版本和下载地址。"""
    entry = {"id": MANIFEST["id"], "name": "动画", "version": "0.1.0", "download": OLD_TAG_URL}
    monkeypatch.setattr(market, "fetch_index", lambda _url: [dict(entry)])
    return entry


def _market_entry(client) -> dict:
    listing = client.get("/api/plugins/market").json()
    return next(one for one in listing["plugins"] if one["id"] == MANIFEST["id"])


def _installed_version(client) -> str:
    return next(one["version"] for one in client.get("/api/plugins").json() if one["id"] == MANIFEST["id"])


@pytest.fixture
def client(served, index, tmp_path, monkeypatch):
    """装好 0.1.0 的一台机器(插件目录每个测试一份)。"""
    from app.core.config import settings
    from tests.util import fresh_client

    monkeypatch.setattr(type(settings), "plugins_dir", property(lambda self: tmp_path / "plugins"))
    client = fresh_client()
    served[OLD_TAG_URL] = "0.1.0"
    response = client.post("/api/plugins/install", json={"url": OLD_TAG_URL})
    assert response.status_code == 200, response.text
    assert _installed_version(client) == "0.1.0"
    return client


def test_索引许的和装着的一样_不说有新版(client) -> None:
    entry = _market_entry(client)
    assert entry["installed"] is True
    assert entry["update_available"] is False and entry["update_unreleased"] is False


def test_装着的比索引新_不说有新版(client, index) -> None:
    """此前是字符串不相等:从链接装了更新的一版,市场反倒说「有新版」,点下去是降级。"""
    index["version"] = "0.0.9"
    assert _market_entry(client)["update_available"] is False


def test_下载给不出新版_预览说还没发布_市场不再提示(client, index, served) -> None:
    index["version"] = "0.2.0"  # main 上改了版本、索引跟着许了 0.2.0,而下载地址那次发版里还是 0.1.0
    assert _market_entry(client)["update_available"] is True

    preview = client.post("/api/plugins/install/preview", json={"url": OLD_TAG_URL, "advertised_version": "0.2.0"})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["update_unreleased"] is True
    assert body["version"] == "0.1.0", "预览给的是包里实际那一版,不是索引许的"

    entry = _market_entry(client)
    assert entry["update_available"] is False, "证实了还没发布,市场就不该再说「有新版」"
    assert entry["update_unreleased"] is True


def test_下载给不出新版_安装回_409_不报已更新(client, index) -> None:
    index["version"] = "0.2.0"
    response = client.post(
        "/api/plugins/install",
        json={"url": OLD_TAG_URL, "overwrite": True, "advertised_version": "0.2.0"},
        headers={"Accept-Language": "zh-CN"},
    )
    assert response.status_code == 409, response.text
    assert "新版本还没发布" in response.json()["detail"]
    assert _installed_version(client) == "0.1.0"
    assert _market_entry(client)["update_available"] is False


def test_英文界面说英文(client, index) -> None:
    index["version"] = "0.2.0"
    response = client.post(
        "/api/plugins/install",
        json={"url": OLD_TAG_URL, "overwrite": True, "advertised_version": "0.2.0"},
        headers={"Accept-Language": "en"},
    )
    assert response.status_code == 409
    assert "hasn't been released yet" in response.json()["detail"]


def test_从链接重装同一版不拦(client) -> None:
    """没带 advertised_version = 不是从市场来的更新:同一版重装是有意的(修一修被改坏的目录)。"""
    response = client.post("/api/plugins/install", json={"url": OLD_TAG_URL, "overwrite": True})
    assert response.status_code == 200, response.text


def test_索引的许诺一变_又照常比版本(client, index, served) -> None:
    """发了新版:官方索引的下载地址钉在新 tag 上,记下的那条就不再算数。"""
    index["version"] = "0.2.0"
    client.post("/api/plugins/install/preview", json={"url": OLD_TAG_URL, "advertised_version": "0.2.0"})
    assert _market_entry(client)["update_available"] is False

    index["download"] = NEW_TAG_URL
    served[NEW_TAG_URL] = "0.2.0"
    entry = _market_entry(client)
    assert entry["update_available"] is True and entry["update_unreleased"] is False

    response = client.post(
        "/api/plugins/install",
        json={"url": NEW_TAG_URL, "overwrite": True, "advertised_version": "0.2.0"},
    )
    assert response.status_code == 200, response.text
    assert _installed_version(client) == "0.2.0"
    entry = _market_entry(client)
    assert entry["update_available"] is False and entry["update_unreleased"] is False


def test_记下的还没发布过了时限就不算数(client, index) -> None:
    """自建索引可能一直用同一个地址,而地址背后的包迟早换成真正的新版。"""
    from app.core.db import SessionLocal
    from app.db.models import PluginMarketHold
    from app.domain.plugins.updates import HOLD_TTL

    index["version"] = "0.2.0"
    client.post("/api/plugins/install/preview", json={"url": OLD_TAG_URL, "advertised_version": "0.2.0"})
    with SessionLocal() as db:
        hold = db.get(PluginMarketHold, MANIFEST["id"])
        hold.recorded_at -= HOLD_TTL + timedelta(minutes=1)
        db.commit()
    assert _market_entry(client)["update_available"] is True


def test_下载给了新版_照常更新(client, index, served) -> None:
    index["version"] = "0.2.0"
    served[OLD_TAG_URL] = "0.2.0"
    preview = client.post("/api/plugins/install/preview", json={"url": OLD_TAG_URL, "advertised_version": "0.2.0"}).json()
    assert preview["update_unreleased"] is False and preview["installed_version"] == "0.1.0"
    response = client.post(
        "/api/plugins/install",
        json={"url": OLD_TAG_URL, "overwrite": True, "advertised_version": "0.2.0"},
    )
    assert response.status_code == 200, response.text
    assert _installed_version(client) == "0.2.0"
