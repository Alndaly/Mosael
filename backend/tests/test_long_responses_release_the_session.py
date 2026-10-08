"""要发很久的响应(文件、事件流)**不攥着数据库连接**。

请求会话是 yield 依赖,默认在响应发完之后才关;路由里查过一次库,它就一直攥着池子里的一条连接。实测 15 条这样的
响应(播放中的视频是一条慢慢读的 `bytes=0-`,智能体这一轮的 SSE 开到这一轮结束)就把池子(5 + 10)占满,之后**所有**
请求等满 30 秒报 500。所以这类响应只从 `app/api/responses.py` 出:先关会话,再开始发。

两道:路由里不许直接构造 `FileResponse` / `StreamingResponse`(棘轮);起一个真服务、开着文件流和 SSE,
池子里一条连接都不占(端到端)。TestClient 不行 —— 它把整个响应读完才交回来,「正在发」的那一段根本不存在。
"""

from __future__ import annotations

import ast
import pathlib
import threading
import time

import httpx
import uvicorn

from app.core.config import settings
from app.core.db import engine
from app.domain.agent import stream as agent_stream
from app.main import app
from tests.util import first_free_port_of_this_worker, fresh_client, insert_asset

# 进 docs/CONVENTIONS.md 的棘轮清单(scripts/sync-ratchet-docs.py 生成)。
RATCHET = True

API = pathlib.Path(__file__).resolve().parents[1] / "app" / "api"
THE_ONLY_PLACE = API / "responses.py"
LONG_RESPONSES = {"FileResponse", "StreamingResponse"}


def _constructs_a_long_response(path: pathlib.Path) -> list[int]:
    lines = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if name in LONG_RESPONSES:
                lines.append(node.lineno)
    return lines


def test_long_responses_only_come_from_the_helpers() -> None:
    offenders = [
        f"{path.relative_to(API.parent.parent).as_posix()}:{line}"
        for path in sorted(API.rglob("*.py"))
        if path != THE_ONLY_PLACE
        for line in _constructs_a_long_response(path)
    ]
    assert not offenders, (
        "这些地方直接构造了文件 / 流式响应 —— 请求会话会攥着一条连接直到发完。改用 app/api/responses 的 "
        "file_response(db, …) / event_stream(db, …):\n  " + "\n  ".join(offenders)
    )


class _Server:
    def __init__(self) -> None:
        self.port = first_free_port_of_this_worker()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning",
                                                    lifespan="off"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert self.server.started, "test server did not start"
        return f"http://127.0.0.1:{self.port}/api"

    def __exit__(self, *_exc: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=15)


def test_a_playing_video_and_an_open_agent_stream_hold_no_connection() -> None:
    client = fresh_client()
    token = client.headers["Authorization"]
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    media = settings.media_dir / "long-responses"
    media.mkdir(parents=True, exist_ok=True)
    (media / "big.mp4").write_bytes(b"\0" * (16 * 1024 * 1024))
    video = insert_asset(ws, kind="video", name="big", file_key="media/long-responses/big.mp4")
    session = client.post("/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": ws}).json()["id"]
    agent_stream._stream_reset(session)  # 这一轮还在跑
    try:
        with _Server() as base, httpx.Client(base_url=base, timeout=30, trust_env=False,
                                             headers={"Authorization": token}) as http:
            with http.stream("GET", f"/assets/{video}/file", headers={"Range": "bytes=0-"}) as playing, \
                    http.stream("GET", f"/agent/sessions/{session}/stream") as thinking:
                # 各读一口就停下:视频像 <video> 一样慢慢读,SSE 等着这一轮的下一帧。迭代器要留着 —— 丢掉它,
                # httpx 就把连接关了,服务那头随之收尾,「正在发」的那一段就没了。
                video_bytes = playing.iter_bytes(64 * 1024)
                frames = thinking.iter_lines()
                next(video_bytes)
                next(frames)
                # 不用等:会话在响应开始发之前就该还掉了 —— 读到第一口时还攥着的,就是一直攥着。
                assert engine.pool.checkedout() == 0, (
                    f"一个播放中的视频 + 一条智能体流攥着 {engine.pool.checkedout()} 条连接(池子一共 15 条)"
                )
                with agent_stream._streams_lock:
                    agent_stream._streams[session]["done"] = True
                    agent_stream._streams[session]["seq"] += 1
    finally:
        with agent_stream._streams_lock:
            agent_stream._streams.pop(session, None)
