"""确认卡属于哪次对话,由**凭据**决定,不由调用方声明。

这个字段此前是请求体里的一个字符串:sidecar 把 `sessionId` 一路传成 `ToolInvocation.session_id`
→ contextvar → `ConfirmationCreate.session_id`。填错了无非是卡显示在别的对话里 —— 直到它开始决定
**要不要自动放行**(三档权限模式):那时一个拿着同一份凭据的外部智能体,只要在请求体里填上那个
开了 bypass 的会话 id,就能让自己的动作被自动执行。

这不是跨用户提权(攻击者已经有这个用户的凭据了),是**同一份凭据内部的混淆代理**:用户为
「我在这个对话里盯着」授的权,被一个他没盯着的通道用掉了。

做法是把归属挂在**令牌**上:一次 turn 一个令牌,铸的时候正好知道是哪个会话;工具调用复用调用方
凭据,所以归属自动一路传到开卡处。请求体里那个字段整个删掉 —— 留着它就是第二条会和令牌打架的
路径(见 docs/adr/0006 的同一条理由:不做多路兼容)。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import AuthSession, ToolConfirmation, User
from tests.util import fresh_client


def _sequence(client, workspace_id: str) -> str:
    project = client.post("/api/projects", json={"workspace_id": workspace_id, "name": "P"}).json()
    return client.post(
        "/api/sequences", json={"workspace_id": workspace_id, "project_id": project["id"], "name": "S"}
    ).json()["id"]


def _card_payload(workspace_id: str, sequence_id: str, **extra) -> dict:
    return {
        "workspace_id": workspace_id,
        "tool": "edit_timeline",
        "payload": {"sequence_id": sequence_id, "operations": [{"kind": "add_track", "track_kind": "video"}]},
        **extra,
    }


def _owner_of(card_id: str) -> str | None:
    with SessionLocal() as db:
        return db.get(ToolConfirmation, card_id).session_id


def test_a_turn_token_carries_its_session() -> None:
    """铸 turn 令牌的地方正好知道是哪个会话 —— 归属从这里出发,不再靠调用方转述。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post(
        "/api/agent/sessions", json={"workspace_id": workspace["id"], "title": "T"}
    ).json()

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "tester").one()
        token = mint_service_session(db, user.id, agent_session_id=session["id"])
        assert db.get(AuthSession, token).agent_session_id == session["id"]


def test_the_card_belongs_to_the_session_the_token_names() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post(
        "/api/agent/sessions", json={"workspace_id": workspace["id"], "title": "T"}
    ).json()
    sequence_id = _sequence(client, workspace["id"])

    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "tester").one()
        token = mint_service_session(db, user.id, agent_session_id=session["id"])
    client.headers["Authorization"] = f"Bearer {token}"

    card = client.post("/api/confirmations", json=_card_payload(workspace["id"], sequence_id))
    assert card.status_code == 200, card.text
    assert _owner_of(card.json()["id"]) == session["id"]


def test_a_claimed_session_id_in_the_body_is_ignored() -> None:
    """伪造别人的会话 id 不该改变归属 —— 令牌里没有会话,这张卡就没有会话。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    victim = client.post(
        "/api/agent/sessions", json={"workspace_id": workspace["id"], "title": "受害会话"}
    ).json()
    sequence_id = _sequence(client, workspace["id"])

    # 登录令牌(没有会话归属)—— MCP 直连、飞书外部智能体都是这个形状。
    card = client.post(
        "/api/confirmations", json=_card_payload(workspace["id"], sequence_id, session_id=victim["id"])
    )

    assert card.status_code == 200, card.text
    assert _owner_of(card.json()["id"]) is None, "请求体里声明的会话 id 被采信了"


def test_an_external_agents_card_stays_unowned() -> None:
    """没有会话的卡由全局确认中心兜底 —— 这条行为不能因为改了归属来源而丢。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    sequence_id = _sequence(client, workspace["id"])

    card = client.post("/api/confirmations", json=_card_payload(workspace["id"], sequence_id)).json()

    assert _owner_of(card["id"]) is None
    unowned = client.get(f"/api/confirmations?workspace_id={workspace['id']}&unowned=true").json()
    assert card["id"] in [row["id"] for row in unowned]


def test_the_body_no_longer_has_a_session_field() -> None:
    """删掉而不是忽略:留着一个"填了也不生效"的字段,下一个人会以为它生效。"""
    from app.api.schemas import ConfirmationCreate

    assert "session_id" not in ConfirmationCreate.model_fields


def test_tool_calls_do_not_carry_a_session_field_either() -> None:
    from app.api.routes.agent_tools import ToolInvocation

    assert "session_id" not in ToolInvocation.model_fields
