"""飞书绑定按**机器人(飞书应用)**记 —— `open_id` 按应用隔离。

官方《用户身份概述》的原话是「不要在跨应用的数据通信中使用 open_id」,而键此前只有
`(workspace_id, open_id)`。这里逐条钉住四个后果的修法:

1. 换 / 重建应用之后,旧行**不再**被当成有效绑定;
2. 同一个人在两个应用里的两行**各归各的机器人**,`requester_binding` 取的 (机器人, open_id)
   来自同一行(不是"A 的 id 配 B 的 token");
3. 两个路由真的按机器人:列表只列本机、删除只删本机(双向);
4. 没绑定时那句回复**说清是哪台机器人**(而不是让用户猜该去生成哪一台的码)。
"""

from __future__ import annotations

import json

from app.core.db import SessionLocal
from app.db.models import FeishuBinding, FeishuBot, WorkspaceMember
from app.domain.feishu import bindings, routing
from app.integrations.feishu import client as feishu_client
from app.integrations.feishu import inbound
from tests.util import fresh_client, second_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _bot(client, workspace_id: str, *, name: str = "助手", app_id: str = "cli_a") -> dict:
    return client.post(
        "/api/feishu/bots",
        json={"workspace_id": workspace_id, "name": name, "app_id": app_id, "app_secret": "s3cret"},
    ).json()


def _bind(db, workspace_id: str, bot_id: str, open_id: str, member_id: str) -> None:
    """成员发一张码、再从**这台机器人**把码发过去 —— 和生产里那条路一样。

    open_id 按应用隔离,所以落成的那一行记的是 `bot_id` 眼里的这串 id。测试就是入口:
    兑码只改对象,提交在这里做(别的会话 —— 比如那两个路由 —— 才看得见它)。
    """
    code, _ = bindings.issue_bind_code(db, workspace_id, member_id)
    assert bindings.redeem_bind_code(db, workspace_id, bot_id, open_id, code) is not None
    db.commit()


def test_unbound_sender_denied_and_bind_code_flow() -> None:
    client = fresh_client()
    ws = _workspace(client)
    me = client.get("/api/auth/me").json()
    bot = _bot(client, ws)
    with SessionLocal() as db:
        # An unbound Feishu sender resolves to nobody → handle_incoming refuses (no owner action).
        assert bindings.resolve_sender(db, ws, bot["id"], "ou_stranger") is None

        # Member issues a one-time code; a Feishu sender redeems it → bound to that member **for this bot**.
        _bind(db, ws, bot["id"], "ou_alice", me["id"])
        assert bindings.resolve_sender(db, ws, bot["id"], "ou_alice").id == me["id"]
        assert bindings.redeem_bind_code(db, ws, bot["id"], "ou_bob", "ZZZZZZ") is None
        # A different, still-unbound sender is still denied.
        assert bindings.resolve_sender(db, ws, bot["id"], "ou_bob") is None


def test_绑定码只能兑换一次() -> None:
    client = fresh_client()
    ws = _workspace(client)
    me = client.get("/api/auth/me").json()
    bot = _bot(client, ws)
    with SessionLocal() as db:
        code, _ = bindings.issue_bind_code(db, ws, me["id"])
        assert bindings.redeem_bind_code(db, ws, bot["id"], "ou_first", code) is not None
        assert bindings.redeem_bind_code(db, ws, bot["id"], "ou_second", code) is None
        db.commit()
        assert bindings.resolve_sender(db, ws, bot["id"], "ou_first").id == me["id"]
        assert bindings.resolve_sender(db, ws, bot["id"], "ou_second") is None


def test_移出工作区后绑定列表不再显示他() -> None:
    client = fresh_client()
    ws = _workspace(client)
    me = client.get("/api/auth/me").json()
    bot = _bot(client, ws)
    with SessionLocal() as db:
        _bind(db, ws, bot["id"], "ou_gone", me["id"])
        member = db.get(WorkspaceMember, {"workspace_id": ws, "user_id": me["id"]})
        db.delete(member)
        db.commit()
        assert bindings.list_bindings(db, ws, bot["id"]) == []


def test_换过应用之后旧行的open_id在新机器人里认不出来() -> None:
    """应用重建 = 一段新的 open_id 命名空间:老应用里那一行在新机器人眼里**什么都不是**。

    此前键上没有机器人这一维,旧行照样被认成"已绑定" —— 而新事件里的 `sender_open_id`
    其实来自另一个应用,永远匹配不上,于是机器人回「你还没有绑定」、设置页却显示已绑定。
    """
    client = fresh_client()
    ws = _workspace(client)
    me = client.get("/api/auth/me").json()
    old = _bot(client, ws, name="老应用", app_id="cli_old")
    new = _bot(client, ws, name="新应用", app_id="cli_new")
    with SessionLocal() as db:
        _bind(db, ws, old["id"], "ou_under_old_app", me["id"])
        # 老应用里那一行照旧算数(切回去的人还能用)。
        assert bindings.resolve_sender(db, ws, old["id"], "ou_under_old_app").id == me["id"]
        # 新应用里**不算数** —— 这条 open_id 不是它眼里的 id。
        assert bindings.resolve_sender(db, ws, new["id"], "ou_under_old_app") is None
        # 「发起人绑过飞书就私聊他」同样按机器人取:新机器人名下他一条也没有。
        assert routing.requester_binding(db, ws, me["id"], new["id"]) is None

    #: 面板也是各看各的:新机器人的绑定列表里没有老应用那一行(它此前按工作区列)。
    assert client.get(f"/api/feishu/bots/{new['id']}/bindings").json() == []


def test_同一个人在两个应用里的两行各归各的机器人() -> None:
    """同一个人两台机器人 = 两行、两串 id;`requester_binding` 交回的 (机器人, open_id) 必须同一行。"""
    client = fresh_client()
    ws = _workspace(client)
    me = client.get("/api/auth/me").json()
    first = _bot(client, ws, name="先接的", app_id="cli_1")
    second = _bot(client, ws, name="后接的", app_id="cli_2")
    with SessionLocal() as db:
        _bind(db, ws, first["id"], "ou_in_first_app", me["id"])
        _bind(db, ws, second["id"], "ou_in_second_app", me["id"])

        assert bindings.resolve_sender(db, ws, first["id"], "ou_in_first_app").id == me["id"]
        assert bindings.resolve_sender(db, ws, second["id"], "ou_in_second_app").id == me["id"]
        # 交叉着认不出来:同一串 id 只属于生成它的那个应用。
        assert bindings.resolve_sender(db, ws, first["id"], "ou_in_second_app") is None
        assert bindings.resolve_sender(db, ws, second["id"], "ou_in_first_app") is None

        #: 点名哪台就拿哪台的那一行 —— 两个值来自同一行(此前没有 app 维度、也没有 ORDER BY)。
        assert routing.requester_binding(db, ws, me["id"], first["id"])[1] == "ou_in_first_app"
        assert routing.requester_binding(db, ws, me["id"], second["id"])[1] == "ou_in_second_app"
        #: 没点名:挑**他绑过的那台**(创建时间最早的那个),而不是"最早启用的那台"再配上别人的 id。
        picked_bot, picked_open_id = routing.requester_binding(db, ws, me["id"])
        assert (picked_bot.id, picked_open_id) == (first["id"], "ou_in_first_app")

        #: `channel=user` 那一档的"已绑定"也是就这台机器人而言。
        assert routing.resolve(db, workspace_id=ws, channel="user", bot_id=first["id"], to="ou_in_first_app").ok
        assert routing.resolve(
            db, workspace_id=ws, channel="user", bot_id=first["id"], to="ou_in_second_app",
        ).reason == "not-bound"


def test_列表只列本机_删除只删本机() -> None:
    """两个路由都按机器人:一台的面板既看不到、也删不掉另一台的绑定。"""
    client = fresh_client()
    ws = _workspace(client)
    me = client.get("/api/auth/me").json()
    first = _bot(client, ws, name="一号", app_id="cli_1")
    second = _bot(client, ws, name="二号", app_id="cli_2")
    with SessionLocal() as db:
        _bind(db, ws, first["id"], "ou_one", me["id"])
        _bind(db, ws, second["id"], "ou_two", me["id"])

    def listed(bot_id: str) -> list[str]:
        rows = client.get(f"/api/feishu/bots/{bot_id}/bindings").json()
        return [one["open_id"] for one in rows]

    assert listed(first["id"]) == ["ou_one"]
    assert listed(second["id"]) == ["ou_two"]

    #: 拿一号的 URL 去删二号的那条:删不掉(此前按工作区删,删掉的正是别人的)。
    assert client.delete(f"/api/feishu/bots/{first['id']}/bindings/ou_two").status_code == 204
    assert listed(first["id"]) == ["ou_one"]
    assert listed(second["id"]) == ["ou_two"]

    #: 删自己那条:只掉自己那条。
    assert client.delete(f"/api/feishu/bots/{first['id']}/bindings/ou_one").status_code == 204
    assert listed(first["id"]) == []
    assert listed(second["id"]) == ["ou_two"]


def test_删机器人时它名下的绑定一起没了() -> None:
    """删机器人 = 它名下的绑定一起走。

    `(bot, open_id) -> user` 这条绑定随机器人一起没有意义:open_id 按应用隔离,那台应用没了之后
    它眼里的这串 id 不再有任何应用解释得了 —— 留着只会在表里积一行**谁都匹配不上**的死行。
    「谁曾绑过」不是这张**活跃**表的事:真要留痕,那是另一张审计 / 事件表的事。
    """
    client = fresh_client()
    ws = _workspace(client)
    me = client.get("/api/auth/me").json()
    doomed = _bot(client, ws, name="要删的", app_id="cli_doomed")
    kept = _bot(client, ws, name="留着的", app_id="cli_kept")
    with SessionLocal() as db:
        _bind(db, ws, doomed["id"], "ou_doomed", me["id"])
        _bind(db, ws, kept["id"], "ou_kept", me["id"])

    assert client.delete(f"/api/feishu/bots/{doomed['id']}").status_code == 204

    with SessionLocal() as db:
        assert db.get(FeishuBot, doomed["id"]) is None
        assert db.query(FeishuBinding).filter_by(workspace_id=ws, open_id="ou_doomed").all() == [], (
            "机器人都没了,它名下那行绑定还留着 —— 它永远匹配不上任何东西"
        )
        #: 别的机器人的绑定一动不动(删一台不该动到另一台)。
        assert db.get(FeishuBinding, {"workspace_id": ws, "bot_id": kept["id"], "open_id": "ou_kept"}) is not None
        assert bindings.resolve_sender(db, ws, doomed["id"], "ou_doomed") is None

    #: 留着的机器人面板上只有它自己那一条。
    listed = client.get(f"/api/feishu/bots/{kept['id']}/bindings").json()
    assert [(one["open_id"], one["bot_id"]) for one in listed] == [("ou_kept", kept["id"])]


def test_bind_code_route_requires_membership() -> None:
    client = fresh_client()
    ws = _workspace(client)
    with SessionLocal() as db:
        bot = FeishuBot(workspace_id=ws, app_id="a", app_secret="s")
        db.add(bot)
        db.commit()
        bot_id = bot.id

    ok = client.post(f"/api/feishu/bots/{bot_id}/bind-code")
    assert ok.status_code == 200 and len(ok.json()["code"]) >= 4

    stranger = second_client("stranger")
    assert stranger.post(f"/api/feishu/bots/{bot_id}/bind-code").status_code == 404  # non-member → hidden


def test_没绑定时的回复说清是哪台机器人(monkeypatch) -> None:
    """用户只能猜"该去生成哪一台的码" —— 这句话里必须有那台机器人的名字。"""
    client = fresh_client()
    ws = _workspace(client)
    bot = _bot(client, ws, name="客服助手", app_id="cli_support")
    sent: list[str] = []
    monkeypatch.setattr(feishu_client, "send_text", lambda bot, chat_id, text: sent.append(text))

    inbound.handle_incoming(bot["id"], "oc_1", "m-1", "ou_stranger", content_json=json.dumps({"text": "你好"}))
    assert sent and "客服助手" in sent[0], sent

    #: 他发上来的那张码不作数时,要说清**为什么**(另一台机器人 / 过期),而不是照旧说"没绑定"。
    inbound.handle_incoming(bot["id"], "oc_1", "m-2", "ou_stranger", content_json=json.dumps({"text": "ABC123"}))
    assert len(sent) == 2 and "客服助手" in sent[1] and "无效" in sent[1], sent
