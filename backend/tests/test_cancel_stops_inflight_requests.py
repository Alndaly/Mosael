"""取消任务时,正在进行的大模型(及其它出站)请求真的断开 —— 不是改一行状态、等它自己答完。

现场(上一轮工作流全量实测):取消工作流之后,本地 Ollama 一直生成到后端重启才停;付费 API 会一直计费到它答完。
原因是取消只落库,而节点里那一次 HTTP 请求阻塞在读上,谁也叫不醒它。

这里的上游是**假的、慢的**:真的监听一个端口,收到请求后要么憋着不回(Ollama 非流式就是生成完才发响应头),要么
每 50 毫秒吐一块(流式)。看的是上游那一侧:取消之后多久看到连接断开、之后还有没有字节流进来。
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time

import httpx
import pytest

from app.core import abort, outbound_guard
from app.core.db import SessionLocal
from app.core.http_retry import RetryingClient
from tests.util import add_provider, fresh_client, until, wait_settled, wait_status


@pytest.fixture(autouse=True)
def _desktop(monkeypatch):
    """这里的服务起在本机回环上,是桌面版的情形:连接里填的(部署配的)地址照连(core/outbound_guard)。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "local_desktop", True)

#: 上游「生成」要多久才回。旧代码下取消之后连接一直挂到这时;新代码下取消后一秒内就断。
GENERATE_SECONDS = 8.0
#: 取消之后最多等多久看到断开:线画在「不修的话要等多久」(生成完才断)的一半。此前是 1.5 秒,几套测试同时跑时不够。
CLOSE_WITHIN_SECONDS = GENERATE_SECONDS / 2


@pytest.fixture(autouse=True)
def _direct(monkeypatch):
    """开发机的 shell 里常挂着代理;这些用例连的是本机的假上游,一律直连。"""
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(key, raising=False)
        monkeypatch.delenv(key.lower(), raising=False)


class _SlowUpstream:
    """一个慢的上游。`mode="hold"`:收完请求就憋着,GENERATE_SECONDS 之后才回一个完整的对话补全;
    `mode="stream"`:收完请求就发响应头,然后每 50 毫秒一块(chunked),直到对方断开。

    记下:收到了几个连接、收到的请求体、什么时候发现对方断开、断开之后有没有再写出去过。
    """

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.connections = 0
        self.bodies: list[dict] = []
        self.request_seen = threading.Event()
        self.closed = threading.Event()
        self.closed_at: float | None = None
        self.chunks_sent = 0
        self.answered = False
        self._listener = socket.create_server(("127.0.0.1", 0))
        self.port = self._listener.getsockname()[1]
        self._server = threading.Thread(target=self._serve, daemon=True)
        self._server.start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._listener.accept()
            except OSError:
                return
            self.connections += 1
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _read_request(self, conn: socket.socket) -> None:
        data = b""
        while b"\r\n\r\n" not in data:
            data += conn.recv(65536)
        head, _, body = data.partition(b"\r\n\r\n")
        length = 0
        for line in head.split(b"\r\n")[1:]:
            name, _, value = line.partition(b":")
            if name.strip().lower() == b"content-length":
                length = int(value.strip())
        while len(body) < length:
            body += conn.recv(65536)
        try:
            self.bodies.append(json.loads(body or b"{}"))
        except ValueError:
            self.bodies.append({"raw": body.decode(errors="replace")})
        self.request_seen.set()

    def _mark_closed(self) -> None:
        if not self.closed.is_set():
            self.closed_at = time.monotonic()
            self.closed.set()

    def _handle(self, conn: socket.socket) -> None:
        try:
            self._read_request(conn)
            if self.mode == "hold":
                self._hold(conn)
            else:
                self._stream(conn)
        finally:
            conn.close()

    def _hold(self, conn: socket.socket) -> None:
        conn.settimeout(0.02)
        deadline = time.monotonic() + GENERATE_SECONDS
        while time.monotonic() < deadline:
            try:
                if conn.recv(1) == b"":
                    self._mark_closed()
                    return
            except TimeoutError:
                continue
            except OSError:
                self._mark_closed()
                return
        payload = json.dumps({"choices": [{"message": {"content": "生成完了"}}], "usage": {}}).encode()
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                     + str(len(payload)).encode() + b"\r\n\r\n" + payload)
        self.answered = True

    def _stream(self, conn: socket.socket) -> None:
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n")
        deadline = time.monotonic() + GENERATE_SECONDS
        while time.monotonic() < deadline:
            piece = b'data: {"delta":"\xe5\xad\x97"}\n\n'
            try:
                conn.sendall(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
            except OSError:
                self._mark_closed()
                return
            self.chunks_sent += 1
            time.sleep(0.05)
            #: 对方 shutdown 之后,本端的读会立刻看到 EOF(写可能还会成功一两次,内核缓冲着)——
            #: 真的上游就是这样发现客户端走了、停止生成的。
            conn.setblocking(False)
            try:
                if conn.recv(1) == b"":
                    self._mark_closed()
                    return
            except BlockingIOError:
                pass
            except OSError:
                self._mark_closed()
                return
            conn.setblocking(True)

    def close(self) -> None:
        # 只 close 叫不醒阻塞在 accept() 里的线程 —— macOS 上会醒,Linux(CI)上不会,线程一直活着,
        # 测试结束后的「线程没收完」检查就红。先 shutdown 再 close,两边都会让 accept() 抛错退出。
        try:
            self._listener.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._listener.close()
        self._server.join(timeout=5)


@pytest.fixture
def held():
    one = _SlowUpstream("hold")
    yield one
    one.close()


@pytest.fixture
def streaming():
    one = _SlowUpstream("stream")
    yield one
    one.close()


def _job_events(client, job_id: str) -> list[dict]:
    return client.get(f"/api/jobs/{job_id}/events").json()


def _run_and_cancel(client, graph: dict, upstream: _SlowUpstream, *, params: dict | None = None) -> tuple[str, float]:
    ws = client.get("/api/workspaces").json()[0]["id"]
    saved = client.post("/api/workflows", json={"workspace_id": ws, "name": "取消", "graph": graph}).json()
    job = client.post(f"/api/workflows/{saved['id']}/run", json={"params": params or {}}).json()
    assert upstream.request_seen.wait(15), "工作流应该已经把请求发到上游了"
    cancelled_at = time.monotonic()
    res = client.post(f"/api/jobs/{job['id']}/cancel")
    assert res.status_code == 200, res.text
    return job["id"], cancelled_at


def test_取消工作流_在途的大模型请求当场断开_不重发_节点不算成功(held: _SlowUpstream) -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    with SessionLocal() as db:
        profile = add_provider(db, name="本地模型", vendor="openai-compatible",
                               base_url=f"http://127.0.0.1:{held.port}/v1", api_key="sk-local", model="qwen-local")
        db.commit()
        profile_id = profile.id
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {"topic": "猫"}}},
            {"id": "write", "type": "llm", "config": {"profile_id": profile_id, "model": "qwen-local",
                                                     "prompt": "写一首关于{{start.topic}}的长诗"}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "write"}],
    }
    job_id, cancelled_at = _run_and_cancel(client, graph, held)

    #: 过程:节点的输入就是引用解析之后的那一句,发到了上游。
    assert held.bodies[0]["model"] == "qwen-local"
    assert held.bodies[0]["messages"][-1] == {"role": "user", "content": "写一首关于猫的长诗"}

    assert held.closed.wait(CLOSE_WITHIN_SECONDS), "取消之后上游的连接应该当场断开,而不是挂到生成完"
    assert held.closed_at - cancelled_at < CLOSE_WITHIN_SECONDS
    assert not held.answered

    #: 等到任务线程结束再数连接:重试只能从它发出去,它结束了就不会再有。此前是睡 0.3 秒再数 ——
    #: 机器一忙,重试还没来得及发,断言照样成立。
    assert wait_settled(client, job_id) == "cancelled", "取消不被节点失败盖掉"
    assert held.connections == 1, "取消之后不重试、不再发"
    finished = [one for one in _job_events(client, job_id) if one["type"] == "workflow.node.finished"]
    assert [one["payload"].get("node_id") for one in finished if one["payload"].get("node_id") == "write"] == []


def test_取消时_HTTP_请求节点等着的连接当场断开(held: _SlowUpstream) -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    outbound_guard.set_allowlist([f"127.0.0.1:{held.port}"])
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "call", "type": "http_request",
             "config": {"method": "POST", "url": f"http://127.0.0.1:{held.port}/slow", "body": '{"q": 1}'}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "call"}],
    }
    job_id, cancelled_at = _run_and_cancel(client, graph, held)
    assert held.bodies == [{"q": 1}]
    assert held.closed.wait(CLOSE_WITHIN_SECONDS)
    assert held.closed_at - cancelled_at < CLOSE_WITHIN_SECONDS
    assert wait_status(client, job_id) == "cancelled"


def test_取消时正在读的流式响应当场停_之后一个字节都不再进来(streaming: _SlowUpstream) -> None:
    stop = abort.AbortScope()
    received: list[tuple[float, int]] = []
    failure: list[BaseException] = []

    def read() -> None:
        with abort.scope(stop):
            try:
                with RetryingClient(timeout=30) as client:
                    with client.stream("POST", f"http://127.0.0.1:{streaming.port}/v1/chat/completions",
                                       json={"stream": True}) as response:
                        for chunk in response.iter_bytes():
                            received.append((time.monotonic(), len(chunk)))
            except httpx.HTTPError as exc:
                failure.append(exc)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    assert until(lambda: len(received) >= 5), "流式响应应该已经在往里吐了"

    aborted_at = time.monotonic()
    stop.kill()
    reader.join(CLOSE_WITHIN_SECONDS)
    assert not reader.is_alive(), "读的那个线程应该当场醒来"
    assert streaming.closed.wait(CLOSE_WITHIN_SECONDS), "上游应该看到连接断开"
    assert streaming.closed_at - aborted_at < CLOSE_WITHIN_SECONDS
    #: 取消那一刻手里正在交的那一块可以交完(至多一块);之后再进来的就是没停住 —— 上游每 50 毫秒一块,
    #: 不停的话这里是几十块。此前要求「取消 10 毫秒之后一块都没有」:读线程拿到块之后要抢到 GIL 才记时间,满载下 10 毫秒不够。
    late = [size for at, size in received if at > aborted_at]
    assert len(late) <= 1, f"取消之后又流进来 {len(late)} 块"
    assert failure and isinstance(failure[0], httpx.HTTPError), "被掐断的流不能装成「读完了」"
    assert sum(size for _, size in received) > 0 and streaming.chunks_sent < GENERATE_SECONDS / 0.05 / 2, \
        "上游在断开时就停了,没有生成到底"


def test_已经取消的活不再发新的请求_一个连接都不建(held: _SlowUpstream, monkeypatch) -> None:
    #: 在发起连接的那一处数(httpcore 建 TCP 连接走的是 socket.create_connection),不在上游数:
    #: 上游那边要等接受连接的线程转一圈才数得到,此前只好睡 0.2 秒再看 —— 机器一忙,连上了也还没数到。
    dialed: list[object] = []
    real_create_connection = socket.create_connection

    def create_connection(address, *args, **kwargs):
        dialed.append(address)
        return real_create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", create_connection)
    stop = abort.AbortScope()
    stop.kill()
    with abort.scope(stop), RetryingClient(timeout=5) as client:
        with pytest.raises(abort.RequestAborted):
            client.post(f"http://127.0.0.1:{held.port}/v1/chat/completions", json={})
    assert dialed == []


def test_不在任务里的请求不受影响(monkeypatch) -> None:
    """请求线程、脚本里建的客户端没有开关:照旧等到上游回答。"""
    monkeypatch.setattr(sys.modules[__name__], "GENERATE_SECONDS", 0.3)
    one = _SlowUpstream("hold")
    try:
        with RetryingClient(timeout=5) as client:
            response = client.post(f"http://127.0.0.1:{one.port}/v1/chat/completions", json={})
        assert response.json()["choices"][0]["message"]["content"] == "生成完了"
    finally:
        one.close()


def test_订阅授权那条路_取消时掐掉一次性的_sidecar(monkeypatch) -> None:
    """订阅授权的补全每次起一个 sidecar 进程去问供应商;取消要掐掉它,它对供应商的连接随进程一起断。"""
    from app.ai.sidecar import pi_client

    started: list[subprocess.Popen] = []

    def fake_spawn() -> subprocess.Popen:
        #: 读完那一帧就「等供应商」—— 一直不回。
        process = subprocess.Popen(
            [sys.executable, "-c", "import sys, time; sys.stdin.readline(); time.sleep(60)"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        started.append(process)
        return process

    monkeypatch.setattr(pi_client, "spawn_pi", fake_spawn)
    stop = abort.AbortScope()
    outcome: list[BaseException] = []

    def complete() -> None:
        with abort.scope(stop):
            try:
                pi_client.gateway_complete(system_prompt="", prompt="hi", images=None, provider={}, model="m",
                                           api_base="http://127.0.0.1:1", token="t", timeout=60)
            except BaseException as exc:  # noqa: BLE001 — 要的就是它抛了什么
                outcome.append(exc)

    worker = threading.Thread(target=complete, daemon=True)
    worker.start()
    #: 等它真的在「等供应商」了(取消的回调已经登记上)再取消。此前是起了进程之后再睡 0.2 秒。
    assert until(lambda: started and stop._hooks), "补全一直没开始等供应商"
    stop.kill()
    #: sidecar 要等 60 秒才自己退:线画在它的一半。此前是 1.5 秒。
    assert started[0].wait(timeout=30) is not None, "取消之后那个 sidecar 进程应该没了"
    worker.join(30)
    assert not worker.is_alive()
    assert isinstance(outcome[0], pi_client.SidecarError) and outcome[0].key == "aiErr_gatewayCancelled"


class _Child:
    def __init__(self) -> None:
        self.killed = False

    def kill(self) -> None:
        self.killed = True


def test_取消落在子进程刚起的那一下_后登记的子进程照样当场掐掉() -> None:
    """取消在**提交之前**掐子进程;执行体恰好在那一刻起了一个新的(插件刚要起进程),它登记时去库里查还是 running ——
    此前它就没人掐了,插件照跑到底。现在掐过一次的任务记在内存里,后登记的当场掐。"""
    from app.db.models import Job, Workspace
    from app.domain import jobs

    fresh_client()
    with SessionLocal() as db:
        workspace = Workspace(name="W")
        db.add(workspace)
        db.flush()
        job = jobs.create_job(db, workspace_id=workspace.id, kind="workflow", payload={}, created_by=None)
        job.status = "running"
        db.commit()
        job_id = job.id
    body = _Child()
    jobs.register_job_child(job_id, body)  # 执行体在跑(它一开跑就登记的取消开关)
    try:
        with SessionLocal() as db:
            jobs.cancel_job(db, db.get(Job, job_id), by=None)  # 掐了,还没提交
            late = _Child()
            jobs.register_job_child(job_id, late)  # 执行体恰好此刻起了一个新子进程
            assert body.killed and late.killed, "取消还没提交时登记上来的子进程也要掐掉"
            db.commit()
        after = _Child()
        jobs.register_job_child(job_id, after)
        assert after.killed
    finally:
        jobs.unregister_job_child(job_id)
        jobs.forget_job_kill(job_id)
    assert job_id not in jobs._KILLED, "执行体结束就忘掉,不留在进程里"
