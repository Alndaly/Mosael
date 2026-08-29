"""结构性约束:**清过缓存之后,在飞的那次探测不算数。**

`clear_runtime_probes()` 的意思是「刚才那套环境已经不作数了,重新探」。而探测是后台线程,
清的那一刻很可能有一条正在跑 —— 它探的是**改配置之前**那套环境。

不处理它有两个后果,都真实发生过(一次表现为整套测试里一条用例随机变红):

  · `_PROBING` 不清 —— 上一代那条还挂着「正在探测」,新一代的探测**永远起不来**,
    界面上状态就卡在「还没测过」;
  · 就算把 `_PROBING` 清了,上一代那条跑完还是会把**过期答案写回缓存**,覆盖掉新探出来的。

所以判据不是「清空」,是「**只有当代的才算数**」。
"""

from __future__ import annotations

RATCHET = True

import threading
import time

import pytest

from app.ai.runtime import asr_models, tts_models


def _wait_checked(module, engine: str, seconds: float = 2.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if module.runtime_status(engine)[1]:
            return True
        time.sleep(0.02)
    return False


@pytest.mark.parametrize(
    ("module", "engine", "resolver", "fresh"),
    [
        (tts_models, "f5-tts", "_resolve_engine_python", "/usr/bin/python3"),
        (asr_models, "funasr", "runtime_ready", True),
    ],
    ids=["tts", "asr"],
)
def test_清缓存之后新的探测起得来(module, engine, resolver, fresh, monkeypatch) -> None:
    """**只走后台探测那条路。**

    `refresh_runtime_status` 是同步的,它绕开 `_PROBING` 直接写答案 —— 用它测等于没测
    (第一版就是这么写的,把修复撤掉照样绿)。真正会卡住的是 `probe_in_background`:
    上一代那条还挂在 `_PROBING` 里,它就直接 return,状态永远停在「还没测过」。
    """
    started = threading.Event()

    def slow(_arg):
        started.set()
        time.sleep(3)
        return None if module is tts_models else False

    monkeypatch.setattr(module, resolver, slow)
    module.clear_runtime_probes()
    module.probe_in_background(engine)
    assert started.wait(2), "第一次探测没起来"

    monkeypatch.setattr(module, resolver, lambda _arg: fresh)
    module.clear_runtime_probes()
    module.probe_in_background(engine)

    assert _wait_checked(module, engine), "清完缓存之后新的探测起不来 —— 上一代把位置占着"
    assert module.runtime_status(engine)[0] is True


@pytest.mark.parametrize(
    ("module", "engine", "resolver", "stale", "fresh"),
    [
        (tts_models, "f5-tts", "_resolve_engine_python", None, "/usr/bin/python3"),
        (asr_models, "funasr", "runtime_ready", False, True),
    ],
    ids=["tts", "asr"],
)
def test_上一代的结果不许写回来(module, engine, resolver, stale, fresh, monkeypatch) -> None:
    """慢的那条跑完时新答案已经在了 —— 它一写回去就是把新的覆盖成旧的。"""
    release = threading.Event()
    started = threading.Event()

    def slow(_arg):
        started.set()
        release.wait(3)
        return stale

    monkeypatch.setattr(module, resolver, slow)
    module.clear_runtime_probes()
    module.probe_in_background(engine)
    assert started.wait(2)

    monkeypatch.setattr(module, resolver, lambda _arg: fresh)
    module.clear_runtime_probes()
    module.probe_in_background(engine)
    assert _wait_checked(module, engine)

    release.set()
    time.sleep(0.3)  # 给上一代那条写回的机会

    assert module.runtime_status(engine)[0] is True, "上一代的过期答案把新的覆盖掉了"
