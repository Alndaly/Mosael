"""「只列我能拍板的」确认卡:列表里出现 ⇔ 批准不会被权限挡回。

全局确认中心此前拉的是「他看得见的全部」,于是同事共享给我的对话里的卡也在里面 —— 看得见,点批准却回 403
(替主人拍板只有主人能做,见 domain/agent/sessions.ensure_decides_for)。中心现在只拉 `decidable=true`。

出清单(`decidable_filter` / `decides_for_filter`)和批的那一刻(`_ensure_decides` / `ensure_decides_for`)是两份
写法、一个问题,这里把两边对着答一遍:同一批卡,列出来的每一张批得了,没列出来的每一张批不了。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.db.models import User
from app.domain.agent import host
from app.domain.agent.confirmations import request_confirmation
from tests.util import fresh_client, second_client


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """批下去不真的开浏览器 —— 这里测的是谁批得了,不是批了之后做什么。"""
    monkeypatch.setattr("app.domain.agent.confirmations._execute_approved", lambda _db, _confirmation: {})


def _join(owner: TestClient, workspace: str, username: str, role: str) -> TestClient:
    client = second_client(username)
    owner.post(f"/api/workspaces/{workspace}/invitations", json={"username": username, "role": role})
    invitation = client.get("/api/invitations").json()["invitations"][0]
    client.post(f"/api/invitations/{invitation['id']}/accept")
    return client


def _session(client: TestClient, workspace: str, *, shared: bool) -> str:
    sid = client.post("/api/agent/sessions", json={"workspace_id": workspace, "title": "脚本讨论"}).json()["id"]
    if shared:
        client.post(f"/api/shares/agent_session/{sid}", json={"workspace_id": workspace})
    return sid


def _card(workspace: str, sid: str | None) -> str:
    """一张待批的 browser_open 卡(不校验外部实体,测的只是归属)。`sid` 为空 = 没挂在对话上。"""
    with SessionLocal() as db:
        actor = db.query(User).filter(User.username == "tester").one()
        card_id = request_confirmation(
            db, workspace_id=workspace, tool="browser_open", payload={"url": "https://example.com"},
            actor_id=actor.id, session_id=sid,
        ).id
        db.commit()  # 测试是入口:领域函数不提交
        return card_id


def _listed(client: TestClient, workspace: str, *, decidable: bool) -> set[str]:
    query = f"/api/confirmations?workspace_id={workspace}&status=pending"
    res = client.get(query + ("&decidable=true" if decidable else ""))
    assert res.status_code == 200, res.text
    return {card["id"] for card in res.json()}


def _board() -> tuple[TestClient, TestClient, TestClient, str, dict[str, str]]:
    """主人(tester)、同事(editor)、只读成员(viewer),和一桌各种归属的卡。"""
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()["id"]
    mate = _join(owner, workspace, "mate", "editor")
    viewer = _join(owner, workspace, "viewer", "viewer")
    with SessionLocal() as db:
        group_chat = host.get_or_create_external_session(
            db, workspace_id=workspace, origin="feishu", external_key="feishu:chat-1", title="飞书群"
        ).id
    gone = _session(owner, workspace, shared=True)
    cards = {
        "no_session": _card(workspace, None),
        "group_chat": _card(workspace, group_chat),
        "mate_own": _card(workspace, _session(mate, workspace, shared=False)),
        "owner_shared": _card(workspace, _session(owner, workspace, shared=True)),
        "owner_private": _card(workspace, _session(owner, workspace, shared=False)),
        "session_deleted": _card(workspace, gone),
    }
    assert owner.delete(f"/api/agent/sessions/{gone}").status_code == 204
    return owner, mate, viewer, workspace, cards


def test_共享来的对话里的卡_看得见_但不在我能拍板的清单里() -> None:
    _owner, mate, _viewer, workspace, cards = _board()

    seen = _listed(mate, workspace, decidable=False)
    decidable = _listed(mate, workspace, decidable=True)

    assert cards["owner_shared"] in seen
    assert cards["owner_shared"] not in decidable
    # 工作区的卡(没挂对话、挂在无主的飞书群聊上)和他自己对话里的卡,都归他拍板。
    assert decidable == {cards["no_session"], cards["group_chat"], cards["mate_own"]}
    # 看不见的本来就不在任何一份里。
    assert cards["owner_private"] not in seen and cards["session_deleted"] not in seen


def test_主人的清单里有他共享出去的那张() -> None:
    owner, _mate, _viewer, workspace, cards = _board()

    decidable = _listed(owner, workspace, decidable=True)

    assert {cards["owner_shared"], cards["owner_private"], cards["no_session"], cards["group_chat"]} <= decidable
    assert cards["mate_own"] not in decidable  # 同事没共享的对话,主人也看不见
    assert cards["session_deleted"] not in decidable


def test_只读成员一张都拍不了() -> None:
    _owner, _mate, viewer, workspace, cards = _board()

    assert cards["no_session"] in _listed(viewer, workspace, decidable=False)
    assert _listed(viewer, workspace, decidable=True) == set()
    assert viewer.post(f"/api/confirmations/{cards['no_session']}/approve").status_code == 403


@pytest.mark.parametrize("who", ["owner", "mate", "viewer"])
def test_列出来的每一张都批得了_没列出来的每一张都批不了(who: str) -> None:
    owner, mate, viewer, workspace, cards = _board()
    client = {"owner": owner, "mate": mate, "viewer": viewer}[who]
    decidable = _listed(client, workspace, decidable=True)

    for name, card in cards.items():
        res = client.post(f"/api/confirmations/{card}/approve")
        if card in decidable:
            assert res.status_code == 200, (name, res.text)
            assert res.json()["status"] == "executed", (name, res.json())
        else:
            # 看不见的 404,看得见批不了的 403 —— 总之被权限挡回,卡还在等。
            assert res.status_code in (403, 404), (name, res.status_code, res.text)
