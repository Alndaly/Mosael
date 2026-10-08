"""手动「立即整理上下文」期间,这段对话是占着的(智能体那一路 AGENT-5)。

现场(隔离环境 + 假模型,摘要拖 12 秒):6 轮之后点压缩,2 秒后发「记住暗号是 蓝鲸42」—— 这一轮先答完,压缩随后写回:
模型记忆里没有「蓝鲸42」,下一轮也没有;反过来的顺序则是那一轮把压缩结果整个盖掉(压缩白做、照样计费)。压缩此前不认领
这段对话,两边各读一份记忆、各写回一份。

现在:压缩认领这段对话(和一轮同一个条件更新);压缩期间发来的话进队,压完再跑,跑的时候拿的是压过的记忆;有一轮在跑时不压。
"""

from __future__ import annotations

import threading

from app.ai.sidecar import pi_client
from app.ai.sidecar.pi_client import CompactionResult, TurnResult
from app.core.db import SessionLocal
from app.db.models import AgentMessage, AgentSession
from app.domain.agent import host
from tests.test_agent_queue import _session, _wait_idle, _wait_until
from tests.util import fresh_client


def test_压缩期间发的话排在压缩后面_用的是压过的记忆(monkeypatch) -> None:
    started, release = threading.Event(), threading.Event()

    def slow_compaction(**kwargs):
        started.set()
        assert release.wait(10)
        return CompactionResult(adapter_state=[{"role": "user", "content": "【交接说明】早期对话"}], context=None,
                                compaction={"droppedMessages": 6, "tokensBefore": 900, "tokensAfter": 100, "summary": "早期对话"})

    seen_states: list[object] = []

    def turn(*_args, adapter_state=None, prompt="", **_kwargs):
        seen_states.append(adapter_state)
        return TurnResult(text=f"答:{prompt[-12:]}", adapter_state=[*(adapter_state or []), {"role": "user", "content": prompt}])

    monkeypatch.setattr(host, "compact_session", slow_compaction)
    monkeypatch.setattr(host, "run_turn", turn)
    client = fresh_client()
    sid = _session(client)
    with SessionLocal() as db:
        db.get(AgentSession, sid).adapter_state = [{"role": "user", "content": "很早的话"}]
        db.commit()

    out: dict[str, object] = {}
    worker = threading.Thread(target=lambda: out.setdefault("r", client.post(f"/api/agent/sessions/{sid}/compact")))
    worker.start()
    assert started.wait(10)
    with SessionLocal() as db:
        assert db.get(AgentSession, sid).status == "running", "压缩期间这段对话没被占着"

    sent = client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "记住暗号是 蓝鲸42"})
    assert sent.status_code == 200
    assert (sent.json().get("payload") or {}).get("queued"), "压缩期间发的话应当排队,不是马上起一轮"
    assert seen_states == [], "压缩还没完,那一轮已经开跑了"

    release.set()
    worker.join(10)
    assert out["r"].status_code == 200, out["r"].text
    _wait_until(lambda: len(seen_states) == 1)
    _wait_idle(sid)
    assert seen_states[0] == [{"role": "user", "content": "【交接说明】早期对话"}], "排着的那句拿到的不是压过的记忆"
    with SessionLocal() as db:
        state = db.get(AgentSession, sid).adapter_state
        assert "蓝鲸42" in str(state), "压缩期间说的那句从记忆里丢了"
        assert "交接说明" in str(state)
        notes = db.query(AgentMessage).filter(AgentMessage.session_id == sid, AgentMessage.role == "system").count()
        assert notes == 1


def test_正在回答时不压_压完或压失败都放开这段对话(monkeypatch) -> None:
    client = fresh_client()
    sid = _session(client)
    with SessionLocal() as db:
        db.get(AgentSession, sid).status = "running"
        db.commit()
    busy = client.post(f"/api/agent/sessions/{sid}/compact")
    assert busy.status_code == 409, busy.text
    with SessionLocal() as db:
        db.get(AgentSession, sid).status = "idle"
        db.commit()

    def broken(**_kwargs):
        raise pi_client.SidecarError("摘要失败")

    monkeypatch.setattr(host, "compact_session", broken)
    failed = client.post(f"/api/agent/sessions/{sid}/compact")
    assert failed.status_code == 502
    with SessionLocal() as db:
        assert db.get(AgentSession, sid).status == "idle", "压缩失败之后这段对话一直被占着"
