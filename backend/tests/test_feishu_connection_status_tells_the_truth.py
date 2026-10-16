"""飞书长连接的「在线」必须是**真的连上了**,不是定时器写出来的。

这条链上此前有三处在说假话(或干脆不说):

1. worker 进程起来 8 秒就无条件 `emit status online` —— 凭据错、SDK 卡在内部重连时,设置页照样变绿;
2. autostart 起不来只 `logger.exception`:状态永远停在 connecting,`status_detail` 一个字没有;
3. 子进程异常退出时,泵把那句「长连接进程退出(code N)」盖在 worker 自己报的原因上,真正的原因丢了。

而真机上看到的是:`status='connecting'`、`updated_at` 停在某个时刻,而后端根本没在跑 —— 上一辈子
留下的状态没人归零。

这里钉的是「谁有资格说什么」:只有真的握手成功了才叫在线;起不来必须留下原因;后端起来时把上一次
残留的状态归零,由真实过程重新写。
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import threading
import time
import types
from collections.abc import Callable

from app.core.db import SessionLocal
from app.db.models import FeishuBot
from app.integrations.feishu import connections, worker
from tests.util import fresh_client

#: 协议行前缀(`@@mosael `),替身 worker 也按它说话。
PROTOCOL = worker.PROTOCOL


# ---------------- 装置 ----------------


def _bot(
    ws: str,
    *,
    app_id: str = "cli_status",
    enabled: bool = True,
    status: str = "offline",
    detail: str = "",
) -> str:
    with SessionLocal() as db:
        bot = FeishuBot(
            workspace_id=ws, name="助手", app_id=app_id, app_secret="s",
            enabled=enabled, status=status, status_detail=detail,
        )
        db.add(bot)
        db.commit()
        return bot.id


def _row(bot_id: str) -> tuple[str, str]:
    with SessionLocal() as db:
        bot = db.get(FeishuBot, bot_id)
        assert bot is not None
        return bot.status, bot.status_detail


def _pump_alive(bot_id: str) -> bool:
    name = f"feishu-{bot_id[:8]}"
    return any(one.name == name and one.is_alive() for one in threading.enumerate())


def _online(emitted: list[dict]) -> dict | None:
    for event in emitted:
        if event.get("event") == "status" and event.get("status") == "online":
            return event
    return None


def _statuses(emitted: list[dict]) -> list[str]:
    return [str(event.get("status")) for event in emitted if event.get("event") == "status"]


def _wait_until(predicate: Callable[[], bool], timeout: float = 10.0) -> bool:
    """等到条件成立。**等事件、等条件,不等时间**(见 docs/CONVENTIONS.md「测试里怎么等」)。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# ---------------- 替身 SDK:不出网,连接成功与否由脚本决定 ----------------


class _FakeBuilder:
    """`EventDispatcherHandler.builder("", "")` 那串注册:注册了什么不重要,链式调用要能走通。"""

    def register_p2_im_message_receive_v1(self, _fn):
        return self

    def register_p2_im_message_message_read_v1(self, _fn):
        return self

    def register_p2_card_action_trigger(self, _fn):
        return self

    def build(self):
        return self


class _FakeClient:
    """`lark.ws.Client` 的替身。

    真 SDK 里"连上了"的唯一状态是 `_conn`(见 lark_oapi/ws/client.py 的 `_connect`):端点那次
    HTTP POST 与 websocket 握手都成功之后才被赋值,掉线时清回 None。`script` 演的就是这件事。
    """

    def __init__(self, script: Callable[[_FakeClient], None]) -> None:
        self.script = script
        self._conn = None
        #: 真 SDK 里这两个是可赋值的观察钩子,默认什么都不做。
        self.on_reconnecting: Callable[[], None] = lambda: None
        self.on_reconnected: Callable[[], None] = lambda: None

    def start(self) -> None:  # 真 SDK:阻塞到连接结束(或自己卡在重连里)
        self.script(self)


def _install_fake_sdk(monkeypatch, client: _FakeClient) -> None:
    module = types.ModuleType("lark_oapi")
    module.LogLevel = types.SimpleNamespace(INFO=1)  # type: ignore[attr-defined]
    module.EventDispatcherHandler = types.SimpleNamespace(builder=lambda *_a, **_k: _FakeBuilder())  # type: ignore[attr-defined]
    module.ws = types.SimpleNamespace(Client=lambda *_a, **_k: client)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "lark_oapi", module)


def _run_worker(
    monkeypatch,
    script: Callable[[_FakeClient], None],
) -> tuple[_FakeClient, list[dict]]:
    """起一个 worker(替身 SDK),把它报上来的协议事件收下来。

    `script` 是替身 `start()` 期间发生的事。它**等事件,不等时间**(见 docs/CONVENTIONS.md
    「测试里怎么等」):要"还在跑"就卡在 Event 上,由用例放行。
    """
    client = _FakeClient(script)
    emitted: list[dict] = []
    _install_fake_sdk(monkeypatch, client)
    #: 父进程那一头的看门狗(管道一关就 os._exit)另有其测:这里测的是连接状态,不要它。
    monkeypatch.setattr(worker, "follow_parent", lambda *_a, **_k: None)
    monkeypatch.setattr(worker, "emit", emitted.append)
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO(json.dumps({"app_id": "cli_s", "app_secret": "s"}) + "\n"))
    #: 旧实现那个「起来 8 秒就报在线」的定时器。它还在的时候,下面第一条用例必须是红的;
    #: 现在没有这个常量了,setattr 是空操作(raising=False 就是为这一条)。
    monkeypatch.setattr(worker, "CONNECTING_GRACE_SECONDS", 0.05, raising=False)
    #: 新实现看 `_conn` 的间隔。旧实现没有这个名字,空操作。
    monkeypatch.setattr(worker, "CONNECT_CHECK_SECONDS", 0.01, raising=False)
    threading.Thread(target=worker.main, args=("bot-status",), daemon=True).start()
    return client, emitted


# ---------------- ① 在线只能由「真的连上了」驱动 ----------------


def test_连接没建立起来_就不许报在线(monkeypatch) -> None:
    """连不上(凭据不对 / 网络不通 / SDK 卡在内部重连)时,设置页不许变绿。

    旧实现:起来 8 秒(这里缩到 50 毫秒)无条件发 `status online`,于是"连上了"是定时器写的。
    """
    release = threading.Event()

    def never_connects(_client: _FakeClient) -> None:
        release.wait(5)  # 真 SDK 卡在内部重连里就是这种形状:start() 一直不返回

    try:
        _client, emitted = _run_worker(monkeypatch, never_connects)
        assert _wait_until(lambda: _online(emitted) is not None, timeout=0.6) is False, (
            f"连接根本没建立起来,却报了「在线」:{emitted}"
        )
    finally:
        release.set()


def test_在线只在握手成功之后出现(monkeypatch) -> None:
    """真连上的那一刻之后才有「在线」;早于它的绿都是假的。"""
    connect_now, release = threading.Event(), threading.Event()

    def connects_when_told(client: _FakeClient) -> None:
        connect_now.wait(5)
        client._conn = object()  # 真 SDK:握手成功 → 赋 _conn
        release.wait(5)

    try:
        _client, emitted = _run_worker(monkeypatch, connects_when_told)
        assert _wait_until(lambda: _online(emitted) is not None, timeout=0.6) is False, (
            f"还没握手就报了「在线」—— 定时器写的绿:{emitted}"
        )
        connect_now.set()
        assert _wait_until(lambda: _online(emitted) is not None, timeout=5), f"握手成功了却没报在线:{emitted}"
        assert _statuses(emitted) == ["online"], _statuses(emitted)
    finally:
        connect_now.set()
        release.set()


def test_掉线重连时_状态说清正在重连(monkeypatch) -> None:
    """连上之后掉线:不能留着上一次的「在线」不说 —— SDK 正在重连这件事要让设置页看得见。"""
    drop, release = threading.Event(), threading.Event()

    def drops_and_retries(client: _FakeClient) -> None:
        client._conn = object()  # 一连上
        drop.wait(5)
        client._conn = None
        client.on_reconnecting()  # 真 SDK 决定重连时先喊这一声
        release.wait(5)

    try:
        _client, emitted = _run_worker(monkeypatch, drops_and_retries)
        assert _wait_until(lambda: _online(emitted) is not None, timeout=5), f"真的连上了却没报在线:{emitted}"
        drop.set()
        assert _wait_until(lambda: _statuses(emitted) == ["online", "connecting"], timeout=5), (
            f"掉线没说出来:{emitted}"
        )
        retrying = next(event for event in emitted if event.get("status") == "connecting")
        assert str(retrying.get("detail") or "").strip(), "说「正在重连」却一个字不说为什么"
    finally:
        drop.set()
        release.set()


# ---------------- ② autostart 起不来:必须留下原因 ----------------


def test_autostart_起不来_落_error_并带上异常原文(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    bot_id = _bot(ws["id"])

    def boom(_bot_id: str) -> None:
        raise RuntimeError("app_secret 被飞书拒了")

    monkeypatch.setattr(connections, "start_connection", boom)

    connections.autostart_enabled_bots()

    status, detail = _row(bot_id)
    assert status == "error", f"起不来却停在 {status!r} —— 设置页会一直转圈"
    assert "app_secret 被飞书拒了" in detail, f"异常原文没进 status_detail:{detail!r}"


# ---------------- ③ 后端起来时:上一次残留的状态归零 ----------------


def test_后端起来时_上一次残留的连接状态归零() -> None:
    """上一辈子留下的 connecting / online 是假话(那时并没有连接在跑),启动时一律归零,
    再由真实过程重新写:启起来写 connecting、真连上才写 online、起不来写 error。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    #: 停用的机器人也在内:没有连接在跑这件事与它启不启用无关。
    stale_connecting = _bot(ws["id"], app_id="cli_a", enabled=False, status="connecting", detail="上一次没跑完")
    stale_online = _bot(ws["id"], app_id="cli_b", enabled=False, status="online", detail="")

    connections.autostart_enabled_bots()

    assert _row(stale_connecting) == ("offline", ""), "残留的 connecting 会永远转圈"
    assert _row(stale_online) == ("offline", ""), "后端没跑却说自己在线"


# ---------------- ④ 子进程异常退出:带上它最后说的原因 ----------------


#: 读完凭据就报一句错、然后以 1 退出 —— 真 worker 抛出前的形状。
CHILD_SAYS_WHY_THEN_EXITS = (
    "import json, sys\n"
    "sys.stdin.readline()\n"
    "sys.stdout.write(" + repr(PROTOCOL) + " + json.dumps("
    "{'event': 'status', 'status': 'error', 'detail': '凭据被拒: app_secret 不对'}, ensure_ascii=False) + '\\n')\n"
    "sys.stdout.flush()\n"
    "sys.exit(1)\n"
)


def test_子进程异常退出_带上它最后说的原因(monkeypatch) -> None:
    monkeypatch.setattr(
        connections,
        "popen_text",
        lambda _argv, **kwargs: subprocess.Popen([sys.executable, "-c", CHILD_SAYS_WHY_THEN_EXITS], text=True, **kwargs),
    )
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    bot_id = _bot(ws["id"], app_id="cli_exit")

    connections.start_connection(bot_id)

    assert _wait_until(lambda: not _pump_alive(bot_id)), "泵没读完就没了"
    status, detail = _row(bot_id)
    assert status == "error", status
    assert "凭据被拒" in detail, f"worker 自己报的原因被那句「进程退出」盖掉了:{detail!r}"
    assert "code 1" in detail, f"退出码也要留着:{detail!r}"
