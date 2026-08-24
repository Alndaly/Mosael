"""首 token 打点:一轮里「等第一个字」和「后面一路吐完」是两段,分开才有得优化。

只有轮总时长的话,一轮 30 秒既可能是模型想了 29 秒才开口,也可能是它稳稳吐了 30 秒的长文 ——
这两件事该做的优化正好相反(换模型 / 减输出),而界面上长得一模一样。

这里守的是三件事:只记第一次、思考也算、**测不到就不写这个键**(缺键和 0 是两回事,前端据此
显示「—」而不是一个假的 0.0s)。
"""
from __future__ import annotations

from app.domain.agent import host


def test_first_token_is_stamped_once_and_thinking_counts() -> None:
    session = "s-first-token"
    host._stream_reset(session)
    assert host.get_stream_state(session)["first_token_at"] is None

    # 思考先到 —— 对着「思考中…」等了八秒的人不会因为吐的是思考就觉得自己没在等。
    host._stream_thinking(session, {"type": "thinking", "delta": "想一下"})
    first = host.get_stream_state(session)["first_token_at"]
    assert first is not None

    # 后面的增量不能把这个时刻往后推,否则测出来的永远是"最后一个 token"。
    host._stream_thinking(session, {"type": "thinking", "delta": "再想想"})
    host._stream_append(session, "正文")
    assert host.get_stream_state(session)["first_token_at"] == first


def test_stream_append_alone_also_stamps() -> None:
    """有的链路不发思考事件,直接吐正文 —— 那一刻同样是"第一个字"。"""
    session = "s-first-token-text"
    host._stream_reset(session)
    host._stream_append(session, "直接开说")
    assert host.get_stream_state(session)["first_token_at"] is not None


def test_empty_thinking_delta_does_not_stamp() -> None:
    """空 delta 不是一个 token。让它打点的话,收到一个空事件的轮会报出 ~0s 的首 token。"""
    session = "s-first-token-empty"
    host._stream_reset(session)
    host._stream_thinking(session, {"type": "thinking", "delta": ""})
    assert host.get_stream_state(session)["first_token_at"] is None


def test_usage_omits_first_token_when_never_stamped() -> None:
    """一个 token 都没吐出来过(轮直接失败了)—— 不写这个键,而不是写 0。"""
    import time

    started = time.monotonic()
    assert "first_token_seconds" not in host._usage_from_started(started)
    assert "first_token_seconds" not in host._usage_from_started(started, None)

    usage = host._usage_from_started(started, started + 1.5)
    assert usage["first_token_seconds"] == 1.5
    # 从轮开始算起,所以它必然落在总时长之内。
    assert usage["first_token_seconds"] <= usage["duration_seconds"] + 1.5


def test_prompt_snapshot_only_records_changes() -> None:
    """系统提示只在**变了**的那一轮记一份。

    它不是常量:跨会话记忆、当前任务计划都拼在里面,每轮都可能不一样,而对话里一个字都看不到
    它 —— 排查「它为什么突然改了做法」时,这恰恰是第一现场。

    但每轮存全文就是每轮几 KB 的重复内容(记忆上限还有 4000 字),50 轮就是一份 200KB 的
    payload。存指纹、变了才存全文,于是轨迹上出现的每条 SYSTEM 都真的是一次变化。
    """
    from app.core.db import SessionLocal
    from app.db.models import AgentMessage
    from tests.util import fresh_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"workspace_id": workspace["id"]}).json()

    with SessionLocal() as db:
        # 第一轮:一次都没记过 —— 这就是基线,必须留下,否则轨迹上永远看不到系统提示。
        first = host._prompt_snapshot(db, session["id"], "系统提示 A")
        assert first is not None and first["system"] == "系统提示 A"

        db.add(AgentMessage(session_id=session["id"], role="assistant", content="", payload={"prompt": first}))
        db.commit()

        # 没变:不再记一份。轨迹上多一条一模一样的 SYSTEM 只是噪音。
        assert host._prompt_snapshot(db, session["id"], "系统提示 A") is None

        # 变了(比如刚 remember 了一条、或计划推进了一步):记新的全文。
        changed = host._prompt_snapshot(db, session["id"], "系统提示 A + 新记忆")
        assert changed is not None and changed["system"] == "系统提示 A + 新记忆"
        assert changed["hash"] != first["hash"]
