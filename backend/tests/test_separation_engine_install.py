"""装分离引擎是一次**显式**的动作,不是藏在第一次分离后面。

不给这一页,第一次分离会在工作流跑到一半时建 venv、装 torch、拉权重 —— 几分钟到几十分钟,
期间界面上只有一个转圈,而用户完全不知道正在往自己机器上装一个 GB 级的东西。

这里钉三条:状态按**盘上**看(内存那份只在装和失败时有话说)、装是后台线程不阻塞请求、
失败的原因原样留着给用户看。
"""

from __future__ import annotations

import pytest

from app.ai.runtime import separation_models as sm
from app.ai.runtime.install_state import InstallProgress


@pytest.fixture(autouse=True)
def _clean_store():
    def reset() -> None:
        for engine in sm.ENGINE_REQUIREMENTS:
            sm._store.clear(engine)
        #: 收尾时 runtime_ready 可能还是某条测试打的桩(monkeypatch 的撤销顺序不保证在
        #: 这之前),那上面没有 cache_clear —— 清缓存是尽力而为,不该把收尾本身弄红。
        getattr(sm.runtime_ready, "cache_clear", lambda: None)()

    reset()
    yield
    reset()


def test_没装时是_missing__装上了就是_installed(monkeypatch) -> None:
    """**静息时的事实源是盘上那个解释器**,不是内存里的记录 —— 重启之后内存空了,
    而解释器还在,这时状态该是"已安装"而不是"未知"。"""
    monkeypatch.setattr(sm, "runtime_ready", lambda engine: False)
    assert sm.list_status()[0]["status"] == "missing"
    monkeypatch.setattr(sm, "runtime_ready", lambda engine: True)
    assert sm.list_status()[0]["status"] == "installed"
    assert sm.list_status()[0]["runtime_ready"] is True


def test_装的时候不阻塞请求(monkeypatch) -> None:
    started = []
    monkeypatch.setattr(sm, "runtime_ready", lambda engine: False)
    monkeypatch.setattr(sm.threading, "Thread", lambda target, args, daemon: type(
        "T", (), {"start": lambda self: started.append(args)}
    )())

    row = sm.start_install("demucs")
    assert row["status"] == "installing"
    assert started == [("demucs",)], "装要跑在后台线程里 —— 建 venv 加装 torch 是几十分钟的事"


def test_已经在装的不许再点一次(monkeypatch) -> None:
    monkeypatch.setattr(sm, "runtime_ready", lambda engine: False)
    sm._store.set("demucs", InstallProgress("installing"))
    with pytest.raises(RuntimeError, match="已经在安装"):
        sm.start_install("demucs")


def test_不认识的引擎报_KeyError() -> None:
    with pytest.raises(KeyError):
        sm.start_install("没有这个引擎")


def test_失败的原因原样留着(monkeypatch) -> None:
    """pip 说不清时,用户至少能把那句话搜一下 —— 包一层"安装失败"就把唯一有用的东西盖住了。"""
    monkeypatch.setattr(sm, "runtime_ready", lambda engine: False)

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
    monkeypatch.setattr(sm, "runtime_ready", lambda engine: ready["value"])
    sm._store.set("demucs", InstallProgress("installing"))
    ready["value"] = True
    sm._run_install("demucs")
    assert sm._store.get("demucs") is None
    assert sm.list_status()[0]["status"] == "installed"


def test_装东西到后端主机上要部署管理员() -> None:
    """往**这台机器**上装几 GB 的东西是部署级动作,不属于任何工作区 —— 和下载转写模型同一条。"""
    import inspect

    from app.api.routes import separation as route

    source = inspect.getsource(route.install_separation_engine)
    assert "ensure_deployment_admin" in source
