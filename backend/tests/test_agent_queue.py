"""Queue by default, steer on purpose.

These are two different things and only one of them can be the default. Queuing waits for the
whole reason-act loop to finish and then runs as its own turn — what a follow-up almost always
means. Steering cuts into the running loop and changes what the agent does next, which is
powerful and wrong to apply to every message someone happens to send early.

Every mid-turn message used to be steered, so several questions merged into one answer and
the earlier ones read as ignored.
"""

from __future__ import annotations

import time

from app.ai.agent import host
from app.ai.agent.adapters import TurnResult
from app.core.db import SessionLocal
from app.db.models import AgentMessage, AgentSession, ProviderUsageEvent
from tests.util import fresh_client


def _slow_turn(*args, **kwargs):
    time.sleep(0.8)
    return TurnResult(text="ok")


def _session(client):
    """建会话,并让这个部署有一个可用的对话模型。

    取默认模型没有"随便挑一个"的兜底(见 provider_models.resolve_default),所以"这个部署能对话"
    必须被显式配出来 —— 真实部署里也是管理员配完连接顺手指定默认的那一步。
    """
    from app.core.db import SessionLocal
    from tests.util import add_provider

    with SessionLocal() as db:
        add_provider(
            db, name="P", vendor="openai-compatible", base_url="http://localhost:1/v1",
            api_key="k", model="m", capability_ids=["chat"],
        )
        db.commit()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    return client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()["id"]


def _wait_until(predicate, seconds: float = 8) -> None:
    """等一个**具体的事实**成立。

    「看起来空闲了」是间接判据,而间接判据在并发里会在错误的一瞬成立(见 _wait_idle 的注释,
    以及它挡不住的那一瞬:出队之后、状态翻成 running 之前)。断言什么就等什么。
    """
    deadline = time.time() + seconds
    while time.time() < deadline and not predicate():
        time.sleep(0.02)


def _wait_idle(session_id: str, seconds: float = 8) -> str:
    """真正空闲 = 状态非 running **且**队列已空。

    只看状态是不够的:一个 turn 结束到队列里下一个 turn 启动之间有一段空隙,状态在那一瞬就是
    idle。在那里返回,排队的 turn 就会在**下一个测试**里才真正跑起来——而下一个测试早已把
    `host.run_turn` monkeypatch 成了自己的记录器,于是上个测试的提示词串进本测试的断言
    (曾表现为 prompts == ['two', 'one', 'two', 'three'])。这类失败按测试顺序与机器速度
    概率出现,查起来极贵,所以判据必须一次写对。
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        with SessionLocal() as db:
            session = db.get(AgentSession, session_id)
            status = session.status
            pending = len(host.queued_messages(db, session))
        if status != "running" and pending == 0:
            return status
        time.sleep(0.05)
    return "running"


def test_a_mid_turn_message_is_queued_not_steered(monkeypatch) -> None:
    """The default must not touch the running turn."""
    steers: list[str] = []
    monkeypatch.setattr(host, "run_turn", _slow_turn)
    monkeypatch.setattr(host, "steer_turn", lambda sid, text, mode="steer": steers.append(text) or True)

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "two"})

    assert steers == [], "the queued message was pushed into the running turn"
    assert [m["content"] for m in client.get(f"/api/agent/sessions/{sid}/queue").json()] == ["two"]
    assert _wait_idle(sid) == "idle"


def test_a_queued_message_runs_as_its_own_turn_when_the_first_ends(monkeypatch) -> None:
    """The point of queuing: it gets answered on its own terms, not merged into the answer
    that was already in flight."""
    prompts: list[str] = []

    def record(*args, **kwargs):
        prompts.append(kwargs.get("prompt") or args[0] if args else kwargs.get("prompt"))
        time.sleep(0.3)
        return TurnResult(text="ok")

    monkeypatch.setattr(host, "run_turn", lambda *a, **kw: (prompts.append(kw["prompt"]), time.sleep(0.2), TurnResult(text="ok"))[-1])

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "two"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "three"})

    assert _wait_idle(sid) == "idle"
    assert prompts == ["one", "two", "three"], prompts
    assert client.get(f"/api/agent/sessions/{sid}/queue").json() == []


def test_a_queued_message_keeps_hidden_context(monkeypatch) -> None:
    prompts: list[str] = []
    monkeypatch.setattr(
        host,
        "run_turn",
        lambda *a, **kw: (prompts.append(kw["prompt"]), time.sleep(0.2), TurnResult(text="ok"))[-1],
    )

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    client.post(
        f"/api/agent/sessions/{sid}/messages",
        json={"content": "two", "context": "当前工作流 workflow_id=w1"},
    )

    queued = client.get(f"/api/agent/sessions/{sid}/queue").json()
    assert [m["content"] for m in queued] == ["two"]
    # 等的是**这两个 turn 都跑过了**,不是"看起来空闲了"。
    # 出队和「状态翻成 running」之间有一瞬:在那一瞬采样,队列已空、状态还没翻,
    # `_wait_idle` 就会提前返回,而第二个 turn 其实还没开始 —— 于是 prompts 只有一条。
    # 这条按机器负载概率性变红(实测跑三遍全量红两遍),等错了东西比等得不够久更难查。
    _wait_until(lambda: len(prompts) == 2)
    assert _wait_idle(sid) == "idle"
    assert prompts == ["one", "当前工作流 workflow_id=w1\n\n用户消息:\ntwo"], prompts


def test_steering_is_opt_in_per_message(monkeypatch) -> None:
    steers: list[str] = []
    monkeypatch.setattr(host, "run_turn", _slow_turn)
    monkeypatch.setattr(host, "steer_turn", lambda sid, text, mode="steer": steers.append(text) or True)

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    client.post(
        f"/api/agent/sessions/{sid}/messages",
        json={"content": "改成竖屏", "context": "当前工作流 workflow_id=w1"},
    )
    queued = client.get(f"/api/agent/sessions/{sid}/queue").json()

    res = client.post(f"/api/agent/sessions/{sid}/queue/{queued[0]['id']}/steer")

    assert res.status_code == 200 and res.json() == {"steered": True}
    assert steers == ["当前工作流 workflow_id=w1\n\n用户消息:\n改成竖屏"]
    # It left the queue: steering it and then running it again would answer it twice.
    assert client.get(f"/api/agent/sessions/{sid}/queue").json() == []
    assert _wait_idle(sid) == "idle"


def test_steering_when_the_turn_already_ended_leaves_it_queued(monkeypatch) -> None:
    """Reporting a failure the user cannot act on is worse than letting it run on its own."""
    monkeypatch.setattr(host, "run_turn", _slow_turn)
    monkeypatch.setattr(host, "steer_turn", lambda sid, text, mode="steer": False)

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "two"})
    queued = client.get(f"/api/agent/sessions/{sid}/queue").json()

    res = client.post(f"/api/agent/sessions/{sid}/queue/{queued[0]['id']}/steer")

    assert res.status_code == 200 and res.json() == {"steered": False}
    assert [m["content"] for m in client.get(f"/api/agent/sessions/{sid}/queue").json()] == ["two"]
    assert _wait_idle(sid) == "idle"


def test_a_queued_message_can_be_withdrawn(monkeypatch) -> None:
    monkeypatch.setattr(host, "run_turn", _slow_turn)

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "two"})
    queued = client.get(f"/api/agent/sessions/{sid}/queue").json()

    assert client.delete(f"/api/agent/sessions/{sid}/queue/{queued[0]['id']}").status_code == 200
    assert client.get(f"/api/agent/sessions/{sid}/queue").json() == []
    assert _wait_idle(sid) == "idle"
    with SessionLocal() as db:
        assert db.get(AgentMessage, queued[0]["id"]) is None


def test_the_message_being_answered_is_not_in_the_queue(monkeypatch) -> None:
    monkeypatch.setattr(host, "run_turn", _slow_turn)
    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "one"})
    assert client.get(f"/api/agent/sessions/{sid}/queue").json() == []
    assert _wait_idle(sid) == "idle"


def test_nothing_is_queued_when_idle() -> None:
    client = fresh_client()
    sid = _session(client)
    assert client.get(f"/api/agent/sessions/{sid}/queue").json() == []


def test_agent_usage_events_are_scoped_to_session_messages() -> None:
    client = fresh_client()
    sid = _session(client)
    other_sid = _session(client)

    with SessionLocal() as db:
        message = AgentMessage(session_id=sid, role="assistant", content="ok")
        other_message = AgentMessage(session_id=other_sid, role="assistant", content="nope")
        db.add_all([message, other_message])
        db.flush()
        message_id = message.id
        other_message_id = other_message.id
        db.add(
            ProviderUsageEvent(
                workspace_id=db.get(AgentSession, sid).workspace_id,
                provider="openai-compatible",
                model="deepseek-v4-pro",
                capability="chat",
                operation="agent_chat",
                idempotency_key="agent-usage-visible",
                agent_message_id=message_id,
                duration_seconds=2.5,
                units={"input_tokens": 12, "output_tokens": 34},
                cost_micros=123,
                currency="USD",
                cost_confidence="estimated",
            )
        )
        db.add(
            ProviderUsageEvent(
                workspace_id=db.get(AgentSession, other_sid).workspace_id,
                provider="openai-compatible",
                model="deepseek-v4-pro",
                capability="chat",
                operation="agent_chat",
                idempotency_key="agent-usage-hidden",
                agent_message_id=other_message_id,
                units={"input_tokens": 99},
            )
        )
        db.commit()

    events = client.get(f"/api/agent/sessions/{sid}/usage-events").json()
    assert len(events) == 1
    assert events[0]["agent_message_id"] == message_id
    assert events[0]["units"] == {"input_tokens": 12, "output_tokens": 34}
    assert events[0]["cost_micros"] == 123


def test_the_transcript_interleaves_questions_and_answers(monkeypatch) -> None:
    """A queued message must land in the transcript where it was SENT, not where it was typed.

    Messages are ordered by created_at, and a queued one is stamped the moment the user hits
    enter — long before the agent gets to it. Left at that timestamp it sorts ahead of the
    previous turn's answer, and the conversation reads as every question in a row followed by
    every answer in a row, which is exactly what it looked like.
    """
    monkeypatch.setattr(
        host,
        "run_turn",
        lambda *a, **kw: (time.sleep(0.2), TurnResult(text=f"答:{kw['prompt']}"))[-1],
    )

    client = fresh_client()
    sid = _session(client)
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "一"})
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "二"})
    assert _wait_idle(sid) == "idle"

    transcript = [(m["role"], m["content"]) for m in client.get(f"/api/agent/sessions/{sid}/messages").json()]

    assert transcript == [
        ("user", "一"),
        ("assistant", "答:一"),
        ("user", "二"),
        ("assistant", "答:二"),
    ], transcript


def test_a_steered_message_also_lands_at_the_moment_it_was_sent(monkeypatch) -> None:
    """Same rule for the other path: it joins the conversation when it is cut in."""
    monkeypatch.setattr(host, "run_turn", _slow_turn)
    monkeypatch.setattr(host, "steer_turn", lambda sid, text, mode="steer": True)

    client = fresh_client()
    sid = _session(client)
    first = client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "一"}).json()
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "改一下"})
    queued = client.get(f"/api/agent/sessions/{sid}/queue").json()
    client.post(f"/api/agent/sessions/{sid}/queue/{queued[0]['id']}/steer")

    with SessionLocal() as db:
        steered = db.get(AgentMessage, queued[0]["id"])
        original = db.get(AgentMessage, first["id"])
        assert steered.created_at >= original.created_at
        assert not (steered.payload or {}).get("queued")
    assert _wait_idle(sid) == "idle"


def test_另一个智能体发来的通知_不夺标题_且带结构化来源(monkeypatch) -> None:
    """notify_agent_session 的消息走同一个 /messages 端点,但它不是"人提的第一件事":
    「新对话」的自动命名要跳过它,payload 要带 from_agent_session —— 前端徽章、
    以及一切"这条是谁发的"的判断,都以这个结构化字段为准,不做信封文案匹配。"""
    monkeypatch.setattr(host, "run_turn", lambda *a, **k: TurnResult(text="ok"))

    client = fresh_client()
    sid = _session(client)
    client.post(
        f"/api/agent/sessions/{sid}/messages",
        json={"content": "【通知】请汇报进展", "origin_session_id": "peer-session-1"},
    )
    assert _wait_idle(sid) == "idle"

    with SessionLocal() as db:
        session = db.get(AgentSession, sid)
        assert session.title == "新对话", "通知不该顶掉待命名的会话标题"
        message = (
            db.query(AgentMessage)
            .filter(AgentMessage.session_id == sid, AgentMessage.role == "user")
            .order_by(AgentMessage.created_at.desc())
            .first()
        )
        assert (message.payload or {}).get("from_agent_session") == "peer-session-1"

    # 对照:人发的第一条消息仍然照旧命名会话
    sid2 = _session(client)
    client.post(f"/api/agent/sessions/{sid2}/messages", json={"content": "帮我剪个片"})
    assert _wait_idle(sid2) == "idle"
    with SessionLocal() as db:
        assert db.get(AgentSession, sid2).title == "帮我剪个片"


def test_排队的跨会话通知_重放时也带上信封(monkeypatch) -> None:
    """对方正忙时通知先排队,稍后重放 —— 那时信封不能丢。

    信封(「这条来自另一个会话」)只进提示词、不进 content,所以它是在**发起 turn 的那一刻**
    拼上去的。直发那条路顺手就拼了;排队这条晚一点才跑,漏在那里的话,「对方正忙」时发来的
    通知,模型就不知道它来自另一个会话 —— 会当成用户在说话,而这恰恰是最需要区分的场合
    (它可能正准备回复"用户",实际却是在回复另一个智能体)。

    这里直接盯模型收到的那份文本,而不是盯 content —— content 本来就该是干净的。
    """
    prompts: list[str] = []

    def _capture(*args, **kwargs):
        # run_turn(session_id, prompt, token) —— 第二个位置参数就是模型收到的那份
        prompts.append(args[1] if len(args) > 1 else kwargs.get("prompt", ""))
        time.sleep(0.3)
        return TurnResult(text="ok")

    monkeypatch.setattr(host, "run_turn", _capture)

    client = fresh_client()
    sid = _session(client)
    # 第一条把会话占住
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "先干这个"})
    _wait_until(lambda: _status(sid) == "running")
    # 正忙时收到另一个会话的通知 → 应该排队
    client.post(
        f"/api/agent/sessions/{sid}/messages",
        json={"content": "请汇报进展", "origin_session_id": "peer-9"},
    )
    with SessionLocal() as db:
        queued = [
            m for m in db.query(AgentMessage).filter(AgentMessage.session_id == sid).all()
            if (m.payload or {}).get("queued")
        ]
        assert len(queued) == 1, "通知没有排队"
        assert (queued[0].payload or {}).get("from_agent_session") == "peer-9", "排队时把来源丢了"
        assert "【" not in queued[0].content, "信封又被拼进正文了"

    _wait_until(lambda: _status(sid) == "idle", seconds=10)

    assert len(prompts) == 2, f"排队那条没有作为自己的一轮跑起来:{prompts}"
    assert "peer-9" in prompts[1], "重放时信封丢了 —— 模型不知道这条来自另一个会话"
    assert "请汇报进展" in prompts[1]
    assert "【" not in prompts[0], "第一条不是通知,不该有信封"


def _status(session_id: str) -> str:
    with SessionLocal() as db:
        return db.get(AgentSession, session_id).status
