"""排队那条消息**一定会跑,而且只跑一遍**。

这两件事各自对应一个竞态,都发生在「读会话状态」和「写会话状态」不是一步的那道缝里:

**丢唤醒。** 决定排队是「读到 running」和「把消息落库」两步。中间那一轮完全可能跑完并
drain 过一次 —— 那次看到的队列还是空的,而消息随后才落库。于是它躺在一个 idle 的会话里,
再也没有下一轮来捞它。用户看到的是「发过去没反应」,日志里什么都没有。

**跑两遍。** 两个 drain 同时读到 idle、同时取走同一条消息、同时起一轮,那条消息会被回答两次。

两个都不会在日常使用里天天出现,但都会在机器忙的时候出现,而且都**不报错**。

## 「跑两遍」那一半没有测试,是有意的

试过三种办法逼它发生:两个线程直接撞、在取消息处设栅栏、在读状态处设栅栏。**三种都逼不出来**
—— 抢占改回"读一次再写"之后,测试照样全绿。原因是 SQLite 把写串起来了:第二个 drain 再去
查队列时,第一个早已把那条消息出队并提交,于是它查到的是空的,自己就退了。

也就是说,在当前这个后端上,抢占更像**防御**而不是在修一个能复现的故障;它挡的是"写不被串起来"
的那类后端(以及将来把状态判断挪到别处的改动)。与其留一条无论代码对错都绿的测试充数,
不如把这件事写在这儿 —— 一条永远不会红的测试比没有测试更糟,它会让人以为这里有把关。
"""

from __future__ import annotations

import time

from app.ai.sidecar.adapters import TurnResult
from app.core.db import SessionLocal
from app.db.models import AgentMessage, AgentSession
from app.domain.agent import host
from tests.test_agent_queue import _session, _status, _wait_until
from tests.util import fresh_client


def _queue_one(session_id: str, content: str = "排队的") -> None:
    """直接往库里放一条排队消息 —— 绕开发消息那条路,好把 drain 单独拿出来测。"""
    with SessionLocal() as db:
        user_id = db.query(AgentMessage).first()
        owner = db.execute(  # 会话的创建者就是唯一那个用户
            __import__("sqlalchemy").select(__import__("app.db.models", fromlist=["User"]).User)
        ).scalars().first()
        db.add(
            AgentMessage(
                session_id=session_id,
                role="user",
                content=content,
                payload={"queued": True, "queued_by": owner.id},
            )
        )
        db.commit()


def _settle(session_id: str, seconds: float = 10) -> None:
    """**退出前等自己起的那几轮跑完。**

    不等的话,后台那个线程会活过这条测试,而下一条测试一上来就把库 drop 掉重建 —— 掉队的
    线程正握着 SQLite 的写锁往里写,于是下一条测试的写全被堵住,表现成"莫名其妙卡三十秒"。
    单独跑它是绿的,一起跑就红,而红的地方和真正的原因隔着一整条测试。
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        with SessionLocal() as db:
            session = db.get(AgentSession, session_id)
            if session is None or session.status != "running":
                return
        time.sleep(0.05)


def _set_status(session_id: str, status: str) -> None:
    with SessionLocal() as db:
        db.get(AgentSession, session_id).status = status
        db.commit()


def test_抢到了却没活干_要把状态放回去(monkeypatch) -> None:
    """抢占之后才发现队列是空的 —— 不放回 idle 的话,这个会话永远停在 running,
    之后每一条消息都会被当成"正忙"排进一个再也不会被 drain 的队列。整个会话就此哑掉。"""
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: TurnResult(text="ok"))
    client = fresh_client()
    sid = _session(client)
    _set_status(sid, "idle")

    host._drain_queue(sid)  # 队列是空的

    assert _status(sid) == "idle", "抢占之后没放回状态,会话哑了"


def test_排队落库之后自己再_drain_一次(monkeypatch) -> None:
    """这是丢唤醒那一半的补丁:**写完之后再看一眼**,所以看得见自己刚写的东西。

    上一轮还在跑的话,这一下抢不到会话、直接让位,消息由那一轮结束时的 drain 接走 ——
    两边都不会漏,也不会重。
    """
    drained: list[str] = []
    original = host._drain_queue
    monkeypatch.setattr(host, "_drain_queue", lambda sid: drained.append(sid) or original(sid))
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: (time.sleep(0.4), TurnResult(text="ok"))[1])

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "先干这个"})
    _wait_until(lambda: _status(sid) == "running")
    drained.clear()
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "排队的"})

    assert sid in drained, "排队落库之后没有再 drain —— 丢唤醒的那道缝还开着"
    _settle(sid)


def test_排队的消息最终会跑起来(monkeypatch) -> None:
    """把两件事合起来看的那条:发过去的消息,不管撞上哪道缝,最后都得跑。"""
    prompts: list[str] = []

    def _capture(*args, **kwargs):
        prompts.append(args[1] if len(args) > 1 else kwargs.get("prompt", ""))
        time.sleep(0.05)
        return TurnResult(text="ok")

    monkeypatch.setattr(host, "run_turn", _capture)
    client = fresh_client()
    sid = _session(client)

    for i in range(12):
        client.post(f"/api/agent/sessions/{sid}/messages", json={"content": f"第 {i} 条"})

    def _queued_left() -> int:
        with SessionLocal() as db:
            return len([
                m for m in db.query(AgentMessage).filter(AgentMessage.session_id == sid).all()
                if (m.payload or {}).get("queued")
            ])

    # **不要把 status 写进判据。** 每一轮结束都会再 drain 一次,而 drain 是"先抢占再看队列" ——
    # 队列空了它也会把 status 短暂翻成 running 再放回去。于是"idle 且队列空"这个条件会在
    # 真正的终态上**反复地真一下假一下**,等到它成立、下一行再读又不成立了。
    # 这个文件修的就是这类毛病,判据自己不能再犯:只看那两件真正在断言的事。
    # 轮询要**放慢**。这条判据每次都要开一个数据库会话,而 SQLite 同一时刻只容得下一个写者 ——
    # 20 毫秒一次地问,等于和干活的那几个线程抢锁,队列反而推不动(实测:快轮询时 30 秒都排不完,
    # 改成 200 毫秒问一次立刻就完)。测量动作本身不该改变被测的东西。
    deadline = time.time() + 30
    while time.time() < deadline and not (len(prompts) == 12 and _queued_left() == 0):
        time.sleep(0.2)
    assert len(prompts) == 12, f"跑起来的轮数不对(应为 12):{len(prompts)}"
    assert _queued_left() == 0, "还有消息压在队列里"
