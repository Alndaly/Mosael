"""用户给的地址只许去公网:HTTP 请求节点、智能体的 http_request / fetch_url、从链接导入。

现场(上一轮工作流全量实测):HTTP 请求节点能打 127.0.0.1、局域网和 169.254.169.254 —— 一个社区模板、一段
藏在网页里的提示词注入,就能借这台服务器摸进本机没有鉴权的服务、路由器、云服务器的元数据。

每条都看**过程**:被拒时那台服务器一个连接都没收到(真的起一个监听的 socket 数连接),放行时请求确实打到了
目标、带着原来的 Host;解析一次、连的就是那个 IP;重定向的每一跳重新判。
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from sqlalchemy import inspect, select, text

from app.core import outbound_guard
from app.core.db import SessionLocal, engine
from app.db.models import Job, Workflow
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.engine import execute_graph
from tests.util import fresh_client, second_client


@pytest.fixture(autouse=True)
def _direct(monkeypatch):
    """这些用例看的是**直连**那条路(解析一次、连那个 IP):开发机的 shell 里常挂着代理,先摘掉。
    走代理的那条路单独一条用例(见最后)。"""
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)


class _Server:
    """本机一个真的 HTTP 服务:**按连接数**记账(连上就算,不管发没发请求),也记下收到的请求。"""

    def __init__(self, *, redirect_to: str | None = None) -> None:
        self.connections = 0
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                outer.requests.append({
                    "method": self.command, "path": self.path, "host": self.headers.get("Host"),
                    "body": self.rfile.read(length).decode() if length else "",
                })
                if redirect_to:
                    self.send_response(302)
                    self.send_header("Location", redirect_to)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                payload = b"<html><title>ok</title><body>hello from the inside</body></html>"
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = _answer  # noqa: N815 — http.server 的约定

            def log_message(self, *args) -> None:
                pass

        class CountingServer(HTTPServer):
            def verify_request(self, request, client_address) -> bool:  # 每接受一个连接调一次
                outer.connections += 1
                return True

        self.httpd = CountingServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_port
        self.url = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=30)


@pytest.fixture
def server():
    one = _Server()
    yield one
    one.close()


def _workflow_id() -> str:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="出站", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return workflow.id


def _run_http_node(url: str, *, wf_id: str | None = None, method: str = "POST", body: str = "hi") -> dict:
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "call", "type": "http_request", "config": {"method": method, "url": url, "body": body}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "call"}],
    }
    context, _ = execute_graph(graph, wf_id=wf_id or _workflow_id())
    return context["call"]


def _allow(client, *entries: str) -> None:
    res = client.put("/api/admin/outbound-allowlist", json={"entries": list(entries)})
    assert res.status_code == 200, res.text


@pytest.mark.parametrize(
    ("address", "reason"),
    [
        ("127.0.0.1", "loopback"), ("127.8.9.10", "loopback"), ("::1", "loopback"),
        ("::ffff:127.0.0.1", "loopback"), ("2002:7f00:1::", "loopback"),
        ("10.1.2.3", "private"), ("172.16.0.1", "private"), ("172.31.255.254", "private"),
        ("192.168.1.1", "private"), ("fc00::1", "private"), ("fd12:3456::1", "private"),
        ("169.254.169.254", "metadata"), ("100.100.100.200", "metadata"), ("fd00:ec2::254", "metadata"),
        ("169.254.10.10", "linkLocal"), ("fe80::1", "linkLocal"),
        ("0.0.0.0", "unspecified"), ("::", "unspecified"),
        ("100.64.0.1", "special"), ("198.18.0.1", "special"), ("224.0.0.1", "special"), ("255.255.255.255", "special"),
        ("8.8.8.8", None), ("93.184.216.34", None), ("2606:4700::1111", None), ("172.32.0.1", None),
    ],
)
def test_按解析出来的地址判(address: str, reason: str | None) -> None:
    assert outbound_guard.blocked_reason(ipaddress.ip_address(address)) == reason


# ---- HTTP 请求节点:真的起一个服务,看它收没收到连接 ----


def test_默认拒绝本机回环_那台服务一个连接都没收到_报错说清地址原因和放行办法(server: _Server) -> None:
    with pytest.raises(WorkflowDomainError) as caught:
        _run_http_node(server.url + "/admin/delete")
    assert caught.value.key == "outboundErr_private"
    message = str(caught.value)
    assert "127.0.0.1" in message and "本机回环地址" in message
    assert f"「127.0.0.1:{server.port}」" in message, "说清该把哪一项加进允许名单"
    assert "管理 → 部署设置 → 内网访问" in message, "说清去哪儿加"
    assert server.connections == 0 and server.requests == [], "被拒的请求不能连出去"


def test_localhost_这种名字按解析结果拦(server: _Server) -> None:
    with pytest.raises(WorkflowDomainError) as caught:
        _run_http_node(f"http://localhost:{server.port}/")
    assert caught.value.key == "outboundErr_private"
    assert "localhost" in str(caught.value)
    assert server.connections == 0


def test_允许名单里的地址照常打到_请求原样到达(server: _Server) -> None:
    wf_id = _workflow_id()
    client = second_client("tester")  # 同一个(第一个注册的,部署管理员)账号
    _allow(client, f"127.0.0.1:{server.port}")
    out = _run_http_node(server.url + "/hook?x=1", wf_id=wf_id, body='{"a": 1}')
    assert out["status"] == 200 and "hello from the inside" in out["text"]
    assert server.connections == 1
    assert server.requests == [{"method": "POST", "path": "/hook?x=1", "host": f"127.0.0.1:{server.port}", "body": '{"a": 1}'}]


def test_放行的是别的端口_这个端口照样拦(server: _Server) -> None:
    wf_id = _workflow_id()
    _allow(second_client("tester"), f"127.0.0.1:{server.port + 1 if server.port < 65535 else 1}")
    with pytest.raises(WorkflowDomainError) as caught:
        _run_http_node(server.url, wf_id=wf_id)
    assert caught.value.key == "outboundErr_private"
    assert server.connections == 0


def test_名字解析一次_连的就是查过的那个IP_Host_头还是原来的名字(server: _Server, monkeypatch) -> None:
    """svc.test 在真实 DNS 里不存在:请求能打到,只可能是因为连的是守卫查过的那个 IP,而不是 httpx 再解析一遍。"""
    wf_id = _workflow_id()
    _allow(second_client("tester"), f"svc.test:{server.port}")
    lookups: list[str] = []

    def fake_lookup(host: str, port: int) -> list[str]:
        lookups.append(host)
        return ["127.0.0.1"]

    monkeypatch.setattr(outbound_guard, "lookup", fake_lookup)
    out = _run_http_node(f"http://svc.test:{server.port}/x", wf_id=wf_id, method="GET", body="")
    assert out["status"] == 200
    assert lookups == ["svc.test"], "只解析一次"
    assert server.requests == [{"method": "GET", "path": "/x", "host": f"svc.test:{server.port}", "body": ""}]


@pytest.mark.parametrize("answers", [["10.0.0.5"], ["93.184.216.34", "127.0.0.1"], ["169.254.169.254"]],
                         ids=["内网", "一半公网一半回环", "元数据"])
def test_名字解析到内网_一个连接都不发(answers: list[str], monkeypatch) -> None:
    clients: list[object] = []
    monkeypatch.setattr(outbound_guard, "lookup", lambda host, port: answers)
    monkeypatch.setattr(outbound_guard, "client", lambda **kwargs: clients.append(kwargs) or pytest.fail("不该连出去"))
    with pytest.raises(WorkflowDomainError) as caught:
        _run_http_node("https://evil.example/latest/meta-data/")
    assert caught.value.key == "outboundErr_private"
    assert caught.value.params["host"] == "evil.example"
    assert caught.value.params["address"] in answers and caught.value.params["address"] != "93.184.216.34"
    assert clients == []


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://100.100.100.200/latest/meta-data/",
    "http://[::1]:8800/api/workspaces",
    "http://[::ffff:127.0.0.1]:8800/",
    "http://0.0.0.0:8800/",
    "http://192.168.1.1/cgi-bin/luci",
    "http://[fe80::1]/",
], ids=["aws元数据", "阿里云元数据", "ipv6回环", "v4映射回环", "未指定地址", "路由器", "ipv6链路本地"])
def test_字面量的内网地址_一个连接都不发(url: str, monkeypatch) -> None:
    monkeypatch.setattr(outbound_guard, "client", lambda **kwargs: pytest.fail("不该连出去"))
    with pytest.raises(WorkflowDomainError) as caught:
        _run_http_node(url)
    assert caught.value.key == "outboundErr_private"


def test_公网地址照常发_发到查过的那个IP_TLS_按原来的名字校验(monkeypatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"ok": True})

    monkeypatch.setattr(outbound_guard, "lookup", lambda host, port: ["93.184.216.34"])
    monkeypatch.setattr(
        outbound_guard, "client",
        lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False),
    )
    out = _run_http_node("https://api.example.com/v1/hook", body='{"hi": 1}')
    assert out == {"status": 201, "text": '{"ok":true}', "json": {"ok": True}}
    (request,) = seen
    assert request.url.host == "93.184.216.34" and request.url.path == "/v1/hook"
    assert request.headers["host"] == "api.example.com"
    assert request.extensions["sni_hostname"] == "api.example.com"
    assert request.content == b'{"hi": 1}' and request.headers["content-type"] == "application/json"


# ---- fetch_url:重定向的每一跳重新判 ----


def test_fetch_url_公网页面跳到内网_那一跳被拦_内网服务一个连接都没收到() -> None:
    from app.domain.websearch import WebSearchError, fetch

    inside = _Server()
    front = _Server(redirect_to=f"http://127.0.0.1:{inside.port}/secret")
    try:
        fresh_client()
        outbound_guard.set_allowlist([f"127.0.0.1:{front.port}"])  # 只放行跳板那一个
        with pytest.raises(WebSearchError) as caught:
            fetch(front.url + "/start")
        assert caught.value.key == "outboundErr_private"
        assert f"127.0.0.1:{inside.port}" in str(caught.value)
        assert front.requests[0]["path"] == "/start"
        assert inside.connections == 0, "跳到内网的那一跳不能连出去"
    finally:
        inside.close()
        front.close()


def test_fetch_url_每一跳都放行时跟到底() -> None:
    from app.domain.websearch import fetch

    inside = _Server()
    front = _Server(redirect_to=f"http://127.0.0.1:{inside.port}/page")
    try:
        outbound_guard.set_allowlist([f"127.0.0.1:{front.port}", f"127.0.0.1:{inside.port}"])
        page = fetch(front.url + "/start")
        assert page["title"] == "ok" and "hello from the inside" in page["text"]
        assert page["url"] == f"http://127.0.0.1:{inside.port}/page", "交回的是原来的地址,不是连过去的 IP"
        assert [one["path"] for one in front.requests] == ["/start"]
        assert [one["path"] for one in inside.requests] == ["/page"]
    finally:
        inside.close()
        front.close()


def test_fetch_url_默认拒绝回环(server: _Server) -> None:
    from app.domain.websearch import WebSearchError, fetch

    with pytest.raises(WebSearchError) as caught:
        fetch(server.url)
    assert caught.value.key == "outboundErr_private"
    assert server.connections == 0


def test_fetch_url_不收别的协议() -> None:
    from app.domain.websearch import WebSearchError, fetch

    with pytest.raises(WebSearchError) as caught:
        fetch("file:///etc/passwd")
    assert caught.value.key == "outboundErr_badUrl"


# ---- 智能体的 http_request 卡、从链接导入:同一个守卫 ----


def test_智能体的_http_request_卡批准之后照样被拦(server: _Server) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    card = client.post("/api/confirmations", json={
        "workspace_id": ws["id"], "tool": "http_request", "requested_by": "pi",
        "payload": {"url": server.url + "/x", "method": "POST", "body": "{}"},
    }).json()
    approved = client.post(f"/api/confirmations/{card['id']}/approve").json()
    assert approved["status"] == "failed"
    assert "127.0.0.1" in approved["error"] and "本机回环地址" in approved["error"]
    assert server.connections == 0


def test_从链接导入_内网链接当场拒_不排任务() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    res = client.post("/api/assets/import-url", json={
        "workspace_id": ws, "items": [{"url": "http://169.254.169.254/latest/meta-data/", "title": ""}],
    })
    assert res.status_code == 422, res.text
    assert "169.254.169.254" in res.json()["detail"] and "元数据" in res.json()["detail"]
    with SessionLocal() as db:
        assert db.scalars(select(Job).where(Job.kind == "url_import")).all() == []


# ---- 允许名单:部署管理员改,改完立刻生效 ----


def test_允许名单只有部署管理员能看能改_写不对的那一项点名() -> None:
    admin = fresh_client()
    member = second_client("member")
    assert member.get("/api/admin/outbound-allowlist").status_code == 403
    assert member.put("/api/admin/outbound-allowlist", json={"entries": ["10.0.0.0/8"]}).status_code == 403

    bad = admin.put("/api/admin/outbound-allowlist", json={"entries": ["10.0.0.0/8", "nas local"]})
    assert bad.status_code == 422 and "nas local" in bad.json()["detail"]
    assert outbound_guard.current_allowlist() == (), "写不对就一项都不生效"

    ok = admin.put("/api/admin/outbound-allowlist",
                   json={"entries": [" 10.0.0.0/8 ", "nas.local", "127.0.0.1:11434", "[::1]:8188", "10.0.0.0/8", ""]})
    assert ok.status_code == 200
    assert ok.json() == {"entries": ["10.0.0.0/8", "nas.local", "127.0.0.1:11434", "[::1]:8188"]}
    assert admin.get("/api/admin/outbound-allowlist").json() == ok.json()
    assert [one.text for one in outbound_guard.current_allowlist()] == ok.json()["entries"], "提交之后对本进程生效"

    check = outbound_guard.check
    assert check("http://10.20.30.40/").address == "10.20.30.40"
    assert check("http://127.0.0.1:11434/api/tags").address == "127.0.0.1"
    assert check("http://[::1]:8188/prompt").address == "::1"
    for blocked in ("http://127.0.0.1:11435/", "http://[::1]:8189/", "http://192.168.1.1/"):
        with pytest.raises(outbound_guard.OutboundBlocked):
            check(blocked)


def test_启动时把库里的名单推进进程() -> None:
    from app.domain import outbound_allowlist

    admin = fresh_client()
    _allow(admin, "192.168.1.0/24")
    outbound_guard.set_allowlist(())
    with SessionLocal() as db:
        outbound_allowlist.apply_to_process(db)
    assert [one.text for one in outbound_guard.current_allowlist()] == ["192.168.1.0/24"]


def test_老库补上空的允许名单() -> None:
    from app.db.migrations import _migrate_outbound_allowlist
    from app.domain import deployment

    fresh_client()
    with SessionLocal() as db:
        deployment.open_registration(db)
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE deployment_config DROP COLUMN outbound_allowlist"))
    engine.dispose()
    assert "outbound_allowlist" not in {c["name"] for c in inspect(engine).get_columns("deployment_config")}
    _migrate_outbound_allowlist()
    with engine.begin() as conn:
        assert conn.execute(text("SELECT outbound_allowlist FROM deployment_config")).scalars().all() == ["[]"]
    _migrate_outbound_allowlist()  # 再跑一次什么都不做


def _no_dns(host: str, port: int) -> list[str]:
    raise socket.gaierror("nodename nor servname provided")


def test_解析不了的名字不当成被拦_是连不上(monkeypatch) -> None:
    monkeypatch.setattr(outbound_guard, "lookup", _no_dns)
    with pytest.raises(httpx.ConnectError):
        outbound_guard.check("https://nowhere.invalid/")


def test_走代理时_按本机解析结果判_内网照样拦_公网交给代理去连(monkeypatch) -> None:
    """走代理时连接由代理发起,我们连不了「那个 IP」:只能在发出前判一次。内网照样拦;公网的请求原样(带着名字)交给代理。"""
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.corp:3128")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    made: list[dict] = []
    seen: list[httpx.Request] = []

    def fake_client(**kwargs):
        made.append(kwargs)
        return httpx.Client(transport=httpx.MockTransport(lambda request: seen.append(request) or httpx.Response(200)))

    monkeypatch.setattr(outbound_guard, "client", fake_client)
    monkeypatch.setattr(outbound_guard, "lookup", lambda host, port: ["10.0.0.7"])
    with pytest.raises(outbound_guard.OutboundBlocked):
        outbound_guard.send("GET", "https://intranet.corp/admin", timeout=5)
    assert made == [] and seen == []

    monkeypatch.setattr(outbound_guard, "lookup", lambda host, port: ["93.184.216.34"])
    outbound_guard.send("GET", "https://api.example.com/v1", timeout=5)
    assert made == [{"timeout": 5, "proxy": "http://proxy.corp:3128"}]
    assert str(seen[0].url) == "https://api.example.com/v1", "交给代理的是原来的名字"

    #: 本机解析不了(只有代理那边解析得了的内网环境):交给代理 —— 它是部署者自己配的出口。
    monkeypatch.setattr(outbound_guard, "lookup", _no_dns)
    outbound_guard.send("GET", "https://only-the-proxy-knows.example/", timeout=5)
    assert str(seen[-1].url) == "https://only-the-proxy-knows.example/"
