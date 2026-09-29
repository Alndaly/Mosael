"""共享来的对话**只能看**。

对话是某人的私人工作线程。主人把它共享进工作区,是给同事看:消息、轨迹、花费、待拍板的卡都看得到。此前写路径
只查了「看得见」,于是同事能把别人的对话改名、删掉、收进自己的分组、换掉模型与权限模式,还能在里面发消息、
停掉主人正在跑的那一轮、替主人答选择卡、批确认卡 —— 批下去的动作记在他头上、用他的钥匙跑。

读写两道闸在 domain/agent/sessions(判据与生成会话同一份,住在 domain/sharing):看 = 是主人或共享进了这个
工作区(看不见就 404);写 = 还得是主人(403)。下面每一条写路径被拒、读路径放行。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.db.models import AgentMessage, AgentQuestion, ToolConfirmation, User
from app.domain.agent.confirmations import request_confirmation
from tests.util import fresh_client, second_client

QUESTION = [{"question": "选哪个?", "options": [{"label": "甲"}, {"label": "乙"}]}]


def _team() -> tuple[TestClient, str, TestClient]:
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()["id"]
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{workspace}/invitations", json={"username": "mate", "role": "editor"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")
    return owner, workspace, mate


def _session(owner: TestClient, workspace: str, *, shared: bool) -> str:
    sid = owner.post("/api/agent/sessions", json={"workspace_id": workspace, "title": "脚本讨论"}).json()["id"]
    if shared:
        owner.post(f"/api/shares/agent_session/{sid}", json={"workspace_id": workspace})
    return sid


def _question(owner: TestClient, sid: str) -> str:
    return owner.post("/api/agent/questions", json={"session_id": sid, "questions": QUESTION}).json()["id"]


def _card(workspace: str, sid: str | None) -> str:
    """这次对话里的一张待批确认卡(browser_open:不校验外部实体,测的只是归属)。`sid` 为空 = 没挂在对话上。"""
    with SessionLocal() as db:
        owner = db.query(User).filter(User.username == "tester").one()
        card = request_confirmation(
            db, workspace_id=workspace, tool="browser_open", payload={"url": "https://example.com"},
            actor_id=owner.id, session_id=sid,
        )
        db.commit()  # 测试是入口:领域函数不提交
        return card.id


def _denied(res) -> None:
    assert res.status_code == 403, res.text
    detail = res.json()["detail"]
    assert "主人" in detail or "owner" in detail, detail


#: (方法, 路径模板, 请求体)。`{sid}` / `{mid}` 在用例里填。每一条都是在别人的对话里写。
WRITES: list[tuple[str, str, dict | None]] = [
    ("patch", "/api/agent/sessions/{sid}", {"title": "我改的"}),
    ("patch", "/api/agent/sessions/{sid}", {"group_id": "whatever"}),
    ("patch", "/api/agent/sessions/{sid}", {"model": "gpt-4o"}),
    ("patch", "/api/agent/sessions/{sid}", {"provider_profile_id": ""}),
    ("patch", "/api/agent/sessions/{sid}", {"thinking_level": "high"}),
    ("patch", "/api/agent/sessions/{sid}", {"analysis_video_mode": "frames"}),
    ("patch", "/api/agent/sessions/{sid}", {"permission_mode": "auto"}),
    ("patch", "/api/agent/sessions/{sid}", {"auto_allow_tools": ["browser_open"]}),
    ("post", "/api/agent/sessions/{sid}/messages", {"content": "我替你说一句"}),
    ("post", "/api/agent/sessions/{sid}/compact", None),
    ("post", "/api/agent/sessions/{sid}/queue/{mid}/steer", None),
    ("delete", "/api/agent/sessions/{sid}/queue/{mid}", None),
    ("post", "/api/agent/sessions/{sid}/stop", None),
    ("put", "/api/agent/sessions/{sid}/plan", {"steps": ["改计划"]}),
    ("post", "/api/agent/sessions/{sid}/view", {"view": "home"}),
    ("delete", "/api/agent/sessions/{sid}/view", None),
    ("post", "/api/agent/questions", {"session_id": "{sid}", "questions": QUESTION}),
    ("delete", "/api/agent/sessions/{sid}", None),
]


def _call(client: TestClient, method: str, path: str, body: dict | None, **ids: str):
    url = path.format(**ids)
    if body is None:
        return getattr(client, method)(url)
    filled = {key: (value.format(**ids) if isinstance(value, str) else value) for key, value in body.items()}
    return client.request(method.upper(), url, json=filled)


@pytest.mark.parametrize("method, path, body", WRITES, ids=[f"{m} {p} {sorted(b or {})}" for m, p, b in WRITES])
def test_共享来的对话_同事的每一条写路径都被拒(method: str, path: str, body: dict | None) -> None:
    owner, workspace, mate = _team()
    sid = _session(owner, workspace, shared=True)
    with SessionLocal() as db:
        mid = db.query(AgentMessage.id).filter(AgentMessage.session_id == sid).scalar() or "no-such-message"

    _denied(_call(mate, method, path, body, sid=sid, mid=mid))

    kept = owner.get(f"/api/agent/sessions/{sid}").json()
    assert (kept["title"], kept["model"], kept["group_id"], kept["thinking_level"]) == ("脚本讨论", None, None, "off")
    assert (kept["permission_mode"], kept["auto_allow_tools"], kept["plan"]) == ("manual", [], None)
    assert owner.get(f"/api/agent/sessions/{sid}/messages").json() == []
    assert owner.get(f"/api/agent/questions?session_id={sid}").json() == []


def test_共享来的对话_同事答不了选择卡_批不了确认卡() -> None:
    """替主人拍板也是在他的对话里写:作答会变成对话里的一条用户消息,批准会以批的人的身份执行。"""
    owner, workspace, mate = _team()
    sid = _session(owner, workspace, shared=True)
    qid = _question(owner, sid)
    card = _card(workspace, sid)

    _denied(mate.post(f"/api/agent/questions/{qid}/answer", json={"answers": {"选哪个?": ["甲"]}}))
    _denied(mate.post(f"/api/agent/questions/{qid}/dismiss"))
    _denied(mate.post(f"/api/confirmations/{card}/approve"))
    _denied(mate.post(f"/api/confirmations/{card}/reject"))

    with SessionLocal() as db:
        assert db.get(AgentQuestion, qid).status == "pending"
        assert db.get(ToolConfirmation, card).status == "pending"
    # 主人照常拍板(拒绝不执行任何东西,只看闸放不放)。
    assert owner.post(f"/api/confirmations/{card}/reject").json()["status"] == "rejected"
    assert owner.post(f"/api/agent/questions/{qid}/dismiss").status_code == 200


def test_共享来的对话_同事看得见_标着不是他的() -> None:
    owner, workspace, mate = _team()
    sid = _session(owner, workspace, shared=True)
    qid = _question(owner, sid)

    listed = mate.get(f"/api/agent/sessions?workspace_id={workspace}").json()
    assert [(one["id"], one["is_mine"]) for one in listed] == [(sid, False)]
    # 单取一条也要如实说「不是你的」—— 界面按它决定给不给写,默认值不能替它回答。
    assert mate.get(f"/api/agent/sessions/{sid}").json()["is_mine"] is False
    for path in (
        f"/api/agent/sessions/{sid}/messages",
        f"/api/agent/sessions/{sid}/usage-events",
        f"/api/agent/sessions/{sid}/queue",
        f"/api/agent/sessions/{sid}/stream",
        f"/api/agent/questions?session_id={sid}",
        f"/api/agent/questions/{qid}",
    ):
        assert mate.get(path).status_code == 200, path


def test_没共享的对话_同事连它在不在都不知道() -> None:
    owner, workspace, mate = _team()
    sid = _session(owner, workspace, shared=False)
    qid = _question(owner, sid)

    assert mate.get(f"/api/agent/sessions/{sid}").status_code == 404
    assert mate.get(f"/api/agent/questions/{qid}").status_code == 404
    assert mate.patch(f"/api/agent/sessions/{sid}", json={"title": "x"}).status_code == 404
    assert mate.post(f"/api/agent/sessions/{sid}/messages", json={"content": "x"}).status_code == 404
    assert mate.post(f"/api/agent/questions/{qid}/answer", json={"answers": {"选哪个?": ["甲"]}}).status_code == 404
    assert mate.delete(f"/api/agent/sessions/{sid}").status_code == 404


def test_主人照常能改_回来的那一份仍说是他的() -> None:
    owner, workspace, _mate = _team()
    sid = _session(owner, workspace, shared=True)
    renamed = owner.patch(f"/api/agent/sessions/{sid}", json={"title": "定稿"})
    assert renamed.status_code == 200
    assert (renamed.json()["title"], renamed.json()["is_mine"], renamed.json()["shared"]) == ("定稿", True, True)
    planned = owner.put(f"/api/agent/sessions/{sid}/plan", json={"steps": ["写脚本"]})
    assert planned.status_code == 200 and planned.json()["is_mine"] is True
    assert owner.delete(f"/api/agent/sessions/{sid}").status_code == 204


def test_问题记在它那次对话所在的工作区() -> None:
    """此前工作区由调用方另报,MCP 缺省报「第一个工作区」—— 对话在第二个工作区时,问题记错了地方。"""
    owner = fresh_client()
    owner.post("/api/workspaces", json={"name": "第一个"})
    second = owner.post("/api/workspaces", json={"name": "第二个"}).json()["id"]
    sid = _session(owner, second, shared=False)
    asked = owner.post("/api/agent/questions", json={"session_id": sid, "questions": QUESTION}).json()
    assert asked["workspace_id"] == second


# ---------- 挂在对话上的东西,跟着对话一起「看得见 / 看不见」 ----------
#
# 读闸不只守着 /agent/sessions/{id}/…:确认卡列着那次对话里的工具名和参数,笔记能引用对话里的一条消息。
# 这两处此前只查了「是不是工作区的人」,同事拿着别人私有对话的 id(或不带 id 拉整个工作区的待确认)就读得到。


def _message(sid: str, content: str = "预算只有三万") -> str:
    from app.domain.agent import host

    with SessionLocal() as db:
        message = host.append_message(db, sid, role="user", content=content)
        db.commit()
        return message.id


def _cards_seen(client: TestClient, workspace: str, **params: str) -> set[str]:
    query = "".join(f"&{key}={value}" for key, value in params.items())
    res = client.get(f"/api/confirmations?workspace_id={workspace}{query}")
    assert res.status_code == 200, res.text
    return {card["id"] for card in res.json()}


def test_没共享的对话_同事看不到它的确认卡() -> None:
    owner, workspace, mate = _team()
    sid = _session(owner, workspace, shared=False)
    card = _card(workspace, sid)

    assert mate.get(f"/api/confirmations?workspace_id={workspace}&session_id={sid}").status_code == 404
    assert card not in _cards_seen(mate, workspace)
    assert card not in _cards_seen(mate, workspace, status="pending")
    missing = mate.get("/api/confirmations/no-such-card")
    for res in (
        mate.get(f"/api/confirmations/{card}"),
        mate.post(f"/api/confirmations/{card}/approve"),
        mate.post(f"/api/confirmations/{card}/reject"),
    ):
        # 看不见和不存在是同一个回答,连 detail 都一样。
        assert (res.status_code, res.json()) == (missing.status_code, missing.json()) == (404, {"detail": "Not found"})
    with SessionLocal() as db:
        assert db.get(ToolConfirmation, card).status == "pending"

    # 主人自己照常看得见。
    assert _cards_seen(owner, workspace, session_id=sid) == {card}
    assert card in _cards_seen(owner, workspace, status="pending")
    assert owner.get(f"/api/confirmations/{card}").status_code == 200


def test_共享来的对话_同事看得见它的确认卡() -> None:
    owner, workspace, mate = _team()
    sid = _session(owner, workspace, shared=True)
    card = _card(workspace, sid)

    assert _cards_seen(mate, workspace, session_id=sid) == {card}
    assert card in _cards_seen(mate, workspace, status="pending")
    assert mate.get(f"/api/confirmations/{card}").status_code == 200


def test_工作区的卡_全局确认中心照旧兜底() -> None:
    """没挂在对话上的(MCP 直连)和挂在无主对话上的(飞书群聊会话)是工作区的卡:同事都看得见 ——
    否则智能体会一直干等一个没人看得到的确认。"""
    from app.domain.agent import host

    owner, workspace, mate = _team()
    with SessionLocal() as db:
        group_chat = host.get_or_create_external_session(
            db, workspace_id=workspace, origin="feishu", external_key="feishu:chat-1", title="飞书群"
        ).id
    no_session = _card(workspace, None)
    in_group_chat = _card(workspace, group_chat)

    assert {no_session, in_group_chat} <= _cards_seen(mate, workspace, status="pending")
    assert _cards_seen(mate, workspace, session_id=group_chat) == {in_group_chat}
    assert mate.get(f"/api/confirmations/{in_group_chat}").status_code == 200


def test_对话删了_留下的卡谁也看不到() -> None:
    """卡上的会话 id 不设外键,对话删掉后卡还在。删掉的是主人的私人线程,卡(工具名、参数)不该因此变成全工作区可读。"""
    owner, workspace, mate = _team()
    sid = _session(owner, workspace, shared=False)
    card = _card(workspace, sid)
    assert owner.delete(f"/api/agent/sessions/{sid}").status_code == 204

    assert card not in _cards_seen(mate, workspace)
    assert mate.get(f"/api/confirmations/{card}").status_code == 404


def test_笔记引用的消息_跟着它那次对话的可见性走() -> None:
    owner, workspace, mate = _team()
    private = _message(_session(owner, workspace, shared=False), "私下说的")
    shared = _message(_session(owner, workspace, shared=True), "给大家看的")

    def source(client: TestClient, message_id: str):
        return client.get(f"/api/notes/sources/message/{message_id}?workspace_id={workspace}")

    hidden, missing = source(mate, private), source(mate, "no-such-message")
    assert (hidden.status_code, hidden.json()) == (missing.status_code, missing.json())
    assert hidden.status_code == 404
    assert source(mate, shared).json()["content"] == "给大家看的"
    assert source(owner, private).json()["content"] == "私下说的"
