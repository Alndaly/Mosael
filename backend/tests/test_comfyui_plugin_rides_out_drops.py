"""隧道抖一下不让跑着的任务失败:读的请求等一等再试,提交先问到没到再决定发不发(ADR 0092)。"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui" / "tools"
MODULES = tuple(path.stem for path in TOOLS.glob("*.py"))


@pytest.fixture(scope="module")
def tools():
    """插件的模块名很普通(graph / run),用完就从 sys.modules 摘掉,不串到别的测试。"""
    saved = {name: sys.modules.pop(name) for name in MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import comfy_http
        import run

        yield comfy_http, run
    finally:
        sys.path.remove(str(TOOLS))
        for name in MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


class Flaky(ThreadingHTTPServer):
    """前 `drops` 个请求收下就掐断;`drop_after_queueing`:POST /prompt 记下任务再掐断(回答丢了)。"""

    def __init__(self, drops: int = 0, drop_after_queueing: bool = False) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.drops, self.drop_after_queueing = drops, drop_after_queueing
        self.seen: list[str] = []
        self.queued: list[str] = []


class Handler(BaseHTTPRequestHandler):
    server: Flaky

    def log_message(self, *_args) -> None:
        pass

    def _answer(self, value: object) -> None:
        raw = json.dumps(value).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _hang_up(self) -> None:
        self.close_connection = True
        self.connection.close()

    def do_GET(self) -> None:
        self.server.seen.append(self.path)
        if self.server.drops > 0:
            self.server.drops -= 1
            return self._hang_up()
        if self.path.startswith("/queue"):
            return self._answer({"queue_running": [], "queue_pending": [[0, one] for one in self.server.queued]})
        self._answer({})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.seen.append(self.path)
        if self.server.drop_after_queueing:
            self.server.drop_after_queueing = False
            self.server.queued.append(body["prompt_id"])
            return self._hang_up()
        if self.server.drops > 0:
            self.server.drops -= 1
            return self._hang_up()
        self.server.queued.append(body["prompt_id"])
        self._answer({"prompt_id": body["prompt_id"], "node_errors": {}})


@pytest.fixture
def serve(tools, monkeypatch):
    monkeypatch.setattr(tools[0], "DROP_WAITS_SECONDS", (0.0, 0.0, 0.0))
    started: list[Flaky] = []

    def start(**kwargs) -> tuple[Flaky, object]:
        server = Flaky(**kwargs)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        started.append(server)
        return server, tools[0].Comfy(f"http://127.0.0.1:{server.server_address[1]}")

    yield start
    for server in started:
        server.shutdown()
        server.server_close()


def test_跑任务时_读的请求被掐断_等一等再试(serve) -> None:
    _server, comfy = serve(drops=3)
    comfy.ride_out_drops()
    assert comfy.get("/history/x") == {}


def test_没在跑任务时_连不上当场说(serve, tools) -> None:
    server, comfy = serve(drops=3)
    with pytest.raises(tools[0].ComfyUnreachable):
        comfy.get("/history/x")
    assert len(server.seen) <= 2, "探活要立刻知道连不上"


def test_一直不通_最后还是报连不上(serve, tools) -> None:
    _server, comfy = serve(drops=100)
    comfy.ride_out_drops()
    with pytest.raises(tools[0].ComfyUnreachable):
        comfy.get("/history/x")


def test_提交没到_重发一遍(serve, tools) -> None:
    server, comfy = serve(drops=1)
    comfy.ride_out_drops()
    prompt_id = tools[1].submit(comfy, {}, "c", "zh")
    assert server.queued == [prompt_id]


def test_提交到了只是回答丢了_不发第二遍(serve, tools) -> None:
    server, comfy = serve(drop_after_queueing=True)
    comfy.ride_out_drops()
    prompt_id = tools[1].submit(comfy, {}, "c", "zh")
    assert server.queued == [prompt_id]
    assert server.seen.count("/prompt") == 1
