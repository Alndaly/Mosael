"""插话要等对面回一句「接住了」,而不是「字节写出去了」。

## 现场

用户对一条排队消息点「插入当前轮」。后端回 `{"steered": true}`,界面按成功处理,而那条消息
**既没有进正在跑的那一轮,也不会再被排队执行** —— 它从队列里消失了。

链条上每一环都写对了:sidecar 专门为「那一轮在用户打字和这一帧到达之间结束了」发一条
`queued{pending:false}`(注释写着"说出来是为了让后端把它当成普通的下一轮发过去而不是丢掉");
`steer_queued_message` 的 docstring 写着「没有活着的轮次时返回 False」;前端连
`chatSteerTooLate` 的文案都备好了。**唯独中间那一跳把问题换了** —— 从「对面接住了吗」
换成「字节写出去了吗」。这两个问题 99% 的情况下答案相同,所以它一直看着是对的;
命中那 1% 时,用户丢的是自己刚打的一句话。

竞态窗口本身很窄(sidecar 在 `send(turn_done)` 之后立刻 `active.delete`,而后端要读到
`turn_done` 才 `live.close()`),但窄不等于没有。
"""

from __future__ import annotations

import threading

from app.ai.sidecar import adapters
from app.ai.sidecar.adapters import _LIVE, _LIVE_LOCK, _LiveTurn, abort_turn, steer_turn


class _Pipe:
    """一根只记录写了什么的 stdin。"""

    def __init__(self) -> None:
        self.frames: list[str] = []

    def write(self, text: str) -> None:
        self.frames.append(text)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass


def _live(session_id: str) -> _LiveTurn:
    live = _LiveTurn(_Pipe(), "turn-1")
    with _LIVE_LOCK:
        _LIVE[session_id] = live
    return live


def _drop(session_id: str) -> None:
    with _LIVE_LOCK:
        _LIVE.pop(session_id, None)


def test_对面说没接住时返回False_哪怕管道写成功了() -> None:
    live = _live("s1")
    try:
        result: list[bool] = []
        caller = threading.Thread(target=lambda: result.append(steer_turn("s1", "改成横屏")))
        caller.start()
        # sidecar:那一轮刚好结束了 —— pending=False。
        _wait_until(lambda: bool(live._ack_type))
        live.ack("queued", False)
        caller.join(timeout=5)

        assert result == [False], "写成功被当成了插进去 —— 这条消息会被摘掉队列标然后蒸发"
    finally:
        _drop("s1")


def test_对面说接住了才返回True() -> None:
    live = _live("s2")
    try:
        result: list[bool] = []
        caller = threading.Thread(target=lambda: result.append(steer_turn("s2", "改成横屏")))
        caller.start()
        _wait_until(lambda: bool(live._ack_type))
        live.ack("queued", True)
        caller.join(timeout=5)

        assert result == [True]
    finally:
        _drop("s2")


def test_那一轮当场结束时_等回执的人立刻拿到False_而不是干等满超时() -> None:
    live = _live("s3")
    try:
        result: list[bool] = []
        caller = threading.Thread(target=lambda: result.append(steer_turn("s3", "改成横屏")))
        caller.start()
        _wait_until(lambda: bool(live._ack_type))
        live.close()  # `_run_pi` 的 finally 走到了这里
        caller.join(timeout=5)

        assert result == [False]
    finally:
        _drop("s3")


def test_对面一声不吭时按没接住处理() -> None:
    live = _live("s4")
    try:
        assert live.send_awaiting_ack({"type": "steer"}, ack_type="queued", timeout=0.05) is False
    finally:
        _drop("s4")


def test_停止也等回执_一轮刚开始时按下不算数() -> None:
    """sidecar 的 `active` 表要到 `await buildAllTools(...)` 之后才写。那几百毫秒里来的 abort
    原先落进空里一声不吭,而这一层返回 True —— 界面显示已停止,那一轮继续跑到底。"""
    live = _live("s5")
    try:
        result: list[bool] = []
        caller = threading.Thread(target=lambda: result.append(abort_turn("s5")))
        caller.start()
        _wait_until(lambda: live._ack_type == "aborted_ack")
        live.ack("aborted_ack", False)  # 那一轮已经结束了,没有东西可停
        caller.join(timeout=5)

        assert result == [False]
    finally:
        _drop("s5")


def test_回执认类型_别人的回执不算数() -> None:
    live = _live("s6")
    try:
        result: list[bool] = []
        caller = threading.Thread(
            target=lambda: result.append(
                live.send_awaiting_ack({"type": "abort"}, ack_type="aborted_ack", timeout=0.4)
            )
        )
        caller.start()
        _wait_until(lambda: live._ack_type == "aborted_ack")
        live.ack("queued", True)  # 另一种回执:不该唤醒这个等待
        caller.join(timeout=5)

        assert result == [False]
    finally:
        _drop("s6")


def _wait_until(predicate, timeout: float = 2.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("等待条件超时")


def test_超时常量是给本地管道的_不是给网络的() -> None:
    assert 0 < adapters.ACK_TIMEOUT_SECONDS <= 5, "这是一次本地管道来回,不该让用户等更久"
