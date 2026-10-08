"""关机**不因为一条还开着的连接而无限等**,lifespan 的收尾照样跑。

uvicorn 默认等所有连接自己结束才走 lifespan 的收尾。智能体这一轮的流、一个慢慢读的视频、一次长插件调用 —— 任何一条
还开着,关机就停在「Waiting for connections to close」:实测开着一条 SSE,20 秒后服务线程还活着、`local_services.stop_all()`
一次都没被调到。壳没了的那条路(core/lifeline)到点 `os._exit`,收尾整段跳过:Mosael 起的 ComfyUI 留在后台占着显存。

两道:打包版的配置(run_backend.config)真的在 GRACEFUL_SHUTDOWN_SECONDS 秒后放手、收尾跑了;开发态的两条启动命令
(Electron 拉起的、`pnpm dev:backend`)带着同一个数。
"""

from __future__ import annotations

import json
import pathlib
import re
import threading
import time

import httpx

from app.core.lifeline import FORCE_EXIT_AFTER, GRACEFUL_SHUTDOWN_SECONDS
from app.domain import local_services
from app.domain.agent import stream as agent_stream
from tests.util import first_free_port_of_this_worker, fresh_client

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_an_open_stream_does_not_keep_the_cleanup_from_running(monkeypatch) -> None:
    import uvicorn

    import run_backend

    client = fresh_client()
    token = client.headers["Authorization"]
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    session = client.post("/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": ws}).json()["id"]
    agent_stream._stream_reset(session)  # 这一轮还在跑:流一直开着

    cleaned = threading.Event()
    real_stop_all = local_services.stop_all
    monkeypatch.setattr(local_services, "stop_all", lambda: (cleaned.set(), real_stop_all()))

    port = first_free_port_of_this_worker()
    config = run_backend.config(port)
    config.log_level = "warning"
    server = uvicorn.Server(config)
    serving = threading.Thread(target=server.run, daemon=True)
    serving.start()
    try:
        deadline = time.monotonic() + 30
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert server.started
        with httpx.Client(base_url=f"http://127.0.0.1:{port}/api", timeout=None, trust_env=False,
                          headers={"Authorization": token}) as http, \
                http.stream("GET", f"/agent/sessions/{session}/stream") as thinking:
            frames = thinking.iter_lines()
            next(frames)
            asked = time.monotonic()
            server.should_exit = True  # 和收到 SIGTERM 走同一条路
            serving.join(timeout=GRACEFUL_SHUTDOWN_SECONDS + 20)
            took = time.monotonic() - asked
        assert not serving.is_alive(), "开着一条流,关机一直等着它"
        assert cleaned.is_set(), "lifespan 的收尾(停本机服务)没有跑"
        assert took < FORCE_EXIT_AFTER, "收尾要在壳那条路强退之前做完"
    finally:
        server.force_exit = True
        serving.join(timeout=10)
        with agent_stream._streams_lock:
            agent_stream._streams.pop(session, None)


def test_every_way_of_starting_the_backend_bounds_the_wait() -> None:
    expected = str(GRACEFUL_SHUTDOWN_SECONDS)
    scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
    dev = re.search(r"--timeout-graceful-shutdown (\d+)", scripts["dev:backend"])
    assert dev and dev.group(1) == expected, "pnpm dev:backend 没带 --timeout-graceful-shutdown(或数字对不上)"
    electron = (ROOT / "electron" / "main.cjs").read_text(encoding="utf-8")
    shell = re.search(r'"--timeout-graceful-shutdown",\s*"(\d+)"', electron)
    assert shell and shell.group(1) == expected, "Electron 开发态拉起后端的命令没带 --timeout-graceful-shutdown(或数字对不上)"
