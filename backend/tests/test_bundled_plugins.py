"""随应用一起发的插件(`plugins/bundled/`):装好、登记好,卸不掉(见 domain/plugins/bundled)。

`install-bundled-plugins` 是每次启动都跑的对账步骤:插件目录里没有、或内容和这一版带的不一样,
就整目录换成这一版的;一样就不动(连目录的修改时间都不动)。插件自己的持久数据和实例、凭据
都不在插件目录里,换目录伤不到它们。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import PluginPackage
from app.domain.plugins import PluginDomainError, bundled, packages
from tests.util import fresh_client


@pytest.fixture
def shipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fresh_client()
    root = tmp_path / "bundled"
    plugin = root / "demo"
    plugin.mkdir(parents=True)
    (plugin / "mosael.plugin.json").write_text(
        json.dumps({"id": "test.bundled", "name": "随包", "version": "1.0.0", "manifest_version": 1,
                    "runtime": {"kind": "process", "entry": "main.py"}}),
        encoding="utf-8",
    )
    (plugin / "main.py").write_text("print('v1')\n", encoding="utf-8")
    monkeypatch.setattr(bundled, "bundled_root", lambda: root)
    target = settings.plugins_dir / "test.bundled"
    yield plugin, target
    import shutil

    shutil.rmtree(target, ignore_errors=True)


def test_启动对账把随包插件装进插件目录并登记(shipped) -> None:
    plugin, target = shipped
    from app.db.migrations import _install_bundled_plugins

    _install_bundled_plugins()
    assert (target / "main.py").read_text() == "print('v1')\n"
    with SessionLocal() as db:
        package = db.get(PluginPackage, "test.bundled")
        assert package is not None and package.manifest["_path"] == str(target)
        assert bundled.install(db, settings.plugins_dir) == [], "内容没变就不该再拷一遍"

        # 这一版带的插件改了(开发时改了代码、或者升级带来了新版本)→ 下一次对账换成新的
        (plugin / "main.py").write_text("print('v2')\n", encoding="utf-8")
        assert bundled.install(db, settings.plugins_dir) == ["test.bundled"]
    assert (target / "main.py").read_text() == "print('v2')\n"
    assert not any(path.name.endswith(".installing") for path in settings.plugins_dir.iterdir())


def test_随包插件卸不掉(shipped) -> None:
    from app.db.migrations import _install_bundled_plugins

    _install_bundled_plugins()
    with SessionLocal() as db:
        with pytest.raises(PluginDomainError) as caught:
            packages.uninstall(db, "test.bundled", settings.plugins_dir)
        assert caught.value.key == "pluginErr_bundledCannotUninstall"
        assert db.scalars(select(PluginPackage.id).where(PluginPackage.id == "test.bundled")).one()


def test_插件页标出随包的那一个(shipped) -> None:
    from app.db.migrations import _install_bundled_plugins

    _install_bundled_plugins()
    client = fresh_client()
    entry = next(one for one in client.get("/api/plugins").json() if one["id"] == "test.bundled")
    assert entry["bundled"] is True


def test_随包插件随后端一起打包() -> None:
    """冻结之后 bundled_root 指向解包目录里的 plugins/bundled —— 打包命令得真的把它带上,
    否则打包版里一个随包插件都没有,而开发时一切正常(那时读的是仓库里那一份)。"""
    build = (Path(__file__).resolve().parents[2] / "package.json").read_text(encoding="utf-8")
    command = next(line for line in build.splitlines() if '"build:backend"' in line)
    assert "--add-data ../plugins/bundled:plugins/bundled" in command


def test_仓库里随包的插件都能装() -> None:
    """plugins/bundled 下的每一个都有合法清单、入口在 —— 坏一个,每次启动对账都会炸。"""
    from app.domain.plugins.manifest import parse

    shipped = bundled.plugins()
    assert shipped, "plugins/bundled 下至少有 ComfyUI"
    for plugin in shipped:
        raw = json.loads((plugin.source / "mosael.plugin.json").read_text(encoding="utf-8"))
        manifest = parse(raw, str(plugin.source))
        assert (plugin.source / manifest.runtime.entry).is_file()


def test_问哪几个是随包的不读插件的文件(shipped, monkeypatch: pytest.MonkeyPatch) -> None:
    """插件页列表、市场、卸载判定都要问「哪几个是随包的」。此前每问一次就把随包插件的整个目录
    读一遍、哈希一遍 —— 打开一次插件页就是一次。指纹只有启动对账要。"""
    def boom(_root: Path) -> str:
        raise AssertionError("只问 id 的时候不该去算内容指纹")

    from app.db.migrations import _install_bundled_plugins
    from tests.util import second_client

    _install_bundled_plugins()  # 启动对账:只有这一处该算指纹
    monkeypatch.setattr(bundled, "_digest", boom)
    assert [one.id for one in bundled.plugins()] == ["test.bundled"]
    assert bundled.is_bundled("test.bundled")
    listed = second_client("tester").get("/api/plugins")
    assert listed.status_code == 200 and any(one["bundled"] for one in listed.json())
