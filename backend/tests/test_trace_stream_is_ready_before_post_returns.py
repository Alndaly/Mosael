"""POST 一返回,轨迹那条流就得是**开着**的。

界面的顺序是:POST 发消息 → 拿到回应 → 连 `/stream` 看轨迹。而这一轮的流状态此前是在
工作线程里建的 —— POST 返回到那一行跑起来之间有一个窗口,窗口里 `get_stream_state` 说的是
「没有回合在跑」,SSE 的 generator 当场 break,连接关掉。于是那一整轮思考和工具卡片一条都
不出现,要等回合结束才一次性补上。

窗口很窄(线程 start 之后几行),所以它不是每次都发生 —— 表现为「偶尔整轮没有轨迹」,
这种间歇性的事最难从现场倒推。这条测试把它钉死:起线程之前流就得备好。
"""

from __future__ import annotations

import threading

from app.domain.agent import host
from app.domain.agent import stream as agent_stream


def test_起线程之前流就已经开着(monkeypatch) -> None:
    seen: list[bool] = []
    started = threading.Event()

    def fake_thread_target(session_id: str, prompt: str, token: str) -> None:
        started.set()

    monkeypatch.setattr(host, "_run_turn_thread", fake_thread_target)

    real_start = threading.Thread.start

    def watching_start(self):  # 线程真正跑起来之前,先看一眼流的状态
        seen.append(agent_stream.get_stream_state("s-1")["done"])
        real_start(self)

    monkeypatch.setattr(threading.Thread, "start", watching_start)
    host._start_turn("s-1", "hi", "tok")
    started.wait(timeout=5)

    # done=False 的意思是「这一轮在跑」—— 界面这时连上去,流不会被当场关掉。
    assert seen == [False]


def test_没有回合在跑时仍然是关着的() -> None:
    assert agent_stream.get_stream_state("从没跑过的会话")["done"] is True
