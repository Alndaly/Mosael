"""按了停止,排在队里的话不自动接着跑(维护者 2026-10-09 拍板 D63;体检 AGENT-17)。

现场(隔离环境、假模型):慢吐时排一句「排队的第二句」,按停止 —— 0.5 秒后那句作为新的一轮开跑并答完。按停止往往是
「它跑偏了」,停之前顺手排的那句多半基于跑偏的内容,还得再按一次停止。

现在:用户按停止停下的那一刻,排着的话扣下(payload 带 `held`),留在排队条里等人点「继续发送」;之后再排的照常排队。
不是用户停的(出错、整理上下文)照旧接着跑。
"""

from __future__ import annotations

import threading
import time

import pytest

from app.ai.sidecar.pi_client import SidecarError, TurnResult
from app.core.db import SessionLocal
from app.db.models import AgentSession
from app.domain.agent import host
from tests.test_agent_queue import _session
from tests.util import fresh_client


class _StoppableTurn:
    """卡着不答的一轮:`stop()` 让它像被用户停下那样收尾(aborted),`finish()` 照常答完,`fail()` 抛错。
    放行之后的每一轮都当场答完。记下每一轮收到的提示词。"""

    def __init__(self) -> None:
        self._go = threading.Event()
        self._outcome = "answer"
        self.prompts: list[str] = []

    def __call__(self, *args, **kwargs):
        self.prompts.append(kwargs["prompt"] if "prompt" in kwargs else args[1])
        if len(self.prompts) == 1:
            assert self._go.wait(30), "测试一直没放行第一轮"
            if self._outcome == "stop":
                return TurnResult(text="说到一半", aborted=True)
            if self._outcome == "fail":
                raise SidecarError("上游 500")
        return TurnResult(text="ok")

    def _release(self, outcome: str) -> bool:
        self._outcome = outcome
        self._go.set()
        return True

    def stop(self, *_args) -> bool:
        return self._release("stop")

    def finish(self) -> None:
        self._release("answer")

    def fail(self) -> None:
        self._release("fail")


@pytest.fixture
def turn(monkeypatch):
    fake = _StoppableTurn()
    monkeypatch.setattr(host, "run_turn", fake)
    #: 「停止」走的那条路:宿主叫 sidecar 中止这一轮 —— 这里让替身那一轮以 aborted 收尾。
    monkeypatch.setattr(host, "abort_turn", fake.stop)
    yield fake
    fake.finish()


def _settled(session_id: str, seconds: float = 30) -> None:
    """等到这段对话空闲、而且没有在跑的回合线程。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        with SessionLocal() as db:
            if db.get(AgentSession, session_id).status != "running" and host.wait_for_idle_turns(timeout=0.2):
                return
        time.sleep(0.05)
    raise AssertionError("这段对话一直没停下来")


def _queue(client, sid: str) -> list[tuple[str, bool]]:
    return [(m["content"], bool((m.get("payload") or {}).get("held"))) for m in client.get(f"/api/agent/sessions/{sid}/queue").json()]


def _start_with_two_queued(client) -> str:
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "two"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "three"})
    assert _queue(client, sid) == [("two", False), ("three", False)]
    return sid


def test_按了停止_排着的两句扣下_不自动跑(turn) -> None:
    client = fresh_client()
    sid = _start_with_two_queued(client)

    assert client.post(f"/api/agent/sessions/{sid}/stop").json() == {"stopped": True}
    #: drain 跑在那一轮的线程里、收尾之后:它起了下一轮的话,新的回合线程还活着,_settled 会一直等到它跑完。
    _settled(sid)

    assert turn.prompts == ["one"], "停止之后排着的话自己跑了"
    assert _queue(client, sid) == [("two", True), ("three", True)], "扣下的要留在队列里,带着 held"
    with SessionLocal() as db:
        assert db.get(AgentSession, sid).status == "idle"
        #: 扣下的不算「有东西在等」:别处来的 drain(任务回执、整理完上下文)不该为它们抢占这段对话 ——
        #: 抢了又放,界面上就闪一下「思考中」。
        assert not host._claim_idle_session(db, sid, only_if_queued=True)
        db.rollback()


def test_继续发送_那一句当场开跑_另一句还扣着(turn) -> None:
    client = fresh_client()
    sid = _start_with_two_queued(client)
    client.post(f"/api/agent/sessions/{sid}/stop")
    _settled(sid)
    three = next(m["id"] for m in client.get(f"/api/agent/sessions/{sid}/queue").json() if m["content"] == "three")

    resumed = client.post(f"/api/agent/sessions/{sid}/queue/{three}/resume")
    assert resumed.status_code == 200, resumed.text
    _settled(sid)

    assert turn.prompts == ["one", "three"], turn.prompts
    assert _queue(client, sid) == [("two", True)]


def test_扣下之后又说了一句_那一轮照常跑_扣下的还等着(turn) -> None:
    client = fresh_client()
    sid = _start_with_two_queued(client)
    client.post(f"/api/agent/sessions/{sid}/stop")
    _settled(sid)

    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "four"})
    _settled(sid)

    assert turn.prompts == ["one", "four"], turn.prompts
    assert _queue(client, sid) == [("two", True), ("three", True)]


def test_不是用户停的_出错了_排着的照常接着跑(turn) -> None:
    client = fresh_client()
    sid = _start_with_two_queued(client)

    turn.fail()
    deadline = time.time() + 30
    while time.time() < deadline and len(turn.prompts) < 3:
        time.sleep(0.05)
    _settled(sid)

    assert turn.prompts == ["one", "two", "three"], turn.prompts
    assert _queue(client, sid) == []


def test_继续发送只认还在排队的那条(turn) -> None:
    client = fresh_client()
    sid = _start_with_two_queued(client)
    answered = next(m["id"] for m in client.get(f"/api/agent/sessions/{sid}/messages").json() if m["content"] == "one")
    assert client.post(f"/api/agent/sessions/{sid}/queue/{answered}/resume").status_code == 409
    assert client.post(f"/api/agent/sessions/{sid}/queue/no-such-message/resume").status_code == 409
    turn.finish()
    _settled(sid)
