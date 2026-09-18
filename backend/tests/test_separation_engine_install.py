"""装分离引擎是一次**显式**的动作,不是藏在第一次分离后面。

不给这一页,第一次分离会在工作流跑到一半时建 venv、装 torch、拉权重 —— 几分钟到几十分钟,
期间界面上只有一个转圈,而用户完全不知道正在往自己机器上装一个 GB 级的东西。

这里钉四条:**装没装的判据是 import 得进来**(不是解释器这个文件在不在)、状态按盘上看
(内存那份只在装和失败时有话说)、装是后台线程不阻塞请求、失败的原因原样留着给用户看。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.runtime import separation_models as sm
from app.ai.runtime.install_state import InstallProgress


@pytest.fixture(autouse=True)
def _clean_store():
    def reset() -> None:
        for engine in sm.ENGINES:
            sm._store.clear(engine)
        #: 收尾时 probe_runtime 可能还是某条测试打的桩(monkeypatch 的撤销顺序不保证在
        #: 这之前),那上面没有 cache_clear —— 清缓存是尽力而为,不该把收尾本身弄红。
        sm.clear_runtime_probes()

    reset()
    yield
    reset()


def _says(monkeypatch, *, ready: bool, blame: str = "") -> None:
    """让探测给一个确定的答案,并**当场记进缓存** —— 列状态永远不等后台那次探测。"""
    monkeypatch.setattr(sm, "probe_runtime", lambda engine: (ready, blame))
    sm._probes.invalidate()
    for engine in sm.ENGINES:
        sm.refresh_runtime_status(engine)


def test_没装时是_missing__装上了就是_installed(monkeypatch) -> None:
    """**静息时的事实源是那个 venv 跑不跑得起来**,不是内存里的记录 —— 重启之后内存空了,
    而环境还在,这时状态该是"已安装"而不是"未知"。"""
    _says(monkeypatch, ready=False)
    assert sm.list_status()[0]["status"] == "missing"
    _says(monkeypatch, ready=True)
    assert sm.list_status()[0]["status"] == "installed"
    assert sm.list_status()[0]["runtime_ready"] is True


def test_解释器在但依赖不全_不算装好(monkeypatch, tmp_path: Path) -> None:
    """**这是用户撞到的那一个。**

    pip 装到一半断掉:venv/bin/python 建好了,demucs 没装齐。判据要是"这个文件在不在",
    设置页就写着「已安装」,而每次分离都报「这个运行环境里没有 demucs:No module named 'numpy'」
    —— 两句话都没说谎,只是在回答不同的问题。
    """
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(sm, "managed_venv_python", lambda engine: python)
    _says(monkeypatch, ready=False, blame="No module named 'numpy'")

    row = sm.list_status()[0]
    assert row["status"] == "missing", "解释器在不等于装好了"
    assert row["message"] == "sepMsg_brokenRuntime", "要说清楚它是坏的,而不是只说「未安装」"


def test_半装的环境会被修好_而不是早返回(monkeypatch, tmp_path: Path) -> None:
    """早返回正是那个故障能一直留在机器上的原因:点「安装」什么都不做,分离每次在同一处炸。"""
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(sm, "managed_venv_python", lambda engine: python)
    monkeypatch.setattr("app.ai.runtime.config.get", lambda: type("C", (), {"pip_index_url": ""})())

    installed: list[tuple] = []
    fixed = {"value": False}

    def fake_install(python_path, requirements, **kwargs):
        installed.append((python_path, tuple(requirements)))
        fixed["value"] = True

    monkeypatch.setattr(sm.pip_install, "install", fake_install)
    monkeypatch.setattr(sm, "probe_runtime", lambda engine: (fixed["value"], "No module named 'numpy'"))

    sm.ensure_runtime("demucs")
    assert installed, "依赖不全时要去补,不能因为解释器在就当成已经装好"
    assert installed[0][1] == sm.ENGINES["demucs"].requirements


def test_装完还是跑不起来要说出来(monkeypatch, tmp_path: Path) -> None:
    """pip 退 0 不等于 import 得进来(装错轮子、平台不匹配、依赖被别的包降级)。
    这时报"装好了"就是把同一个谎重讲一遍。"""
    python = tmp_path / "python"
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(sm, "managed_venv_python", lambda engine: python)
    monkeypatch.setattr("app.ai.runtime.config.get", lambda: type("C", (), {"pip_index_url": ""})())
    monkeypatch.setattr(sm.pip_install, "install", lambda *a, **k: None)
    monkeypatch.setattr(sm, "probe_runtime", lambda engine: (False, "No module named 'torch'"))

    with pytest.raises(RuntimeError, match="No module named 'torch'"):
        sm.ensure_runtime("demucs")


def test_还没测过不是没装(monkeypatch) -> None:
    """探一次要起子进程 import torch,列状态不能等它。「还没测过」要能说出口 ——
    否则界面只能把未知画成"没装",然后摆一个按钮让用户重装已经装好的东西。"""
    monkeypatch.setattr(sm, "probe_runtime", lambda engine: (True, ""))
    sm._probes.invalidate()
    monkeypatch.setattr(sm._probes, "probe_in_background", lambda key, probe: None)
    assert sm.list_status()[0]["runtime_checked"] is False


def test_装的时候不阻塞请求(monkeypatch) -> None:
    started = []
    _says(monkeypatch, ready=False)
    monkeypatch.setattr(sm.threading, "Thread", lambda target, args, daemon: type(
        "T", (), {"start": lambda self: started.append(args)}
    )())

    row = sm.start_install("demucs")
    assert row["status"] == "installing"
    assert started == [("demucs",)], "装要跑在后台线程里 —— 建 venv 加装 torch 是几十分钟的事"


def test_已经在装的不许再点一次(monkeypatch) -> None:
    _says(monkeypatch, ready=False)
    sm._store.set("demucs", InstallProgress("installing"))
    with pytest.raises(RuntimeError, match="已经在安装"):
        sm.start_install("demucs")


def test_不认识的引擎报_KeyError() -> None:
    with pytest.raises(KeyError):
        sm.start_install("没有这个引擎")


def test_失败的原因原样留着(monkeypatch) -> None:
    """pip 说不清时,用户至少能把那句话搜一下 —— 包一层"安装失败"就把唯一有用的东西盖住了。"""
    _says(monkeypatch, ready=False)

    def boom(engine: str) -> None:
        raise RuntimeError("安装 demucs 运行依赖失败:No matching distribution found for torch")

    monkeypatch.setattr(sm, "ensure_runtime", boom)
    sm._run_install("demucs")
    row = sm.list_status()[0]
    assert row["status"] == "failed"
    assert "No matching distribution" in row["message"]


def test_装好之后那条记录要清掉(monkeypatch) -> None:
    """留着的话,一条"正在装"会永远挂在那儿 —— 而盘上明明已经好了。"""
    monkeypatch.setattr(sm, "ensure_runtime", lambda engine: None)
    ready = {"value": False}
    monkeypatch.setattr(sm, "probe_runtime", lambda engine: (ready["value"], ""))
    sm._store.set("demucs", InstallProgress("installing"))
    ready["value"] = True
    sm._probes.invalidate()
    sm.refresh_runtime_status("demucs")
    sm._run_install("demucs")
    assert sm._store.get("demucs") is None
    assert sm.list_status()[0]["status"] == "installed"


def test_装东西到后端主机上要部署管理员() -> None:
    """往**这台机器**上装几 GB 的东西是部署级动作,不属于任何工作区 —— 和下载转写模型同一条。"""
    import inspect

    from app.api.routes import separation as route

    source = inspect.getsource(route.install_separation_engine)
    assert "ensure_deployment_admin" in source
