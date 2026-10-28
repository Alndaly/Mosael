"""飞书能力节点:发消息 / 取回附件 / 回表情 / 列群。

这四件事是**工作流自己的动作**(不是「等人确认」那种门),所以它们不另写一套飞书调用:
"发到哪"(目标解析 + 挑机器人)与"怎么发"(文字 / 卡片)都只有一份实现 ——
领域侧 `domain/feishu/routing`(谁收)与 `domain/feishu/gateway`(那道缝),
出网那一份在 `integrations/feishu`。「等人确认」的飞书那一面走的是同一条路。

这里钉的是:

1. 「发飞书消息」文字与卡片两条各一,而且**发完就走**(不等回复);
2. 「取回飞书附件」把字节落成素材(素材编号、名字、大小一起交出去);
3. 「回个表情」的调用参数对(方法、地址、请求体);
4. 「列出机器人所在的群」解析飞书的分页返回,并跟完 page_token;
5. **没绑机器人**:「发飞书消息」失败并说清是哪一件事 —— 不是悄悄什么都不做;
6. 「等人确认」那条路走的是同一份解析(它此前自己解了一遍,那正是"节点上看不见"的来源)。
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Asset, FeishuBinding, FeishuBot, Workspace
from app.domain.workflows.errors import WorkflowDomainError
from app.integrations.feishu import client
from tests.util import fresh_client, user_id

OPEN_ID = "ou_bound_person"


# ---------------- 公共装置 ----------------


@dataclass(frozen=True)
class _Scope:
    """执行器只认这三样(见 executors/registry.RunScope),这里给一份最小的。"""

    workspace_id: str
    id: str
    name: str


def _workspace() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _bot(ws: str, name: str = "助手", app_id: str = "cli_x") -> str:
    with SessionLocal() as db:
        bot = FeishuBot(workspace_id=ws, name=name, app_id=app_id, app_secret="s", enabled=True)
        db.add(bot)
        db.commit()
        return bot.id


def _bind(ws: str, open_id: str = OPEN_ID, bot_id: str = "") -> str:
    """把这个人绑到**这台机器人**上。

    open_id 按飞书应用隔离,所以绑定必须指名机器人;没指名就用这个工作区的第一台(没有就建一台)。
    """
    with SessionLocal() as db:
        bot = (
            db.get(FeishuBot, bot_id) if bot_id
            else db.scalars(select(FeishuBot).where(FeishuBot.workspace_id == ws)).first()
        )
        if bot is None:
            bot = FeishuBot(workspace_id=ws, name="助手", app_id="cli_bind", app_secret="s")
            db.add(bot)
            db.flush()
        db.add(FeishuBinding(workspace_id=ws, bot_id=bot.id, open_id=open_id, user_id=user_id()))
        db.commit()
    return open_id


def _run(node_type: str, config: dict[str, Any], ws: str) -> dict[str, Any]:
    """**直接调执行器**(不走引擎):这几个节点都是"做一件事、交几格产物",不需要真线程。"""
    from app.domain.workflows.executors.registry import get_executor

    handler = get_executor(node_type)
    assert handler is not None, f"{node_type} 没有登记执行器"
    with SessionLocal() as db:
        return handler(db, _Scope(workspace_id=ws, id="wf-1", name="这张图"), config)


def _sent(monkeypatch) -> dict[str, list]:
    """出网那一处打桩:发出去的文字与卡片都记下来,一条都不真的发。"""
    seen: dict[str, list] = {"texts": [], "cards": []}

    def send_text(bot, receive_id, text, *, receive_id_type="chat_id"):
        seen["texts"].append({"bot": bot.id, "to": receive_id, "type": receive_id_type, "text": text})
        return f"om_text_{len(seen['texts'])}"

    def send_card(bot, receive_id, card, *, receive_id_type="chat_id"):
        seen["cards"].append({"bot": bot.id, "to": receive_id, "type": receive_id_type, "card": card})
        return f"om_card_{len(seen['cards'])}"

    monkeypatch.setattr(client, "send_text", send_text)
    monkeypatch.setattr(client, "send_card", send_card)
    return seen


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(buffer, "PNG")
    return buffer.getvalue()


# ---------------- ① 「发飞书消息」:文字与卡片 ----------------


def test_发飞书消息_纯文字_发完就走(monkeypatch) -> None:
    ws = _workspace()
    bot_id = _bot(ws)
    seen = _sent(monkeypatch)

    out = _run(
        "feishu_message",
        {"channel": "chat", "to": "oc_room", "format": "text", "text": "「前半程」跑完了"},
        ws,
    )

    assert out["sent"] is True
    assert out["message_id"] == "om_text_1", "发出去的那条消息 id 要交出来,下游可能要用"
    assert seen["texts"] == [
        {"bot": bot_id, "to": "oc_room", "type": "chat_id", "text": "「前半程」跑完了"}
    ]
    assert seen["cards"] == []
    #: 「发完就走」:没有等人确认那套(执行器不建单、不抛 AwaitingApproval)。
    from app.db.models import WorkflowRunApproval

    with SessionLocal() as db:
        assert db.query(WorkflowRunApproval).count() == 0


def test_发飞书消息_卡片_标题正文链接按钮(monkeypatch) -> None:
    ws = _workspace()
    bot_id = _bot(ws)
    seen = _sent(monkeypatch)

    out = _run(
        "feishu_message",
        {
            "channel": "user",
            "to": _bind(ws),
            "format": "card",
            "title": "夜间转码",
            "body": "**跑完**了,共 12 条",
            "link": "https://example.test/runs/12",
            "button_label": "打开运行",
        },
        ws,
    )

    assert out["sent"] is True and out["message_id"] == "om_card_1"
    assert seen["texts"] == [], "卡片形态不该再发一条文字"
    card = seen["cards"][0]
    assert (card["to"], card["type"], card["bot"]) == (OPEN_ID, "open_id", bot_id)
    assert card["card"]["header"]["title"]["content"] == "夜间转码"
    rendered = json.dumps(card["card"], ensure_ascii=False)
    assert "**跑完**了,共 12 条" in rendered
    assert "https://example.test/runs/12" in rendered and "打开运行" in rendered


def test_发飞书消息_手填收件_id_与类型(monkeypatch) -> None:
    """`raw` 是给"机器人看得见、但不在下拉里"的那种 id 留的口子(另一个租户、另一个拉群的机器人)。

    手填的 id 是飞书那边的编号:**类型按前缀判**(`ou_` 是人、`oc_` 是群),那一格写的名字要和它对上。
    """
    ws = _workspace()
    bot_id = _bot(ws)
    seen = _sent(monkeypatch)

    _run(
        "feishu_message",
        {"channel": "raw", "raw_id": "ou_handwritten", "raw_type": "open_id", "format": "text", "text": "在吗"},
        ws,
    )

    assert seen["texts"] == [{"bot": bot_id, "to": "ou_handwritten", "type": "open_id", "text": "在吗"}]


def test_手填的收件_id_前缀说了算_类型那一格空着也认(monkeypatch) -> None:
    """类型那一格空着时,按 id 前缀判 —— 前缀是飞书真正校验的那一半,手改 / 迁移来的图常常只有 id。"""
    ws = _workspace()
    bot_id = _bot(ws)
    seen = _sent(monkeypatch)

    _run(
        "feishu_message",
        {"channel": "raw", "raw_id": "oc_handwritten", "raw_type": "", "format": "text", "text": "在吗"},
        ws,
    )

    assert seen["texts"] == [{"bot": bot_id, "to": "oc_handwritten", "type": "chat_id", "text": "在吗"}]


def test_手填的收件_id_认不出前缀_当场说清而不是猜成群(monkeypatch) -> None:
    """前缀认不出时此前**猜成 chat_id** 发出去(那一格空着就是"回 chat_id"),等飞书回一句英文报错。

    这里两种写法都要失败:那一格空着、以及那一格写着 open_id —— id 的形状认不出就不发。
    """
    ws = _workspace()
    _bot(ws)
    seen = _sent(monkeypatch)

    for declared in ("", "open_id"):
        with pytest.raises(WorkflowDomainError) as raised:
            _run(
                "feishu_message",
                {"channel": "raw", "raw_id": "om_someone", "raw_type": declared, "format": "text", "text": "在吗"},
                ws,
            )
        assert raised.value.key == "wfErr_feishuRawId", raised.value
        assert "oc_" in str(raised.value) and "ou_" in str(raised.value), f"要写清该长什么样:{raised.value}"
    assert seen["texts"] == [] and seen["cards"] == [], "认不出的收件 id 一个字都不该发出去"


def test_手填的收件_id_与类型对不上_当场说清(monkeypatch) -> None:
    """两格互相矛盾(前缀说是人、那一格写的是群 id)是手改留下的,不许按任何一边猜着发。"""
    ws = _workspace()
    _bot(ws)
    seen = _sent(monkeypatch)

    with pytest.raises(WorkflowDomainError) as raised:
        _run(
            "feishu_message",
            {"channel": "raw", "raw_id": "ou_person", "raw_type": "chat_id", "format": "text", "text": "在吗"},
            ws,
        )

    assert raised.value.key == "wfErr_feishuRawType", raised.value
    assert seen["texts"] == [] and seen["cards"] == []


def test_发飞书消息_没绑机器人_失败并说清是哪件事(monkeypatch) -> None:
    """**不是悄悄不发。** 这个节点整个存在的意义就是把一句话送出去 —— 送不出去却"成功",
    等于让整条自动化假装做完了。工作区一个机器人都没接时,它当场失败,失败原因说清要接机器人。
    """
    ws = _workspace()
    seen = _sent(monkeypatch)

    with pytest.raises(WorkflowDomainError) as raised:
        _run("feishu_message", {"channel": "chat", "to": "oc_room", "format": "text", "text": "hi"}, ws)

    assert raised.value.key == "wfErr_feishuNoBot", raised.value
    assert seen["texts"] == [] and seen["cards"] == []


def test_发飞书消息_内容为空_当场说清() -> None:
    ws = _workspace()
    _bot(ws)
    with pytest.raises(WorkflowDomainError) as raised:
        _run("feishu_message", {"channel": "raw", "raw_id": "oc_x", "format": "text", "text": "  "}, ws)
    assert raised.value.key == "wfErr_feishuEmptyText", raised.value


# ---------------- ② 「取回飞书附件」 ----------------


def test_取回飞书附件_落成素材(monkeypatch) -> None:
    ws = _workspace()
    bot_id = _bot(ws)
    data = _png()
    calls: list[tuple] = []

    def named(bot, message_id, file_key, kind):
        calls.append((bot.id, message_id, file_key, kind))
        return client.DownloadedResource(data=data, filename="收到的图.png", content_type="image/png")

    monkeypatch.setattr(client, "download_message_resource_named", named)

    out = _run(
        "feishu_take_resource",
        {"message_id": "om_42", "file_key": "img_v2_abc", "resource_type": "image"},
        ws,
    )

    assert calls == [(bot_id, "om_42", "img_v2_abc", "image")]
    assert out["name"] == "收到的图.png"
    assert out["size_bytes"] == len(data)
    with SessionLocal() as db:
        asset = db.get(Asset, out["asset_id"])
        assert asset is not None, "附件必须真的落成素材"
        assert (asset.kind, asset.name, asset.source) == ("image", "收到的图.png", "feishu")
        assert asset.workspace_id == ws


# ---------------- ③ 「回个表情」 ----------------


def test_回个表情_调用参数对(monkeypatch) -> None:
    ws = _workspace()
    bot_id = _bot(ws)
    calls: list[tuple] = []

    def call_api(bot, method, url, body=None):
        calls.append((bot.id, method, url, body))
        return {"code": 0, "data": {"reaction_id": "rx_9"}}

    monkeypatch.setattr(client, "call_api", call_api)

    out = _run("feishu_reaction", {"message_id": "om_7", "emoji_type": "THUMBSUP"}, ws)

    assert out["reaction_id"] == "rx_9"
    assert calls == [
        (bot_id, "POST", f"{client.SEND_URL}/om_7/reactions", {"reaction_type": {"emoji_type": "THUMBSUP"}})
    ]


def test_回个表情_飞书拒了要算失败(monkeypatch) -> None:
    """`client.add_reaction` 是**尽力而为**的(它服务的是"正在输入"那个点缀,坏了也不能弄断回复链路)。
    节点不是点缀:它整个存在的意义就是加上那个表情,加不上就得说。
    """
    ws = _workspace()
    _bot(ws)
    monkeypatch.setattr(client, "call_api", lambda bot, method, url, body=None: {"code": 230001, "msg": "nope"})

    with pytest.raises(WorkflowDomainError) as raised:
        _run("feishu_reaction", {"message_id": "om_7", "emoji_type": "OK"}, ws)
    assert raised.value.key == "feishuErr_reaction", raised.value


# ---------------- ④ 「列出机器人所在的群」 ----------------


def test_列出机器人所在的群_跟完分页_解析成_id_与名字(monkeypatch) -> None:
    ws = _workspace()
    bot_id = _bot(ws)
    pages = [
        {"code": 0, "data": {"items": [{"chat_id": "oc_a", "name": "甲群"}], "has_more": True, "page_token": "t1"}},
        {"code": 0, "data": {"items": [{"chat_id": "oc_b", "name": "乙群"}], "has_more": False}},
    ]
    urls: list[str] = []

    def call_api(bot, method, url, body=None):
        urls.append(url)
        return pages[len(urls) - 1]

    monkeypatch.setattr(client, "call_api", call_api)

    out = _run("feishu_chats", {}, ws)

    assert out["chats"] == [{"id": "oc_a", "name": "甲群"}, {"id": "oc_b", "name": "乙群"}]
    assert out["ids"] == ["oc_a", "oc_b"]
    assert out["count"] == 2
    assert len(urls) == 2 and "page_token=t1" in urls[1], "第二页要拿着上一页给的 page_token 去要"
    assert bot_id


def test_列出机器人所在的群_没绑机器人也是失败() -> None:
    """列不出来就是列不出来 —— 交一份空清单会让下游的「发到某个群」拿到空 id,失败出现在更远的地方。"""
    ws = _workspace()
    with pytest.raises(WorkflowDomainError) as raised:
        _run("feishu_chats", {}, ws)
    assert raised.value.key == "wfErr_feishuNoBot", raised.value


def test_列出机器人所在的群_limit_为0_当场说清而不是悄悄换成200(monkeypatch) -> None:
    """`whole_number(...) or 200` 把用户写的 0 静默换成了 200。

    0 在这儿的含义只能是"一个群都不列" —— 而这个节点的用处正是交出群清单(执行器自己还
    `max(1, ...)` 兜了一下),飞书那条接口也不认 0。所以按「最少 1」当场说清,而不是把 0 吃掉:
    填了 0 的人以为自己设了,跑出来的却是默认的 200 个群。
    """
    ws = _workspace()
    _bot(ws)
    calls: list = []
    monkeypatch.setattr(
        client, "call_api",
        lambda bot, method, url, body=None: (
            calls.append(url), {"code": 0, "data": {"items": [], "has_more": False}}
        )[1],
    )

    with pytest.raises(WorkflowDomainError) as raised:
        _run("feishu_chats", {"limit": 0}, ws)

    assert raised.value.key == "wfErr_belowMin", raised.value
    #: 参数落库时会过一道 JSON 化(见 core/i18n.stored_param),所以这里比的是它的样子。
    assert str(raised.value.params.get("min")) == "1", raised.value.params
    assert "不能小于 1" in str(raised.value), f"要说清最少多少:{raised.value}"
    assert calls == [], "数字就不对,不该先去问飞书"


# ---------------- ⑤ 目标解析:一份实现,三处用 ----------------


class _Job:
    """`routing` 只看这两格(任务载荷里的回执、发起人)。"""

    def __init__(self, payload: dict, created_by: str = "") -> None:
        self.payload = payload
        self.created_by = created_by


def test_目标解析_origin_回到这次运行来的那个飞书会话() -> None:
    from app.db.models import AgentSession
    from app.domain.feishu import routing

    ws = _workspace()
    bot_id = _bot(ws)
    with SessionLocal() as db:
        session = AgentSession(workspace_id=ws, origin="feishu", external_key=f"feishu:{bot_id}:oc_from_here")
        db.add(session)
        db.commit()
        resolved = routing.resolve(
            db, workspace_id=ws, channel="origin", bot_id="", to="", raw_type="",
            job=_Job({"receipt": {"session_id": session.id}}),
        )

    assert resolved.target is not None
    assert (resolved.target.bot.id, resolved.target.receive_id, resolved.target.receive_type) == (
        bot_id, "oc_from_here", "chat_id",
    )


def test_目标解析_触发器任务从载荷里的来源群解析() -> None:
    """trigger job 没有 AgentSession;origin 必须从起跑时写下的 bot/chat 解,不能退回 owner 私聊。"""
    from types import SimpleNamespace

    from app.domain.feishu import routing

    ws = _workspace()
    bot_id = _bot(ws)

    with SessionLocal() as db:
        got = routing.run_origin(
            db,
            SimpleNamespace(
                workspace_id=ws,
                payload={"trigger_bot_id": bot_id, "trigger_chat_id": "oc_from_trigger"},
            ),
        )

    assert got is not None
    assert got[0].id == bot_id
    assert got[1] == "oc_from_trigger"


@pytest.mark.parametrize(
    ("channel", "to", "raw_type", "expected"),
    [
        ("chat", "oc_room", "", ("oc_room", "chat_id")),
        ("user", OPEN_ID, "", (OPEN_ID, "open_id")),
        ("raw", "ou_anything", "open_id", ("ou_anything", "open_id")),
        ("raw", "oc_anything", "", ("oc_anything", "chat_id")),
    ],
)
def test_目标解析_四档写法各解到哪(channel, to, raw_type, expected) -> None:
    from app.domain.feishu import routing

    ws = _workspace()
    bot_id = _bot(ws)
    _bind(ws)
    with SessionLocal() as db:
        resolved = routing.resolve(
            db, workspace_id=ws, channel=channel, bot_id=bot_id, to=to, raw_type=raw_type, job=None
        )
    assert resolved.target is not None
    assert (resolved.target.receive_id, resolved.target.receive_type) == expected
    assert resolved.target.bot.id == bot_id


def test_目标解析_私聊必须发给这个工作区已绑定的人() -> None:
    """`channel=user` 的契约是「一个**已绑定**的人」。没绑过的 open_id 不猜着发 ——
    手填任意 id 是 `raw` 那一档的事(那一档明确说了"机器人看得见的都行")。"""
    from app.domain.feishu import routing

    ws = _workspace()
    _bot(ws)
    with SessionLocal() as db:
        resolved = routing.resolve(
            db, workspace_id=ws, channel="user", bot_id="", to="ou_a_stranger", raw_type="", job=None
        )
    assert resolved.target is None
    assert resolved.reason == "not-bound"


def test_目标解析_none_就是不发飞书这个明确选择() -> None:
    from app.domain.feishu import routing

    ws = _workspace()
    _bot(ws)
    with SessionLocal() as db:
        resolved = routing.resolve(db, workspace_id=ws, channel="none", bot_id="", to="", raw_type="", job=None)
    assert resolved.target is None
    assert resolved.reason == "none", "「仅站内」和「发不出去」不是同一件事,理由要分得开"


def test_通知方式认不出_当场说清_而不是悄悄发给发起人(monkeypatch) -> None:
    """`channel` 认不出的值此前**静默退回 origin** —— 而这个节点的声明里根本没有 `none` 那一档,
    所以这种写法只会从手改 / 迁移来的图进来。退回 origin 的后果是:本该不发的图,发给了发起人。

    这里钉两件事:它当场失败(说清是哪一格、能写哪些值),而且一个字都没发出去。
    """
    from app.db.models import Job
    from app.domain.jobs import reset_parent_job, set_parent_job

    ws = _workspace()
    _bot(ws)
    _bind(ws)  # 发起人绑过飞书 —— 旧实现退回 origin 之后正是私聊他
    seen = _sent(monkeypatch)
    with SessionLocal() as db:
        job = Job(workspace_id=ws, kind="workflow", payload={}, created_by=user_id())
        db.add(job)
        db.commit()
        job_id = job.id

    token = set_parent_job(job_id)
    try:
        with pytest.raises(WorkflowDomainError) as raised:
            _run(
                "feishu_message",
                {"channel": "chatroom", "to": "oc_room", "format": "text", "text": "hi"},
                ws,
            )
    finally:
        reset_parent_job(token)

    assert raised.value.key == "wfErr_feishuUnknownChannel", raised.value
    assert "chatroom" in str(raised.value), f"要说清写的是哪个值:{raised.value}"
    assert "origin" in str(raised.value) and "raw" in str(raised.value), f"要说清能写哪些值:{raised.value}"
    assert seen["texts"] == [] and seen["cards"] == [], "认不出的通知方式一个字都不该发出去"


def test_等人确认那条路走同一份解析() -> None:
    """`route_for_approval` 此前自己解了一遍(读回执、读绑定、挑机器人)—— 那正是"路由看不见"的来源。
    它现在必须走 `routing.resolve`,而且不再自己碰回执 / 外部会话键 / 挑机器人。
    """
    from app.integrations.feishu import approvals as feishu_approvals
    from tests.util import executable_source

    source = executable_source(feishu_approvals)
    assert "routing.resolve" in source
    assert "external_key" not in source, "外部会话键的解析只有 routing 一处"
    assert '"receipt"' not in source, "回执的解析只有 routing 一处"
    assert "bot_for_user" not in source, "挑机器人只有 routing 一处"


def test_工作区里没有机器人时_解析给出说得清的理由() -> None:
    from app.domain.feishu import routing

    ws = _workspace()
    with SessionLocal() as db:
        assert db.query(Workspace).filter_by(id=ws).count() == 1  # 工作区在,机器人没有
        resolved = routing.resolve(
            db, workspace_id=ws, channel="chat", bot_id="", to="oc_room", raw_type="", job=None
        )
    assert resolved.target is None and resolved.reason == "no-bot"


# ---------------- ⑥ 检查器里那几格是选择器,不是手抄 id ----------------


def _options(source: str, ws: str, *, parent: str = "") -> list[dict]:
    from app.domain.workflows.field_options import OptionContext, field_options

    with SessionLocal() as db:
        return field_options(
            db, source, OptionContext(workspace_id=ws, user_id=None, parent=parent, locale="zh")
        )


def test_机器人那一格列的是这个工作区的机器人() -> None:
    ws = _workspace()
    mine = _bot(ws, name="我们的助手")
    with SessionLocal() as db:
        other = Workspace(name="别人的")
        db.add(other)
        db.flush()
        db.add(FeishuBot(workspace_id=other.id, name="别人的", app_id="cli_z", app_secret="s"))
        db.commit()
    assert _options("feishu_bots", ws) == [{"value": mine, "label": "我们的助手"}]


def test_收件人那一格_私聊列已绑定的人_发群列机器人所在的群(monkeypatch) -> None:
    """**同一个值格装着两种东西**,装哪种由 `channel` 说(它就是 depends_on 的那个父字段)——
    所以这一格的下拉必须跟着父字段换源,不然私聊那一档会列出群、发群那一档会列出人。"""
    ws = _workspace()
    bot_id = _bot(ws, name="助手")
    _bind(ws)
    monkeypatch.setattr(
        client, "call_api",
        lambda bot, method, url, body=None: {
            "code": 0, "data": {"items": [{"chat_id": "oc_room", "name": "产品群"}], "has_more": False}
        },
    )

    assert [one["value"] for one in _options("feishu_targets", ws, parent="user")] == [OPEN_ID]
    assert _options("feishu_targets", ws, parent="chat") == [
        {"value": "oc_room", "label": "产品群", "bot_id": bot_id}
    ]
    #: 另外两档(哪来发回哪 / 手填 id)用不上这一格:给清单反而是误导。
    assert _options("feishu_targets", ws, parent="origin") == []
    assert _options("feishu_targets", ws, parent="") == []


def test_收件人那一格_两台机器人时那串id标着是谁的() -> None:
    """open_id 按飞书应用隔离:同一个人在两台机器人上是两串不同的 id,而这一格存的就是那一串。

    清单里不分是谁的,选中的那串配别的机器人发出去就是飞书直接拒 —— 所以不止一台时标签带上
    机器人名(见 field_options._feishu_bound_users)。
    """
    ws = _workspace()
    first = _bot(ws, name="一号")
    second = _bot(ws, name="二号")
    _bind(ws, "ou_in_one", bot_id=first)
    _bind(ws, "ou_in_two", bot_id=second)

    assert _options("feishu_targets", ws, parent="user") == [
        {"value": "ou_in_one", "label": "tester · 一号", "bot_id": first},
        {"value": "ou_in_two", "label": "tester · 二号", "bot_id": second},
    ]


def test_收件人那一格_同一个人在两台应用上各带各的bot_id() -> None:
    """open_id 按飞书应用隔离:同一个人在一号、二号上各是一串不同的 id、各是一条绑定。

    两项必须各自说清自己属于**哪台机器人** —— 前端选中时要把「机器人」那一格一并写上,
    而它拿不到"选项属于谁"这件事。机器人的名字写在标签里,**不许**从标签反推(那是禁掉的猜法):
    依据只能是这个键。
    """
    ws = _workspace()
    first = _bot(ws, name="一号", app_id="cli_one")
    second = _bot(ws, name="二号", app_id="cli_two")
    _bind(ws, "ou_in_one", bot_id=first)
    _bind(ws, "ou_in_two", bot_id=second)

    options = _options("feishu_targets", ws, parent="user")

    assert [one["value"] for one in options] == ["ou_in_one", "ou_in_two"], "值仍然是那串 open_id,语义没动"
    assert [one["bot_id"] for one in options] == [first, second], "每一项带着自己那台机器人的 id"
    assert options[0]["bot_id"] != options[1]["bot_id"], "同一个人,两台应用 → 两个不同的 bot_id"


def test_收件人那一格_发群时两台机器人各自带各自的bot_id(monkeypatch) -> None:
    """发群那一支同理:chat_id 也按飞书应用隔离,同一个群在两台应用眼里是两串不同的 id。

    「选中 B 的收件人、却让运行用 A 发」正是这里要挡的事 —— 每一项都得说清这串 id 是哪台
    机器人眼里的,不然那串 id 配上另一台的 token,飞书直接拒。
    """
    ws = _workspace()
    first = _bot(ws, name="一号", app_id="cli_one")
    second = _bot(ws, name="二号", app_id="cli_two")
    #: 同一个群(都叫「产品群」),两台机器人各自看见自己那串 chat_id。
    seen_by_bot = {first: "oc_seen_by_one", second: "oc_seen_by_two"}

    def call_api(bot, method, url, body=None):
        return {"code": 0, "data": {"items": [{"chat_id": seen_by_bot[bot.id], "name": "产品群"}], "has_more": False}}

    monkeypatch.setattr(client, "call_api", call_api)

    options = _options("feishu_targets", ws, parent="chat")

    assert [one["value"] for one in options] == ["oc_seen_by_one", "oc_seen_by_two"], "值仍然是那串 chat_id,语义没动"
    assert [one["bot_id"] for one in options] == [first, second], "每一项带着自己那台机器人的 id"
    assert options[0]["bot_id"] != options[1]["bot_id"], "同一个群,两台应用 → 两个不同的 bot_id"
    #: 标签的现有形状没动:不止一台时带机器人名,名字在标签里,但归属的依据是 bot_id 而不是它。
    assert [one["label"] for one in options] == ["一号 / 产品群", "二号 / 产品群"]


def test_收件人那一格_飞书问不到就给空表而不是把这一页打红(monkeypatch) -> None:
    """它是一个下拉:对方没开、超时、机器人不在任何群里,都不该让整张检查器变成错误。
    声明里写了 allow_custom,问不到的时候人还能把 id 填进去。"""
    ws = _workspace()
    _bot(ws)

    def boom(bot, method, url, body=None):
        raise RuntimeError("对方没开")

    monkeypatch.setattr(client, "call_api", boom)
    assert _options("feishu_targets", ws, parent="chat") == []

