"""HTTP 请求节点:说的和做的对上。

- 请求体按普通插值拼 JSON:一段带引号的 LLM 回答就让请求体成了坏的 JSON。
- 不带 Content-Type:多数 API 把 JSON 当表单。
- 404 / 500 算成功:下游拿着错误页当数据往下跑。
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.core import outbound_guard
from app.core.db import SessionLocal
from app.db.models import Workflow
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.engine import execute_graph
from tests.util import fresh_client


def _wf_id() -> str:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="节点", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return workflow.id


def _node(node_type: str, config: dict, params: dict | None = None) -> dict:
    """真跑一遍引擎:开始节点 → 这一个节点。"""
    graph = {
        "nodes": [{"id": "start", "type": "start", "config": {}}, {"id": "n", "type": node_type, "config": config}],
        "edges": [{"id": "e1", "source": "start", "target": "n"}],
    }
    context, _ = execute_graph(graph, wf_id=_wf_id(), params=params or {})
    return context["n"]


# ---- HTTP 请求 ----

class _Server:
    """本机起一个真的 HTTP 服务:记下收到的请求,按路径回状态码。"""

    def __init__(self) -> None:
        received: list[dict] = []
        self.received = received

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 — http.server 的约定
                length = int(self.headers.get("Content-Length") or 0)
                received.append({"body": self.rfile.read(length).decode(), "type": self.headers.get("Content-Type")})
                status = 404 if self.path == "/missing" else 200
                payload = b'{"ok": true}' if status == 200 else b"not found"
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args) -> None:
                pass

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        # shutdown() 停掉 serve_forever 的循环;server_close() 关掉监听的套接字(不关的话 fd 留到进程退出);再等服务线程走完。
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=30)


@pytest.fixture
def server():
    """本机回环默认不许去(core/outbound_guard):这台测试服务的端口放进允许名单 —— 和部署管理员放行一个本机服务同一条路。"""
    one = _Server()
    outbound_guard.set_allowlist([f"127.0.0.1:{one.httpd.server_port}"])
    yield one
    one.close()


def test_JSON_请求体里的引用按_JSON_转义_自动带上_Content_Type(server: _Server) -> None:
    reply = '他说:"好的"\n第二行 \\ 反斜杠'
    out = _node(
        "http_request",
        {"method": "POST", "url": server.url + "/ok",
         "body": '{"prompt": "{{start.reply}}", "n": {{start.n}}, "tags": {{start.tags}}, "none": {{start.nothing}}}'},
        params={"reply": reply, "n": 3, "tags": ["a", "b"]},
    )
    assert out["status"] == 200
    sent = server.received[0]
    assert json.loads(sent["body"]) == {"prompt": reply, "n": 3, "tags": ["a", "b"], "none": ""}
    assert sent["type"] == "application/json"


def test_纯文本请求体照普通插值_不强加_Content_Type(server: _Server) -> None:
    _node("http_request", {"method": "POST", "url": server.url + "/ok", "body": "你好 {{start.who}}"},
          params={"who": "小明"})
    assert server.received[0]["body"] == "你好 小明"
    assert server.received[0]["type"] != "application/json"


@pytest.mark.parametrize("body", ["{{start.text}}\n\n来自 Mosael", "[告警] {{start.text}}", "{{start.text}} {结尾}"])
def test_开头像_JSON_的纯文本请求体_照普通插值(server: _Server, body: str) -> None:
    """此前只看开头是不是 `{` / `[`:这几种纯文本也被当成 JSON,引用被填成带引号、换行转义过的 JSON 字面量。"""
    text = '他说:"好"\n第二行'
    _node("http_request", {"method": "POST", "url": server.url + "/ok", "body": body}, params={"text": text})
    assert server.received[0]["body"] == body.replace("{{start.text}}", text)


def test_非_2xx_算失败(server: _Server) -> None:
    with pytest.raises(WorkflowDomainError) as caught:
        _node("http_request", {"method": "POST", "url": server.url + "/missing", "body": "x"})
    assert caught.value.key == "wfErr_httpStatus"
    assert caught.value.details["status"] == 404


def test_关掉_fail_on_error_就照常交出状态码(server: _Server) -> None:
    out = _node("http_request", {"method": "POST", "url": server.url + "/missing", "body": "x", "fail_on_error": "no"})
    assert out["status"] == 404 and out["text"] == "not found"
