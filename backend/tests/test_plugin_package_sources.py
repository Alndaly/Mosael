"""插件装包从哪个镜像拉:插件在清单里声明生态(`package_sources`),宿主按「连接的覆盖 > 管理 → 下载源」注入
各生态自己认的变量(见 domain/plugins/package_sources)。

此前 Manim、Remotion 各带一个自由文本的「镜像」配置项,每个插件各存一份地址,和管理页的下载源互不知道,
选了清华 pip 还得在每个插件里再填一遍(用户截图:「镜像应该是下拉选择而不是输入」)。
"""

from __future__ import annotations

import copy

import pytest
from mosael_formats.plugin_env import PACKAGE_SOURCE_KEYS, is_reserved
from mosael_formats.plugin_manifest import ManifestError, parse as parse_manifest

from app.ai.runtime import config as runtime_config
from app.core.db import SessionLocal
from app.domain.voices import tts_settings
from tests.test_plugins import SIMPLE, install

PYPI_PLUGIN = {**copy.deepcopy(SIMPLE), "package_sources": ["pypi"]}


def _host(pip: str = "", npm: str = "") -> None:
    """改「管理 → 下载源」那一行。直接写库,再让运行时重读。"""
    with SessionLocal() as db:
        row = tts_settings.saved_row(db)
        row.pip_index, row.npm_registry = pip, npm
        db.commit()
    runtime_config.refresh()


def _connected(manifest=PYPI_PLUGIN):
    client = install(manifest)
    instance_id = client.get("/api/plugins").json()[0]["instances"][0]["id"]
    client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True})
    return client, instance_id


def _child_env(client, instance_id: str) -> dict[str, str]:
    out = client.post(f"/api/plugins/instances/{instance_id}/tools/shout/invoke", json={"input": {"text": "x"}}).json()
    assert out["status"] == "succeeded", out
    return {key: value for key, value in out["output"]["env"].items() if key.upper() in PACKAGE_SOURCE_KEYS}


@pytest.fixture(autouse=True)
def _reset_host():
    yield
    _host()


class Test注入:
    def test_跟随_管理页选了清华_插件拿到清华的地址_pip和uv都认(self) -> None:
        client, instance_id = _connected()
        _host(pip="tsinghua")
        url = "https://pypi.tuna.tsinghua.edu.cn/simple"
        assert _child_env(client, instance_id) == {"PIP_INDEX_URL": url, "UV_DEFAULT_INDEX": url}

    def test_跟随_管理页是官方源_什么都不注入(self) -> None:
        client, instance_id = _connected()
        _host()
        assert _child_env(client, instance_id) == {}

    def test_连接自己的覆盖盖过管理页_改回空串就重新跟随(self) -> None:
        client, instance_id = _connected()
        _host(pip="tsinghua")
        out = client.patch(f"/api/plugins/instances/{instance_id}", json={"package_sources": {"pypi": "aliyun"}}).json()
        row = next(one for one in out["package_sources"] if one["source"] == "pypi")
        assert row["value"] == "aliyun" and row["host_label"] == "清华大学"
        assert _child_env(client, instance_id)["PIP_INDEX_URL"] == "https://mirrors.aliyun.com/pypi/simple/"
        client.patch(f"/api/plugins/instances/{instance_id}", json={"package_sources": {"pypi": ""}})
        assert _child_env(client, instance_id)["PIP_INDEX_URL"] == "https://pypi.tuna.tsinghua.edu.cn/simple"

    def test_自定义地址照样注入_不带scheme的当场拒(self) -> None:
        client, instance_id = _connected()
        ok = client.patch(f"/api/plugins/instances/{instance_id}",
                          json={"package_sources": {"pypi": "https://pypi.example.com/simple"}})
        assert ok.status_code == 200
        assert _child_env(client, instance_id)["PIP_INDEX_URL"] == "https://pypi.example.com/simple"
        bad = client.patch(f"/api/plugins/instances/{instance_id}", json={"package_sources": {"pypi": "pypi.example.com"}})
        assert bad.status_code >= 400 and "http" in bad.json()["detail"]

    def test_没声明的生态不注入_界面也不列(self) -> None:
        """声明了 pypi 的插件拿不到 npm 的镜像:只注入它要的,插件页只给它要的那几行。"""
        client, instance_id = _connected()
        _host(pip="tsinghua", npm="npmmirror")
        assert "NPM_CONFIG_REGISTRY" not in _child_env(client, instance_id)
        listed = client.get("/api/plugins").json()[0]["instances"][0]["package_sources"]
        assert [one["source"] for one in listed] == ["pypi"]
        assert [one["value"] for one in listed[0]["presets"]] == ["pypi", "tsinghua", "aliyun", "tencent"]


class Test清单:
    def test_镜像变量是宿主占着的名字_插件不能再自己声明一个(self) -> None:
        for key in ("PIP_INDEX_URL", "pip_index_url", "UV_DEFAULT_INDEX", "npm_config_registry"):
            assert is_reserved(key), key
        manifest = copy.deepcopy(SIMPLE)
        manifest["instance"] = {"config": [{"key": "PIP_INDEX_URL", "label": "镜像", "type": "string", "required": False}]}
        with pytest.raises(ManifestError) as raised:
            parse_manifest(manifest, "demo")
        assert raised.value.key == "pluginErr_manifestReservedKey"

    def test_认不出的生态装的时候就说(self) -> None:
        with pytest.raises(ManifestError) as raised:
            parse_manifest({**copy.deepcopy(SIMPLE), "package_sources": ["pip"]}, "demo")
        assert raised.value.key == "pluginErr_manifestPackageSources"


def test_管理页的下载源_npm_也在这里_预设由后端给() -> None:
    client = install(PYPI_PLUGIN)
    got = client.put("/api/settings/install-source", json={"npm_registry": "npmmirror"}).json()
    assert got["npm_registry"] == "npmmirror" and got["pip_index"] == "", "只改给了的那一行"
    assert {one["value"] for one in got["npm_presets"]} == {"npmjs", "npmmirror", "tencent", "huawei"}
    assert client.put("/api/settings/install-source", json={"pip_index": "not a url"}).status_code == 422
