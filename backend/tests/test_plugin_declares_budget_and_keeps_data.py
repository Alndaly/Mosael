"""插件自己能说两件事:「这一步要跑多久」和「这些东西要留到下次」。

两件事此前都说不出来:
- 预算只有调用方能给(Blender 互通自己传)。一个渲染视频的工具不管从哪里调,都在第 60 秒被掐。
- 插件目录不能当存储 —— 更新就是整目录替换。Remotion 那种要攒几百 MB 依赖的插件,
  每次更新都重装一遍。

所以:`declare` 里可以写 `timeout_seconds`(有上限);每个插件有一个 MOSAEL_PLUGIN_DATA_DIR,
更新不动它,卸载连它一起删。
"""

from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import PluginInstance, PluginPackage
from app.domain.plugins import packages, runtime
from app.domain.plugins.tools import MAX_DECLARED_TIMEOUT_SECONDS, all_tools, invoke
from tests.util import fresh_client

ENTRY = """
    import json, os, sys, time
    request = json.loads(sys.stdin.read())
    if request["tool"] == "slow":
        time.sleep(3)
    data = os.environ.get("MOSAEL_PLUGIN_DATA_DIR", "")
    if data:
        marker = os.path.join(data, "seen.txt")
        before = open(marker).read() if os.path.exists(marker) else ""
        open(marker, "w").write(before + "x")
    print(json.dumps({"ok": True, "output": {"data_dir": data, "seen": open(os.path.join(data, "seen.txt")).read() if data else ""}}))
"""


def install(tmp_path: Path, declare: list[dict]) -> str:
    # 持久目录**本来就**跨调用留着 —— 所以别的用例留下的东西也在,每条用例从空目录开始。
    shutil.rmtree(runtime.data_dir_for("budget-demo"), ignore_errors=True)
    plugin_dir = tmp_path / "budget-demo"
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / "main.py").write_text(textwrap.dedent(ENTRY), encoding="utf-8")
    manifest = {
        "id": "budget-demo", "name": "预算", "version": "0.1.0",
        "runtime": {"kind": "process", "entry": "main.py"},
        "tools": {"expose": "all", "declare": declare},
        "_path": str(plugin_dir),
    }
    (plugin_dir / "mosael.plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    fresh_client()
    with SessionLocal() as db:
        db.add(PluginPackage(id="budget-demo", name="预算", version="0.1.0", manifest=manifest))
        db.flush()
        instance = PluginInstance(package_id="budget-demo", name="预算", enabled=True, owner_user_id="")
        db.add(instance)
        db.commit()
        return instance.id


def test_声明的预算真的生效(tmp_path) -> None:
    """声明 1 秒、睡 3 秒 —— 按声明掐断,而不是等满默认的 60 秒。"""
    instance_id = install(tmp_path, [{"name": "slow", "timeout_seconds": 1}])
    with SessionLocal() as db:
        invocation = invoke(db, instance_id, "slow", {})
    assert invocation.status == "failed"
    assert "超时(1s)" in invocation.error


def test_调用方给了预算就以调用方为准(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    instance_id = install(tmp_path, [{"name": "go", "timeout_seconds": 300}])
    seen: list[float] = []
    real = runtime.execute_tool

    def spy(*args, timeout=runtime.PLUGIN_TIMEOUT_SECONDS, **kwargs):
        seen.append(timeout)
        return real(*args, timeout=timeout, **kwargs)

    monkeypatch.setattr("app.domain.plugins.tools.execute_tool", spy)
    with SessionLocal() as db:
        invoke(db, instance_id, "go", {})
        invoke(db, instance_id, "go", {}, timeout=7)
    assert seen == [300.0, 7]


@pytest.mark.parametrize(("declared", "expected"), [
    (None, None), ("600", None), (0, None), (-5, None), (True, None),
    (120, 120.0), (10**6, float(MAX_DECLARED_TIMEOUT_SECONDS)),
])
def test_写错的预算当没写_太大的截到上限(tmp_path, declared, expected) -> None:
    tool = {"name": "go"} if declared is None else {"name": "go", "timeout_seconds": declared}
    instance_id = install(tmp_path, [tool])
    with SessionLocal() as db:
        instance = db.get(PluginInstance, instance_id)
        assert all_tools(db, instance)[0]["timeout_seconds"] == expected


def test_持久目录跨调用留着_卸载时一起删(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    instance_id = install(tmp_path, [{"name": "go"}])
    with SessionLocal() as db:
        first = invoke(db, instance_id, "go", {})
        second = invoke(db, instance_id, "go", {})
    data_dir = Path(first.output["data_dir"])
    assert data_dir == runtime.data_dir_for("budget-demo")
    assert second.output["seen"] == "xx", "第二次调用没看到第一次留下的东西"

    with SessionLocal() as db:
        packages.uninstall(db, "budget-demo", tmp_path)
    assert not data_dir.exists(), "卸载后持久目录还在 —— 下次装回来会读到上一个版本攒下的东西"


def test_持久目录的名字不会逃出根目录() -> None:
    root = runtime.data_dir_for("x").parent
    for hostile in ("../../etc", "a/../../b", "..", ""):
        assert runtime.data_dir_for(hostile).parent == root


def test_Windows上子进程要的系统变量都在_凭据以外的东西不多带(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows 上缺 SYSTEMROOT,Python 连初始化都过不去;npm 要 APPDATA 放缓存。"""
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    fake = {"PATH": r"C:\\Windows", "SystemRoot": r"C:\\Windows", "APPDATA": r"C:\\Users\\u\\AppData\\Roaming",
            "TEMP": r"C:\\Temp", "OPENAI_API_KEY": "sk-应用自己的", "MOSAEL_DATA_DIR": r"C:\\data"}
    monkeypatch.setattr(runtime.os, "environ", fake)
    env = runtime.base_env()
    assert env["SYSTEMROOT"] == r"C:\\Windows" and env["APPDATA"].endswith("Roaming") and env["TEMP"] == r"C:\\Temp"
    assert "OPENAI_API_KEY" not in env and "MOSAEL_DATA_DIR" not in env


def test_其他平台只有那三个(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime.sys, "platform", "darwin")
    monkeypatch.setattr(runtime.os, "environ", {"PATH": "/usr/bin", "HOME": "/Users/u", "SYSTEMROOT": "x", "SECRET": "y"})
    assert set(runtime.base_env()) == {"PATH", "HOME", "LANG"}
