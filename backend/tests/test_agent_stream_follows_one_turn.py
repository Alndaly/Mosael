"""一条智能体流只属于一轮(`GET /agent/sessions/{id}/stream`)。

下一轮可能在上一轮收尾后几毫秒内就起来(回执、答完问题都会接着起一轮),比流 0.1 秒一次的轮询快:
上一轮的 done 没被看到,流状态已经换成新的一轮。此前流就这么接着往下发,而客户端那边 running 从没
变成 false、不会重接 —— 维护者看到的是「明明跑了很多,界面一直停在 ask_user」。现在换轮就关流,
客户端重新接上新的这一轮;每一帧带着这一轮的开始时间,「已用 …」从它算。
"""

from __future__ import annotations

import json
import threading
import time

import httpx
import uvicorn

from app.domain.agent import stream as agent_stream
from app.main import app
from tests.util import free_port, fresh_client


def _frame(line: str) -> dict:
    assert line.startswith("data: "), line
    return json.loads(line.removeprefix("data: "))


def test_换了一轮就关流_每一帧带着这一轮的开始时间() -> None:
    client = fresh_client()
    token = client.headers["Authorization"]
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    session = client.post("/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": ws}).json()["id"]
    agent_stream._stream_reset(session)
    started = agent_stream.get_stream_state(session)["started_at"]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=free_port(), log_level="warning",
                                           lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        base = f"http://127.0.0.1:{server.config.port}/api"
        with httpx.Client(base_url=base, timeout=10, trust_env=False, headers={"Authorization": token}) as http, \
                http.stream("GET", f"/agent/sessions/{session}/stream") as live:
            lines = (line for line in live.iter_lines() if line)
            first = _frame(next(lines))
            assert first["done"] is False
            assert first["started_at"].startswith(started.isoformat()[:19])
            # 上一轮收尾、下一轮紧接着起来 —— 在同一把锁里,流根本没机会看到 done。
            with agent_stream._streams_lock:
                agent_stream._streams[session]["done"] = True
                agent_stream._streams[session]["seq"] += 1
            agent_stream._stream_reset(session)
            agent_stream._stream_append(session, "新的一轮")
            rest = [_frame(line) for line in lines]
            assert all(frame["text"] != "新的一轮" for frame in rest), "新的一轮不接在上一轮的流后面"
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        with agent_stream._streams_lock:
            agent_stream._streams.pop(session, None)


def test_finished_streams_are_evicted_after_the_retention_window(monkeypatch) -> None:
    """收尾后的流只留一小段给前端读 done;不回收就是每个用过的会话永久占一份正文和 timeline。"""
    session = "stream-eviction"
    agent_stream._stream_reset(session)
    agent_stream._stream_finish(session, "答完了")
    with agent_stream._streams_lock:
        assert session in agent_stream._streams

    monkeypatch.setattr(agent_stream, "STREAM_RETENTION_SECONDS", 0.0)
    state = agent_stream.get_stream_state(session)
    assert state["done"] is True
    with agent_stream._streams_lock:
        assert session not in agent_stream._streams, "收尾后的流状态没有被回收"
