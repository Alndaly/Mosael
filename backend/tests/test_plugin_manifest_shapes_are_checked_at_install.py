"""清单里那几样**会被当成路径、名字、环境变量用的东西**,在解析那一刻就卡住形状。

此前 `id` 只要求非空字符串,工具名、配置键只要能解析就收。而它们在下游各有用途:

· id 是插件目录名 —— `"id": "../../x"` 的包装的时候被搬到插件目录之外,「更新」时还会先
  rmtree 那个目录;
· 工具名进节点类型 `plugin.<包>.<工具>`(按最后一个点切)和智能体的函数表;
· 配置 / 凭据键大写后注入插件进程的环境 —— 叫 `path` 的配置项会顶掉 PATH。
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from app.domain.plugins import registry as market
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import ManifestError, parse

BASE = {
    "id": "dev.test.shape",
    "name": "形状",
    "version": "1.0.0",
    "runtime": {"kind": "process", "entry": "main.py"},
}


def _zip(manifest: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mosael.plugin.json", json.dumps(manifest))
        archive.writestr("main.py", "print('{}')")
    return buffer.getvalue()


@pytest.mark.parametrize("hostile", ["../../escaped", "..", ".hidden", "a/b", "a\\b", "/abs", "有空格 的"])
def test_id_不能是一段路径(hostile: str) -> None:
    with pytest.raises(ManifestError):
        parse({**BASE, "id": hostile}, "x")


@pytest.mark.parametrize("fine", ["dev.mosael.comfyui", "budget-demo", "a", "x.y", "test_pan"])
def test_现有的_id_写法都还认(fine: str) -> None:
    assert parse({**BASE, "id": fine}, "x").id == fine


def test_id_越界的包装不上_也不会动插件目录外面的东西(tmp_path) -> None:
    """「更新」一个 id 写成 `../victim` 的包,此前会先 rmtree 插件目录**旁边**那个目录再把包挪过去。"""
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "重要.txt").write_text("别删我", encoding="utf-8")

    with pytest.raises(PluginDomainError):
        market.install_archive(_zip({**BASE, "id": "../victim"}), plugins_dir, overwrite=True)
    assert (victim / "重要.txt").read_text(encoding="utf-8") == "别删我"
    assert list(plugins_dir.iterdir()) == []


@pytest.mark.parametrize("name", ["v1.upload", "有 空格", "", "-leading", "x" * 65])
def test_声明的工具名要能进节点类型和智能体函数表(name: str) -> None:
    manifest = {**BASE, "tools": {"declare": [{"name": name}]}}
    with pytest.raises(ManifestError):
        parse(manifest, "x")


def test_同名的两个工具不收() -> None:
    manifest = {**BASE, "tools": {"declare": [{"name": "go"}, {"name": "go"}]}}
    with pytest.raises(ManifestError, match="go"):
        parse(manifest, "x")


@pytest.mark.parametrize("key", ["path", "PATH", "home", "Lang", "SYSTEMROOT", "mosael_plugin_output_dir", "MOSAEL_LOCALE"])
def test_配置键不能盖掉宿主给的环境变量(key: str) -> None:
    manifest = {**BASE, "instance": {"config": [{"key": key, "label": "x"}]}}
    with pytest.raises(ManifestError, match=key):
        parse(manifest, "x")


def test_配置和凭据大写后撞名不收() -> None:
    manifest = {
        **BASE,
        "instance": {"config": [{"key": "token", "label": "x"}], "credentials": [{"key": "TOKEN", "label": "y"}]},
    }
    with pytest.raises(ManifestError, match="TOKEN"):
        parse(manifest, "x")


def test_仓库里的每个插件清单都过得了这几条() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "plugins"
    manifests = sorted(root.glob("*/*/mosael.plugin.json"))
    assert manifests
    for path in manifests:
        parse(json.loads(path.read_text(encoding="utf-8")), str(path))
