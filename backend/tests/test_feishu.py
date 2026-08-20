from __future__ import annotations

import json
import time

from app.ai.agent.adapters import TurnResult
from app.core.db import SessionLocal
from app.db.models import AgentSession
from app.integrations.feishu import service
from tests.util import fresh_client


def _configured(client):
    """让这个部署有一个可用的对话模型 —— 取默认模型没有"随便挑一个"的兜底
    (见 provider_models.resolve_default),所以"能对话"必须被显式配出来。"""
    from app.core.db import SessionLocal
    from tests.util import add_provider

    with SessionLocal() as db:
        add_provider(
            db, name="P", vendor="openai-compatible", base_url="http://localhost:1/v1",
            api_key="k", model="m", capability_ids=["chat"],
        )
        db.commit()


def test_extract_text_strips_mentions() -> None:
    assert service.extract_text('{"text": "@_user_1 @_user_2 帮我看看素材"}') == "帮我看看素材"
    assert service.extract_text('{"text": "普通消息"}') == "普通消息"
    assert service.extract_text("not-json") == ""


def test_seen_recently_dedupes() -> None:
    message_id = f"m-{time.time()}"
    assert service.seen_recently(message_id) is False
    assert service.seen_recently(message_id) is True


def test_bot_crud_and_permissions() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    created = client.post(
        "/api/feishu/bots",
        json={"workspace_id": ws["id"], "app_id": "cli_a1", "app_secret": "s3cret", "capability": "readonly"},
    ).json()
    assert created["capability"] == "readonly"
    assert "app_secret" not in created  # secrets never serialize

    listed = client.get(f"/api/feishu/bots?workspace_id={ws['id']}").json()
    assert len(listed) == 1

    updated = client.patch(f"/api/feishu/bots/{created['id']}", json={"capability": "editor", "enabled": False}).json()
    assert updated["capability"] == "editor"
    assert updated["enabled"] is False

    assert client.delete(f"/api/feishu/bots/{created['id']}").status_code == 204


def test_handle_incoming_routes_to_agent_and_replies(monkeypatch) -> None:
    client = fresh_client()
    _configured(client)
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    bot = client.post(
        "/api/feishu/bots",
        json={"workspace_id": ws["id"], "app_id": "cli_a2", "app_secret": "s3cret"},
    ).json()
    # stop_connection is a no-op in tests (start failed w/o real creds), status irrelevant here

    # The sender must be bound to a member first — the bot acts with that member's perms.
    me = client.get("/api/auth/me").json()
    with SessionLocal() as db:
        code, _ = service.issue_bind_code(db, ws["id"], me["id"])
        assert service._redeem_bind_code(db, ws["id"], "ou_sender", code) is not None

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(service, "run_turn", lambda *a, **k: TurnResult(text="已查看,共 2 个素材"))
    monkeypatch.setattr(service, "send_text", lambda bot, chat_id, text: sent.append((chat_id, text)))

    service.handle_incoming(bot["id"], "oc_chat_1", "msg-1", "ou_sender", content_json=json.dumps({"text": "看看素材"}))

    assert sent == [("oc_chat_1", "已查看,共 2 个素材")]
    with SessionLocal() as db:
        session = db.query(AgentSession).filter_by(external_key=f"feishu:{bot['id']}:oc_chat_1").one()
        assert session.origin == "feishu"
        assert session.status == "idle"
        roles = [m.role for m in session.messages]
        assert roles == ["user", "assistant"]

    # duplicate message id is dropped
    service.handle_incoming(bot["id"], "oc_chat_1", "msg-1", "ou_sender", content_json=json.dumps({"text": "看看素材"}))
    assert len(sent) == 1


def test_handle_incoming_unbound_sender_refused(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    bot = client.post(
        "/api/feishu/bots", json={"workspace_id": ws["id"], "app_id": "cli_a4", "app_secret": "s3cret"}
    ).json()
    ran: list[bool] = []
    sent: list[str] = []
    monkeypatch.setattr(service, "run_turn", lambda *a, **k: ran.append(True))
    monkeypatch.setattr(service, "send_text", lambda bot, chat_id, text: sent.append(text))

    service.handle_incoming(bot["id"], "oc_chat_x", "msg-x", "ou_intruder", content_json=json.dumps({"text": "偷偷改点东西"}))

    assert ran == []  # the agent never ran for an unbound sender
    assert sent and "绑定" in sent[0]


def test_handle_incoming_adapter_error_still_replies(monkeypatch) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    bot = client.post(
        "/api/feishu/bots",
        json={"workspace_id": ws["id"], "app_id": "cli_a3", "app_secret": "s3cret"},
    ).json()

    sent: list[str] = []
    from app.ai.agent.adapters import AdapterError

    def boom(*args, **kwargs):
        raise AdapterError("cli exploded")

    me = client.get("/api/auth/me").json()
    with SessionLocal() as db:
        code, _ = service.issue_bind_code(db, ws["id"], me["id"])
        service._redeem_bind_code(db, ws["id"], "ou_sender2", code)

    monkeypatch.setattr(service, "run_turn", boom)
    monkeypatch.setattr(service, "send_text", lambda bot, chat_id, text: sent.append(text))

    service.handle_incoming(bot["id"], "oc_chat_2", "msg-2", "ou_sender2", content_json=json.dumps({"text": "hi"}))
    assert sent and "失败" in sent[0]


def _bound_bot(client, monkeypatch, sent: list):
    """建 bot + 绑一个发送者 + 把外发消息接进 sent。"""
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    bot = client.post(
        "/api/feishu/bots", json={"workspace_id": ws["id"], "app_id": "cli_img", "app_secret": "s3cret"}
    ).json()
    me = client.get("/api/auth/me").json()
    with SessionLocal() as db:
        code, _ = service.issue_bind_code(db, ws["id"], me["id"])
        assert service._redeem_bind_code(db, ws["id"], "ou_img", code) is not None
    monkeypatch.setattr(service, "send_text", lambda bot, chat_id, text: sent.append((chat_id, text)))
    return ws, bot


def test_不认识的消息类型不再石沉大海(monkeypatch) -> None:
    """回归。以前 worker 里是 `if message_type != "text": return` —— 发一段语音过来,
    进程直接返回,用户那边永远等不到回复。**静默丢弃和"正在处理"长得一模一样**,
    而人只会一直等下去,这就是那个"卡死"。"""
    client = fresh_client()
    sent: list = []
    _, bot = _bound_bot(client, monkeypatch, sent)

    service.handle_incoming(bot["id"], "oc_v", "msg-v", "ou_img", message_type="audio", content_json="{}")

    assert len(sent) == 1
    assert "看不了语音" in sent[0][1]


def test_图片消息进素材库_并把素材id带进提示(monkeypatch) -> None:
    """图片走的是和桌面端回形针同一条路:入素材库 → 提示里引用 → 智能体用 analyze_asset 看图。
    不给飞书单开一套,也就不会有"飞书里能看、应用里找不到"的图片。"""
    client = fresh_client()
    _configured(client)
    sent: list = []
    ws, bot = _bound_bot(client, monkeypatch, sent)

    # 1x1 PNG，够走完落盘 + 探测 + 建记录这条真实链路
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d494844520000000100000001080600000"
        "01f15c4890000000a49444154789c6360000002000100ffff03000006000557bfabd4"
        "0000000049454e44ae426082"
    )
    monkeypatch.setattr(service, "download_message_resource", lambda *a, **k: png)
    prompts: list[str] = []

    def fake_turn(*args, **kwargs):
        prompts.append(kwargs["prompt"])
        return TurnResult(text="看到了")

    monkeypatch.setattr(service, "run_turn", fake_turn)

    service.handle_incoming(
        bot["id"], "oc_i", "msg-i", "ou_img", message_type="image", content_json=json.dumps({"image_key": "img_k1"})
    )

    assert sent == [("oc_i", "看到了")]
    assets = client.get(f"/api/assets?workspace_id={ws['id']}").json()
    assert [a["kind"] for a in assets] == ["image"]
    assert assets[0]["source"] == "feishu"
    # 提示里必须带上素材 id,否则模型知道"有张图"却拿不到它。
    assert assets[0]["id"] in prompts[0]
    assert "analyze_asset" in prompts[0]


def test_富文本消息的文字和内嵌图片都收(monkeypatch) -> None:
    """带格式粘贴一段话,飞书发过来的是 post —— 它对用户来说和普通文字没有任何区别,
    以前却和图片一样被整条丢掉。"""
    client = fresh_client()
    _configured(client)
    sent: list = []
    _, bot = _bound_bot(client, monkeypatch, sent)
    monkeypatch.setattr(service, "download_message_resource", lambda *a, **k: b"")
    prompts: list[str] = []
    monkeypatch.setattr(
        service, "run_turn", lambda *a, **k: (prompts.append(k["prompt"]), TurnResult(text="收到"))[1]
    )

    content = json.dumps(
        {"title": "标题", "content": [[{"tag": "text", "text": "帮我看看"}, {"tag": "a", "text": "链接"}]]}
    )
    service.handle_incoming(bot["id"], "oc_p", "msg-p", "ou_img", message_type="post", content_json=content)

    assert sent == [("oc_p", "收到")]
    assert "帮我看看" in prompts[0] and "标题" in prompts[0]


def test_图片下载失败也要回话(monkeypatch) -> None:
    client = fresh_client()
    sent: list = []
    _, bot = _bound_bot(client, monkeypatch, sent)

    def boom(*a, **k):
        raise service.FeishuError("下载飞书资源失败(404)")

    monkeypatch.setattr(service, "download_message_resource", boom)
    service.handle_incoming(
        bot["id"], "oc_e", "msg-e", "ou_img", message_type="image", content_json=json.dumps({"image_key": "k"})
    )
    assert len(sent) == 1 and "没能取回来" in sent[0][1]


def test_被重启打断的飞书会话会收到中断说明(monkeypatch) -> None:
    """会话状态早就被拨回 idle 了,但那条说明只写进了库 —— 桌面端看得到,而在飞书里
    发消息的人只看到沉默。这是"卡死"的另一半:开发时 --reload 尤其频繁。"""
    from app.ai.agent.host import reconcile_orphaned_agent_sessions

    client = fresh_client()
    sent: list = []
    _, bot = _bound_bot(client, monkeypatch, sent)
    monkeypatch.setattr(service, "run_turn", lambda *a, **k: TurnResult(text="好的"))
    service.handle_incoming(bot["id"], "oc_r", "msg-r", "ou_img", content_json=json.dumps({"text": "hi"}))
    sent.clear()

    with SessionLocal() as db:
        session = db.query(AgentSession).filter_by(external_key=f"feishu:{bot['id']}:oc_r").one()
        session.status = "running"  # 模拟一轮跑到一半进程没了
        db.commit()
        assert reconcile_orphaned_agent_sessions(db) == 1
        assert service.notify_interrupted_chats(db) == 1

    assert sent == [("oc_r", "上一轮对话因后端重启而中断,请重新发送。")]


def test_中断说明只发一次_不随每次重启重发(monkeypatch) -> None:
    """真机反馈:开发模式 --reload 频繁重启,飞书那头每次都收到一遍「请重新发送」。

    根因:挑要通知的会话时看的是「最后一条消息带中断标记」,而聊天里之后没人说话,
    它就一直是最后一条 —— 发过与否没有任何记号。发成功要标记,下次启动跳过。
    """
    from app.ai.agent.host import reconcile_orphaned_agent_sessions

    client = fresh_client()
    sent: list = []
    _, bot = _bound_bot(client, monkeypatch, sent)
    monkeypatch.setattr(service, "run_turn", lambda *a, **k: TurnResult(text="好的"))
    service.handle_incoming(bot["id"], "oc_once", "msg-o", "ou_img", content_json=json.dumps({"text": "hi"}))
    sent.clear()

    with SessionLocal() as db:
        session = db.query(AgentSession).filter_by(external_key=f"feishu:{bot['id']}:oc_once").one()
        session.status = "running"
        db.commit()
        reconcile_orphaned_agent_sessions(db)
        assert service.notify_interrupted_chats(db) == 1

    # 第二次启动:没有新的中断,聊天里也没人说话 —— **不能**再发。
    with SessionLocal() as db:
        assert reconcile_orphaned_agent_sessions(db) == 0
        assert service.notify_interrupted_chats(db) == 0
    assert len(sent) == 1, f"同一条中断说明发了 {len(sent)} 次"

    # 但**又一次真的被打断**时,要再通知 —— 去重挡的是重复播报,不是后续的真中断。
    with SessionLocal() as db:
        session = db.query(AgentSession).filter_by(external_key=f"feishu:{bot['id']}:oc_once").one()
        session.status = "running"
        db.commit()
        assert reconcile_orphaned_agent_sessions(db) == 1
        assert service.notify_interrupted_chats(db) == 1
    assert len(sent) == 2


def test_发送失败不标记_下次启动重试(monkeypatch) -> None:
    """失败多半是网络/令牌暂时不行,和「已送达」是两回事 —— 标了就永远沉默。"""
    from app.ai.agent.host import reconcile_orphaned_agent_sessions

    client = fresh_client()
    sent: list = []
    _, bot = _bound_bot(client, monkeypatch, sent)
    monkeypatch.setattr(service, "run_turn", lambda *a, **k: TurnResult(text="好的"))
    service.handle_incoming(bot["id"], "oc_fail", "msg-f", "ou_img", content_json=json.dumps({"text": "hi"}))
    sent.clear()

    with SessionLocal() as db:
        session = db.query(AgentSession).filter_by(external_key=f"feishu:{bot['id']}:oc_fail").one()
        session.status = "running"
        db.commit()
        reconcile_orphaned_agent_sessions(db)

    def boom(*a, **k):
        raise service.FeishuError("token 过期")

    real_send = service.send_text
    monkeypatch.setattr(service, "send_text", boom)
    with SessionLocal() as db:
        assert service.notify_interrupted_chats(db) == 0  # 发失败
    monkeypatch.setattr(service, "send_text", real_send)
    with SessionLocal() as db:
        assert service.notify_interrupted_chats(db) == 1  # 恢复后补上
