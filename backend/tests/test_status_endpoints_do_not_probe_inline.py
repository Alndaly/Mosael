"""列状态是一次**读**,不该在请求里起子进程 import torch。

用户:「项目启动后有些页面加载特别慢」,而「转写模型」那一页停在「正在连接后端…」。实测:

    GET /api/tts/models   冷 6.7s   热 0.00s
    GET /api/tts/engines  冷 3.6s

原因是这些接口会去探测"哪个解释器跑得起这个引擎",而探测 = 起一个子进程 `import
fish_speech.utils.schema; import tools.server.inference` —— 那一串会把 torch、audiotools、
dac 全拉起来。一个纯读的接口,被一件慢的、外部的事拖住。

**这个形状这个仓库已经修过一次**:`/api/settings/providers` 曾经在返回前替过期的订阅刷新令牌,
断网时每条要等到超时(见 test_listing_connections_does_not_block)。当时的判据是
「这个接口要回答的问题,不需要出网就能回答」。这里是同一句话的另一半:**不需要起子进程
import torch 就能回答**。

探测本身要留着 —— 它解决的是真问题(合成前必须知道跑不跑得起来)。留着,但挪到请求之外:
先把已知的给他,探测在后台跑,下一次拉列表时状态自己就对了。而"还没测过"要**说成还没测过**,
不能说成"未就绪" —— 那是拿一个未知冒充一个结论。
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from app.ai.runtime import asr_models, tts_models


@pytest.fixture
def stuck_probe():
    """一个卡住的探测:一直卡到这条测试结束才放行(不留一个睡着的后台线程拖到下一条测试)。

    列表不量时间:列表要是等了探测,它回来的时候探测必然已经结束(`finished` 已立起);没等的话探测还卡着。
    此前量的是「列表 < 5 秒」(更早是探测睡 5 秒、线画在 1 秒,CI 上机器一忙就红过)。
    """
    release = threading.Event()
    finished = threading.Event()

    def wait() -> None:
        try:
            release.wait(60)
        finally:
            finished.set()

    yield SimpleNamespace(wait=wait, finished=finished)
    release.set()


def test_listing_tts_models_does_not_wait_for_a_probe(monkeypatch, stuck_probe) -> None:
    def slow_probe(engine_id: str) -> str | None:
        stuck_probe.wait()
        return "/usr/bin/python3"

    monkeypatch.setattr(tts_models, "_resolve_engine_python", slow_probe)
    tts_models.clear_runtime_probes()

    rows = tts_models.list_status()

    assert not stuck_probe.finished.is_set(), "列模型等到探测结束才回来 —— 它卡在探测上了"
    assert rows, rows


def test_an_unchecked_runtime_says_so_rather_than_claiming_not_ready(monkeypatch, stuck_probe) -> None:
    """"还没测过"和"测过了、跑不起来"是两回事,拿前者冒充后者就又是一次答非所问。"""
    monkeypatch.setattr(tts_models, "_resolve_engine_python", lambda engine_id: stuck_probe.wait())
    tts_models.clear_runtime_probes()

    row = tts_models.get_status("f5-tts")

    assert row["runtime_checked"] is False, row


def test_the_probe_still_happens_in_the_background(monkeypatch) -> None:
    """挪到后台不等于不做 —— 下一次拉列表时答案该在了。"""
    monkeypatch.setattr(tts_models, "_resolve_engine_python", lambda engine_id: "/usr/bin/python3")
    tts_models.clear_runtime_probes()

    tts_models.list_status()
    deadline = time.time() + 30
    while time.time() < deadline and not tts_models.get_status("f5-tts")["runtime_checked"]:
        time.sleep(0.05)

    row = tts_models.get_status("f5-tts")
    assert row["runtime_checked"] is True and row["runtime_ready"] is True, row


def test_synthesis_still_gets_a_definite_answer(monkeypatch) -> None:
    """合成不能拿"还没测过"开工 —— 它必须等一个确定的答案。这条防止我为了让列表变快,
    把确定性一起丢了。"""
    monkeypatch.setattr(tts_models, "_resolve_engine_python", lambda engine_id: "/usr/bin/python3")
    tts_models.clear_runtime_probes()

    assert tts_models.resolve_engine_python("f5-tts") == "/usr/bin/python3"


def test_listing_asr_models_does_not_wait_either(monkeypatch, stuck_probe) -> None:
    """转写那一页停在「正在连接后端…」的就是这个。"""
    def slow(engine: str):
        stuck_probe.wait()
        return "/usr/bin/python3"

    monkeypatch.setattr(asr_models, "_resolve_python", slow)
    asr_models.clear_runtime_probes()

    asr_models.list_status()

    assert not stuck_probe.finished.is_set(), "列转写模型等到探测结束才回来"
