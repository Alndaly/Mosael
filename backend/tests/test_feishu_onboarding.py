"""扫码一键创建:建完这台机器人,建它的那个人就是它名下的第一条绑定。

① 官方《一键创建应用》的注册回包里带着**扫码那个人**的 `user_info`(我们在 `begin` 那一步用
`request_user_info=open_id` 点名要它;文档见 integrations/feishu/onboarding 的模块说明),
此前只从里面读 `tenant_brand`,`open_id` 直接丢了 —— 于是"创建完自动绑定了"只是设置页列了
**整个工作区**的绑定造成的错觉(键那一维是第一半的事,见 domain/feishu/bindings)。
发起人已经不在这个工作区里、或注册回包没给 open_id 时**不写**,只记一条日志。

② 同一段轮询里的两个真 bug:`slow_down` 带回的新间隔被完全忽略(每隔多久只在 begin 读一次)、
有效期只认 `expire_in`(而两家服务端发的是 `expires_in` = 3600)—— 后者让用户还在确认页上就被
报「扫码超时」,而那个二维码其实还有五十分钟。`domain_switched` 也从"单向、白等一轮"改成官方的
样子:两个方向都认、换完**立刻**在新域上再问一次、一次扫描只换一次。

`_poll_onboarding` 这一层直接调、时间换成替身:要断言的是"下一次隔多久",真睡的话这条用例
就得按秒等,而它测的正是等待本身。
"""

from __future__ import annotations

import time
from typing import Any

from app.core.db import SessionLocal
from app.db.models import FeishuBinding, FeishuBot
from app.domain.feishu import bindings
from app.integrations.feishu import onboarding
from tests.util import fresh_client, second_client


class _FakeTime:
    """`time` 的替身 —— **只换 onboarding 这一个模块里的那个引用**(见 `_poll_onboarding` 里那两处)。

    换全局的 `time.sleep` 会影响同时跑着的别的线程(库里那套 `now()`、连接泵),所以按模块换。
    """

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _created(open_id: str | None = "ou_scanner") -> dict[str, Any]:
    """poll 成功那一次的回包:新应用的凭据 + 扫码人的 user_info。"""
    user_info: dict[str, Any] = {"tenant_brand": "feishu"}
    if open_id is not None:
        user_info["open_id"] = open_id
    return {"client_id": "cli_new", "client_secret": "s3cret", "user_info": user_info}


def _registration(monkeypatch, *, begin: dict | None = None, poll: list[dict] | None = None) -> list[dict]:
    """出网那一层换成按脚本回答的替身。返回收到的每一条注册请求(能看见 begin 问了什么、poll 去了哪个域)。

    脚本用完之后的兜底是**终态**(`expired_token`),不是 `authorization_pending` —— 后者会让轮询
    一直转下去(那条 daemon 线程活过本用例,下一条用例 drop_all 时会写进新库)。
    """
    calls: list[dict] = []
    scripted = list(poll or [])
    begun = begin if begin is not None else {
        "device_code": "dc-1",
        "interval": 5,
        "expires_in": 3600,
        "verification_uri_complete": "https://accounts.feishu.cn/qr",
        "user_code": "AB12",
    }

    def fake(base_url: str, body: dict[str, Any]) -> dict[str, Any]:
        calls.append({**body, "_base_url": base_url})
        if body.get("action") == "init":
            return {"supported_auth_methods": ["client_secret"]}
        if body.get("action") == "begin":
            return begun
        return scripted.pop(0) if scripted else {"error": "expired_token"}

    monkeypatch.setattr(onboarding, "_post_registration", fake)
    #: 长连接是另一个进程(真起的话会拿着假凭据去连飞书),这里只要"它被叫过"。
    monkeypatch.setattr(onboarding.connections, "start_connection", lambda bot_id: None)
    return calls


def _settled(workspace_id: str, timeout: float = 15.0) -> dict[str, Any]:
    """等这一轮轮询收尾(状态由那条 daemon 线程写)。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = onboarding.onboarding_status(workspace_id)
        if state.get("phase") in ("done", "error"):
            return state
        time.sleep(0.01)
    raise AssertionError(f"onboarding 没有在 {timeout}s 内收尾:{onboarding.onboarding_status(workspace_id)}")


# ---------------- ① 建完就绑发起人 ----------------


def test_扫码建完机器人就把发起人绑在它名下(monkeypatch) -> None:
    """「创建完自动绑定」这件事真的发生了:那一条绑定的键是 (新机器人, 扫码人的 open_id),
    绑的人是**发起这次扫码的那个成员**。此前建完什么也不写 —— 面板上那几条是别的机器人的。"""
    client = fresh_client()
    ws = _workspace(client)
    me = client.get("/api/auth/me").json()
    calls = _registration(monkeypatch, poll=[_created(open_id="ou_scanner")])

    assert client.post(f"/api/feishu/onboarding/{ws}").status_code == 200
    assert _settled(ws)["phase"] == "done", "这一轮没有建成机器人"

    with SessionLocal() as db:
        bot = db.query(FeishuBot).filter_by(workspace_id=ws).one()
        row = db.get(FeishuBinding, {"workspace_id": ws, "bot_id": bot.id, "open_id": "ou_scanner"})
        assert row is not None, "建完机器人没有给发起人写绑定"
        assert (row.user_id, row.stale_reason) == (me["id"], ""), (row.user_id, row.stale_reason)
        #: 它是一条**有效**绑定(不是"写是写了、认人时不算数"的那种)。
        assert bindings.resolve_sender(db, ws, bot.id, "ou_scanner").id == me["id"]

    #: `begin` 那一步就得点名要 open_id,否则回包里根本不会有它。
    begin_calls = [one for one in calls if one.get("action") == "begin"]
    assert begin_calls and begin_calls[0].get("request_user_info") == "open_id", begin_calls


def test_发起人已经不是成员时不写绑定(monkeypatch) -> None:
    """绑的人必须是这个工作区的成员:那条外键指着 `users`,而"绑一个非成员"没有任何意义
    (机器人以他/她的权限行事 —— 一个不在工作区里的人没有权限可给)。机器人照样建出来。"""
    client = fresh_client()
    ws = _workspace(client)
    stranger = second_client("stranger").get("/api/auth/me").json()
    _registration(monkeypatch, poll=[_created(open_id="ou_scanner")])

    onboarding.begin_onboarding(ws, stranger["id"])
    assert _settled(ws)["phase"] == "done"

    with SessionLocal() as db:
        assert db.query(FeishuBot).filter_by(workspace_id=ws).one() is not None
        assert db.query(FeishuBinding).filter_by(workspace_id=ws).all() == [], "非成员不该被绑上"


def test_没有发起人时不写绑定也不报错(monkeypatch) -> None:
    """`begin` 那一步没带发起人时(直接调用、或将来某条入口忘了传):机器人照样建出来,
    只是不写绑定 —— **不报错**,用户扫的那张码不该因为这一格空着就作废。"""
    client = fresh_client()
    ws = _workspace(client)
    _registration(monkeypatch, poll=[_created(open_id="ou_scanner")])

    onboarding.begin_onboarding(ws, "")
    assert _settled(ws)["phase"] == "done"

    with SessionLocal() as db:
        assert db.query(FeishuBot).filter_by(workspace_id=ws).one() is not None
        assert db.query(FeishuBinding).filter_by(workspace_id=ws).all() == []


def test_注册回包没给open_id时不写绑定也不报错(monkeypatch) -> None:
    """官方没承诺 `user_info.open_id` 一定在(而且它的**应用归属**官方也没写,见 onboarding 的模块
    说明)。缺了就不绑 —— 记一条日志,**不报错**:机器人已经建好了,不该因为少一个 id 就作废。"""
    client = fresh_client()
    ws = _workspace(client)
    _registration(monkeypatch, poll=[_created(open_id=None)])

    assert client.post(f"/api/feishu/onboarding/{ws}").status_code == 200
    state = _settled(ws)
    assert (state["phase"], state["app_id"]) == ("done", "cli_new"), state

    with SessionLocal() as db:
        assert db.query(FeishuBot).filter_by(workspace_id=ws).one() is not None
        assert db.query(FeishuBinding).filter_by(workspace_id=ws).all() == []


# ---------------- ② slow_down 的新间隔、expires_in、换域 ----------------


def test_slow_down之后按新的间隔轮询(monkeypatch) -> None:
    """服务端说"你问得太快了"并给了新间隔 —— **下一次就按它来**。

    此前 interval 只在 begin 读一次,`slow_down` 带回的那个值被完全忽略:越问越快的请求被越来越多地
    判成 `slow_down`,而这个错误码本身就是在提醒你慢下来。
    """
    clock = _FakeTime()
    monkeypatch.setattr(onboarding, "time", clock)
    answers = [{"error": "slow_down", "interval": 9}, {"error": "access_denied"}]
    monkeypatch.setattr(onboarding, "_post_registration", lambda base_url, body: answers.pop(0))
    onboarding._onboard_state["ws-slowdown"] = {"phase": "waiting_scan", "_gen": 1, "_user_id": "u-1"}

    onboarding._poll_onboarding("ws-slowdown", "dc-1", "feishu", 5.0, 3600.0, 1, "u-1")

    assert clock.slept == [9.0], "slow_down 带回的新间隔没有用上(此前照旧睡 begin 读到的那个 5 秒)"


def test_slow_down没带间隔时按官方的加五秒(monkeypatch) -> None:
    """官方 Python SDK 是 `interval += 5`。回包里没给新值时就照它来。"""
    clock = _FakeTime()
    monkeypatch.setattr(onboarding, "time", clock)
    answers = [{"error": "slow_down"}, {"error": "access_denied"}]
    monkeypatch.setattr(onboarding, "_post_registration", lambda base_url, body: answers.pop(0))
    onboarding._onboard_state["ws-slowdown-step"] = {"phase": "waiting_scan", "_gen": 1, "_user_id": "u-1"}

    onboarding._poll_onboarding("ws-slowdown-step", "dc-1", "feishu", 5.0, 3600.0, 1, "u-1")

    assert clock.slept == [10.0], "没给新间隔时该按官方的 +5 秒"


def test_有效期与间隔的两种拼写都认() -> None:
    """`expires_in` / `expire_in` 是两台服务端各自的拼写(官方 Python SDK 读前者、Go SDK 写后者),
    两个都认;都没有才用官方那个兜底 600。间隔同理(`interval` 只在 begin 出现,认不出就用 5)。
    """
    assert onboarding._expire_seconds({"expires_in": 3600}) == 3600
    assert onboarding._expire_seconds({"expire_in": 1200}) == 1200
    assert onboarding._expire_seconds({}) == 600
    #: 0 / 认不出都不是"立刻过期":退到兜底,别把一次扫码当场判死。
    assert onboarding._expire_seconds({"expires_in": 0}) == 600
    assert onboarding._seconds("nope", 5) == 5
    assert onboarding._seconds(-1, 5) == 5


def test_有效期认expires_in而不是只认expire_in(monkeypatch) -> None:
    """**服务端发的是 `expires_in`(3600)**,`expire_in` 只是 Go SDK 的拼写变体。

    此前只认后者,真机上永远落回 600 秒:用户还在确认页上就被报「扫码超时」,而那个二维码其实
    还有五十分钟。这条用例让扫码人在第 640 秒(> 600、< 3600)才确认 —— 只认 `expire_in` 的话
    轮询在 600 秒那一步就退出了,机器人根本没建出来。

    机器人在**成功那一次**才写库,所以这条用例要一个真库。
    """
    client = fresh_client()
    ws = _workspace(client)
    me = client.get("/api/auth/me").json()
    clock = _FakeTime()
    monkeypatch.setattr(onboarding, "time", clock)
    #: begin 明说 `expires_in: 3600`;每 4 秒问一次,第 161 次(第 640 秒)才成功 ——
    #: 600 秒那条(只认 `expire_in` 时的兜底)正好落在它前面。
    _registration(
        monkeypatch,
        begin={"device_code": "dc-1", "interval": 4, "expires_in": 3600, "user_code": "AB12"},
        poll=[{"error": "authorization_pending"}] * 160 + [_created(open_id="ou_scanner")],
    )

    onboarding.begin_onboarding(ws, me["id"], "feishu")
    state = _settled(ws)

    assert state["phase"] == "done", f"600 秒就被判超时了(而服务端说这次扫码有效期 3600 秒):{state}"
    with SessionLocal() as db:
        assert db.query(FeishuBot).filter_by(workspace_id=ws).one() is not None


def test_换域双向处理_换完立刻在新域上再问一次(monkeypatch) -> None:
    """扫码的人原来在另一个域(feishu ⇄ lark)时,**立刻**换到他的域上再问一次 —— 官方的
    `domain_switched` 就是这个意思:不在旧域上白等一轮,一次扫描也只换一次(换回来再换回去
    就是在两个域之间弹)。

    此前只在 poll 里单向判一次(从 feishu 换到 lark),从 lark 开始扫 feishu 的人换不回去。
    """
    clock = _FakeTime()
    monkeypatch.setattr(onboarding, "time", clock)
    calls: list[tuple[str, str]] = []
    answers: list[dict] = []

    def fake(base_url: str, body: dict[str, Any]) -> dict[str, Any]:
        calls.append((base_url, body.get("action", "")))
        return answers.pop(0)

    monkeypatch.setattr(onboarding, "_post_registration", fake)

    for ws, start, brand, expected in (
        ("ws-fwd", "feishu", "lark", "https://accounts.larksuite.com"),
        ("ws-rev", "lark", "feishu", "https://accounts.feishu.cn"),
    ):
        calls.clear()
        clock.slept.clear()
        clock.now = 0.0
        answers[:] = [{"user_info": {"tenant_brand": brand}}, {"error": "access_denied"}]
        onboarding._onboard_state[ws] = {"phase": "waiting_scan", "_gen": 1, "_user_id": "u-1"}

        onboarding._poll_onboarding(ws, "dc-1", start, 5.0, 3600.0, 1, "u-1")

        assert [url for url, _ in calls] == [onboarding.ONBOARD_ACCOUNTS_URLS[start], expected], calls
        assert clock.slept == [], "换域之后要立刻在新域上再问一次,不是在旧域上白等一轮"
