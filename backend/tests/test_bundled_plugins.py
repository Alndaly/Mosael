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
