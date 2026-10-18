"""一轮跑到一半进程死了,「做到哪一步」要还在。

维护者 2026-10-18 拍板(#5):接受每次工具事件的 DB 写,换来回看时看得到那一轮做过的每一步。
此前 timeline 只在内存里,`reconcile_orphaned_agent_sessions` 只补一句「已中断」——用户只看到
「已中断」,子代理、工具卡、做到哪一步全没了。

这里模拟的是**进程死掉**:内存里的流状态被丢掉,只剩库里已经落下的那些行;然后调重启收尾。
"""

from __future__ import annotations

from app.ai.sidecar.pi_client import TurnResult
from app.core.db import SessionLocal
from app.db.agent_turn_events import latest_turn_id, turn_events
from app.db.models import AgentSession
from app.domain.agent import host
from app.domain.agent import stream as agent_stream
from tests.util import add_provider, fresh_client


def _session(client) -> dict:
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    return client.post(
        "/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": workspace["id"]}
    ).json()


def _configured(client) -> None:
    with SessionLocal() as db:
        add_provider(
            db, name="P", vendor="openai-compatible", base_url="http://localhost:1/v1",
            api_key="k", model="m", capability_ids=["chat"],
        )
        db.commit()


def _stream_a_turn_with_a_tool_and_a_subagent(session_id: str) -> None:
    agent_stream._stream_reset(session_id)
    agent_stream._stream_append(session_id, "我先看看素材。")
    agent_stream._stream_tool_event(
        session_id, {"type": "tool_start", "toolCallId": "c1", "name": "list_assets", "args": {"kind": "video"}}
    )
    agent_stream._stream_tool_event(
        session_id, {"type": "tool_end", "toolCallId": "c1", "result": {"items": 2}, "isError": False}
    )
    agent_stream._stream_tool_event(
        session_id, {"type": "tool_start", "toolCallId": "p1", "name": "run_subagent", "args": {"task": "查素材"}}
    )
    agent_stream._stream_tool_event(
        session_id,
        {"type": "subtool", "phase": "start", "parentCallId": "p1", "toolCallId": "s1",
         "toolName": "list_assets", "args": {}},
    )
    agent_stream._stream_tool_event(
        session_id,
        {"type": "subtool", "phase": "end", "parentCallId": "p1", "toolCallId": "s1",
         "toolName": "list_assets", "result": {"ok": True}, "isError": False},
    )
    agent_stream._stream_tool_event(
        session_id,
        {"type": "subagent_result", "parentCallId": "p1", "archive": {"steps": 1, "trace": []}},
    )


def _restart() -> None:
    """模拟进程死掉:内存里的那一份没了,库里的留着 —— 那正是要断言的部分。"""
    agent_stream._streams.clear()  # type: ignore[attr-defined]


def test_中断的那一轮把工具与子代理做到哪一步附在中断消息上() -> None:
    client = fresh_client()
    session = _session(client)
    session_id = session["id"]
    _stream_a_turn_with_a_tool_and_a_subagent(session_id)

    # 先证明**事件在跑的当时就落了库**,不是收尾时才补的 —— 收尾在重启这条路上根本不会执行。
    with SessionLocal() as db:
        rows = turn_events(db, session_id)
        kinds = [row["kind"] for row in rows]
        assert kinds == [
            "tool_start", "tool_end", "tool_start", "subtool", "subtool", "subagent_result",
        ], kinds
        turn_id = latest_turn_id(db, session_id)
        assert turn_id

    _restart()

    with SessionLocal() as db:
        db.get(AgentSession, session_id).status = "running"
        db.commit()
        assert host.reconcile_orphaned_agent_sessions(db) == 1
        db.commit()

    interrupted = client.get(f"/api/agent/sessions/{session_id}/messages").json()[-1]
    assert interrupted["error"] == "backend restarted mid-turn"
    assert interrupted["payload"]["error_kind"] == "restart"
    timeline = interrupted["payload"]["timeline"]
    tools = {
        item["tool"]["id"]: item
        for item in timeline
        if item.get("type") in ("tool", "subtool") and isinstance(item.get("tool"), dict)
    }
    assert tools["c1"]["tool"]["name"] == "list_assets"
    assert tools["c1"]["tool"]["status"] == "done"
    assert tools["p1"]["tool"]["result"]["details"]["subagent"]["steps"] == 1
    assert tools["s1"]["parent_id"] == "p1"
    assert tools["s1"]["tool"]["status"] == "done"

    # 收尾标记:那一轮的事件已经删掉,再拨一次不会再生出第二条中断说明、也不会重复附加。
    with SessionLocal() as db:
        assert host.reconcile_orphaned_agent_sessions(db) == 0
        assert turn_events(db, session_id) == []
        db.commit()


def test_不中断的正常轮时间线只有一份且进行中的事件被清掉(monkeypatch) -> None:
    """正常收尾的那一轮,时间线照旧来自内存、写进消息 payload 一次;落库的中间事件要收干净,
    否则下一条消息的 payload 和历史事件各留一份,时间线上会出现两张同样的工具卡。"""

    def fake_run_turn(*args, **kwargs):
        kwargs["on_delta"]("先看看素材。")
        kwargs["on_tool"]({"type": "tool_start", "toolCallId": "c1", "name": "list_assets", "args": {}})
        kwargs["on_tool"]({"type": "tool_end", "toolCallId": "c1", "result": {"items": 2}, "isError": False})
        return TurnResult(text="看完了。")

    monkeypatch.setattr(host, "run_turn", fake_run_turn)
    client = fresh_client()
    _configured(client)
    session = _session(client)
    session_id = session["id"]

    client.post(f"/api/agent/sessions/{session_id}/messages", json={"content": "看看素材"})
    assert host.wait_for_idle_turns()

    messages = client.get(f"/api/agent/sessions/{session_id}/messages").json()
    assistant = messages[-1]
    assert assistant["error"] is None
    timeline = assistant["payload"]["timeline"]
    tool_ids = [item["tool"]["id"] for item in timeline if item.get("type") == "tool"]
    assert tool_ids == ["c1"], timeline
    assert timeline.count(next(item for item in timeline if item.get("type") == "tool")) == 1

    with SessionLocal() as db:
        assert turn_events(db, session_id) == []


def test_同一个事件写两次是覆盖_顺序按seq() -> None:
    """`(turn_id, seq)` 唯一:重写同一个事件是覆盖,不是多一行。顺序就是 seq 的顺序 ——
    事件可能从两条回调路径并发写,提交先后不能当作发生先后。"""
    from app.db.agent_turn_events import record_turn_event

    fresh_client()
    card = {"type": "tool", "tool": {"id": "c1", "name": "list_assets", "status": "running"}}
    record_turn_event(session_id="s-idem", turn_id="t-idem", seq=1, kind="tool_start", payload=card)
    record_turn_event(
        session_id="s-idem", turn_id="t-idem", seq=1, kind="tool_end",
        payload={"type": "tool", "tool": {"id": "c1", "name": "list_assets", "status": "done"}},
    )
    record_turn_event(
        session_id="s-idem", turn_id="t-idem", seq=2, kind="tool_start",
        payload={"type": "tool", "tool": {"id": "c2", "name": "view_scene", "status": "running"}},
    )

    with SessionLocal() as db:
        rows = turn_events(db, "s-idem")
    assert [(row["seq"], row["kind"]) for row in rows] == [(1, "tool_end"), (2, "tool_start")]
    assert rows[0]["payload"]["tool"]["status"] == "done"


def test_迁移为已有库建出这张表且重跑安全() -> None:
    """这张表**不在 `Base.metadata` 里**(它是过程日志),`create_all` 看不见它 —— 已有库靠
    `migrate-agent-turn-events-table` 补上。验:旧库里没有它时建出来(列、唯一键),
    再跑一次什么都不做。
    """
    from sqlalchemy import inspect, text

    from app.core.db import engine
    from app.db import migrations

    fresh_client()
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS agent_turn_events"))

    migrations._migrate_agent_turn_events_table()

    inspector = inspect(engine)
    assert "agent_turn_events" in set(inspector.get_table_names())
    assert {column["name"] for column in inspector.get_columns("agent_turn_events")} == {
        "id", "session_id", "turn_id", "seq", "kind", "payload", "created_at",
    }
    unique = {
        tuple(item["column_names"]) for item in inspector.get_unique_constraints("agent_turn_events")
    }
    assert ("turn_id", "seq") in unique

    migrations._migrate_agent_turn_events_table()  # 重跑安全

