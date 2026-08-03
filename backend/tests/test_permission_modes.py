"""三档权限模式:手动(默认)/ auto / bypass。

确认门控此前是二元的 —— 走卡或不走卡。一次任务里点十几次,而其中大多数(时间线编辑、工作流增改)
是可撤销的:用户点的不是决定,是噪音。三档让用户一次性说清「这次对话里,哪一类动作不用问我」。

几条不能松的:

  - **bypass 绕过的是「用户同意」,不是「他有没有这个权限」。** 授权三道闸照走。
  - **没有会话的卡永远手动。** 它们没有会话可挂模式;继承任何默认都是授权范围逃逸。
  - **模式是谁开的谁用。** 飞书群聊共用一个会话,A 开的 bypass 不能替 B 做决定。
  - **自动放行必须留痕**,而且要能一眼看出是哪一档放的 —— 事后能查是 bypass 唯一可接受的前提。

`external` 在 auto 档下这一期仍然弹卡:规则与判断者是第 4 期(见 docs/AGENT_PERMISSION_MODES.md)。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import AgentSession, ToolConfirmation, User, Workflow
from app.domain.agent.autopilot import COST_AUTO_LIMIT, wait_for_idle_autopilot
from tests.util import fresh_client, second_client

START = {"id": "start_1", "type": "start", "config": {}}
CODE = {"id": "code_1", "type": "code", "config": {"code": "output = 1"}}


class Chat:
    """一次对话 + 它的 turn 令牌 —— 卡的归属由令牌决定,所以造卡必须换成它。"""

    def __init__(self, username: str = "tester") -> None:
        self.client = fresh_client(username) if username == "tester" else second_client(username)
        self.login_token = self.client.headers["Authorization"]
        self.workspace_id = self.client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        self.session_id = self.client.post(
            "/api/agent/sessions", json={"workspace_id": self.workspace_id, "title": "T"}
        ).json()["id"]

    def user_id(self, username: str = "tester") -> str:
        with SessionLocal() as db:
            return db.query(User).filter(User.username == username).one().id

    def set_mode(self, mode: str, *, expect: int = 200) -> None:
        response = self.client.patch(
            f"/api/agent/sessions/{self.session_id}", json={"permission_mode": mode}
        )
        assert response.status_code == expect, response.text

    def as_turn(self, username: str = "tester") -> None:
        """接下来的请求以「这次对话的 turn」身份发出。"""
        with SessionLocal() as db:
            user = db.query(User).filter(User.username == username).one()
            token = mint_service_session(db, user.id, agent_session_id=self.session_id)
        self.client.headers["Authorization"] = f"Bearer {token}"

    def as_person(self) -> None:
        self.client.headers["Authorization"] = self.login_token

    def sequence(self) -> str:
        self.as_person()
        project = self.client.post(
            "/api/projects", json={"workspace_id": self.workspace_id, "name": "P"}
        ).json()
        return self.client.post(
            "/api/sequences",
            json={"workspace_id": self.workspace_id, "project_id": project["id"], "name": "S"},
        ).json()["id"]

    def card(self, tool: str, payload: dict) -> dict:
        response = self.client.post(
            "/api/confirmations",
            json={"workspace_id": self.workspace_id, "tool": tool, "payload": payload},
        )
        assert response.status_code == 200, response.text
        wait_for_idle_autopilot()
        with SessionLocal() as db:
            row = db.get(ToolConfirmation, response.json()["id"])
            return {
                "id": row.id,
                "status": row.status,
                "permission": row.permission,
                "decision_mode": row.decision_mode,
                "decided_by": row.decided_by,
                "error": row.error,
            }

    def edit_card(self) -> dict:
        return self.card(
            "edit_timeline",
            {"sequence_id": self._sequence, "operations": [{"kind": "add_track", "track_kind": "video"}]},
        )

    def prepare_timeline(self) -> None:
        self._sequence = self.sequence()


def _chat(mode: str | None = None) -> Chat:
    chat = Chat()
    chat.prepare_timeline()
    if mode:
        chat.set_mode(mode)
    chat.as_turn()
    return chat


# ---------------- 默认:什么都不变 ----------------


def test_manual_is_the_default() -> None:
    chat = _chat()
    card = chat.edit_card()
    assert card["status"] == "pending"
    assert card["decision_mode"] == "manual"


# ---------------- auto ----------------


def test_auto_lets_undoable_edits_through() -> None:
    chat = _chat("auto")
    card = chat.edit_card()
    assert card["status"] == "executed", card
    assert card["decision_mode"] == "auto"
    assert card["decided_by"] == chat.user_id()


def test_auto_still_asks_for_external() -> None:
    """撤不回来的那一档,auto 不放行 —— 规则与判断者是第 4 期。"""
    chat = _chat("auto")
    card = chat.card("run_code", {"code": "output = 1", "inputs": {}})
    assert card["permission"] == "external"
    assert card["status"] == "pending"


def test_auto_stops_after_a_run_of_billable_calls() -> None:
    """花钱这一档放行,但不能无人值守地连开 —— 上限之后要重新问一次。"""
    chat = _chat("auto")
    for index in range(COST_AUTO_LIMIT):
        card = chat.card("generate_image", {"prompt": f"p{index}"})
        assert card["status"] in ("executed", "failed"), card  # 没配供应商时执行会失败,但确实放行了
        assert card["decision_mode"] == "auto"
    blocked = chat.card("generate_image", {"prompt": "再来一张"})
    assert blocked["status"] == "pending", "计费卡连开到上限之后没有停下来"


def test_a_human_decision_resets_the_run() -> None:
    chat = _chat("auto")
    for index in range(COST_AUTO_LIMIT):
        chat.card("generate_image", {"prompt": f"p{index}"})
    blocked = chat.card("generate_image", {"prompt": "停一下"})
    assert blocked["status"] == "pending"

    chat.as_person()
    chat.client.post(f"/api/confirmations/{blocked['id']}/approve")
    chat.as_turn()

    assert chat.card("generate_image", {"prompt": "继续"})["decision_mode"] == "auto"


# ---------------- bypass ----------------


def test_bypass_lets_external_through() -> None:
    chat = _chat("bypass")
    card = chat.card("http_request", {"url": "https://127.0.0.1:9/none", "method": "POST"})
    assert card["permission"] == "external"
    assert card["status"] in ("executed", "failed"), card  # 连不上是执行结果,不是"没放行"
    assert card["decision_mode"] == "bypass"


def test_bypass_does_not_bypass_authorisation() -> None:
    """bypass 绕过的是**同意**,不是权限。

    此前这条用 editor + code 节点来证(editor 不是部署管理员,存不下 code 节点)。那道闸随隔离
    执行器一起撤掉了(ADR 0008 D2),于是换成一条更基本、也更贴近真实事故的:**人被移出工作区
    之后,他手里那个开着 bypass 的会话不该还能替这个工作区做决定**。会话是长命的,成员关系不是。
    """
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{workspace['id']}/invitations", json={"username": "mate", "role": "editor"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")

    session_id = mate.post(
        "/api/agent/sessions", json={"workspace_id": workspace["id"], "title": "T"}
    ).json()["id"]
    # viewer 开不了 bypass(要 admin),所以直接写库模拟"他有办法开到" —— 测的是闸,不是入口。
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "mate").one()
        session = db.get(AgentSession, session_id)
        session.permission_mode = "bypass"
        session.mode_set_by = user.id
        db.commit()
        token = mint_service_session(db, user.id, agent_session_id=session_id)
    workflow = mate.post(
        "/api/workflows",
        json={"workspace_id": workspace["id"], "name": "WF", "graph": {"nodes": [START], "edges": []}},
    ).json()

    # 他离开了这个工作区 —— 而会话与令牌都还在。
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "mate").one()
        from app.domain import members as members_svc

        members_svc.remove_member(db, workspace["id"], user.id)

    mate.headers["Authorization"] = f"Bearer {token}"
    made = mate.post(
        "/api/confirmations",
        json={
            "workspace_id": workspace["id"],
            "tool": "edit_workflow",
            "payload": {
                "workflow_id": workflow["id"],
                "operations": [{"kind": "add_node", "type": "code", "config": {"code": "output = 1"}}],
            },
        },
    )
    wait_for_idle_autopilot()

    assert made.status_code in (403, 404), f"bypass 把授权校验一起绕过去了:{made.text}"
    with SessionLocal() as db:
        graph = db.get(Workflow, workflow["id"]).graph
    assert [node["type"] for node in graph["nodes"]] == ["start"], "图被一个已经不在这个工作区的人改了"


# ---------------- 作用域 ----------------


def test_a_card_without_a_session_is_never_automatic() -> None:
    """MCP 直连、飞书外部智能体的卡没有会话可挂模式 —— 继承任何默认都是授权范围逃逸。"""
    chat = _chat("bypass")
    chat.as_person()  # 登录令牌 = 没有会话归属
    card = chat.edit_card()
    assert card["status"] == "pending"


def test_the_mode_only_applies_to_whoever_set_it() -> None:
    """飞书群聊共用一个会话 —— A 开的 bypass 不能替 B 做决定。"""
    chat = _chat("bypass")
    owner_client = chat.client
    owner_client.headers["Authorization"] = chat.login_token
    mate = second_client("mate")
    owner_client.post(
        f"/api/workspaces/{chat.workspace_id}/invitations", json={"username": "mate", "role": "editor"}
    )
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")

    with SessionLocal() as db:
        other = db.query(User).filter(User.username == "mate").one()
        token = mint_service_session(db, other.id, agent_session_id=chat.session_id)
    mate.headers["Authorization"] = f"Bearer {token}"
    card = mate.post(
        "/api/confirmations",
        json={
            "workspace_id": chat.workspace_id,
            "tool": "edit_timeline",
            "payload": {"sequence_id": chat._sequence, "operations": [{"kind": "add_track", "track_kind": "video"}]},
        },
    ).json()
    wait_for_idle_autopilot()

    with SessionLocal() as db:
        assert db.get(ToolConfirmation, card["id"]).status == "pending"


# ---------------- 「本会话始终允许」 ----------------


def test_session_allow_list_is_server_side_and_recorded_as_such() -> None:
    """它此前是浏览器 localStorage 里的一份自动批准 —— 聊天面板一关就没了,而 turn 还在跑。"""
    chat = _chat()
    chat.as_person()
    chat.client.patch(
        f"/api/agent/sessions/{chat.session_id}", json={"auto_allow_tools": ["edit_timeline"]}
    )
    chat.as_turn()

    card = chat.edit_card()
    assert card["status"] == "executed", card
    assert card["decision_mode"] == "session-allow", "白名单放行不该和模式放行混为一谈"


# ---------------- 入口权限 ----------------


def test_switching_to_bypass_requires_admin() -> None:
    owner = fresh_client()
    workspace = owner.post("/api/workspaces", json={"name": "W"}).json()
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{workspace['id']}/invitations", json={"username": "mate", "role": "editor"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")
    session_id = mate.post(
        "/api/agent/sessions", json={"workspace_id": workspace["id"], "title": "T"}
    ).json()["id"]

    assert mate.patch(f"/api/agent/sessions/{session_id}", json={"permission_mode": "auto"}).status_code == 200
    denied = mate.patch(f"/api/agent/sessions/{session_id}", json={"permission_mode": "bypass"})
    assert denied.status_code == 403, denied.text


def test_an_unknown_mode_is_refused() -> None:
    chat = Chat()
    chat.set_mode("whatever", expect=422)


def test_the_agent_has_no_tool_to_change_the_mode() -> None:
    """模式是用户的**授权动作** —— 被授权的一方不该能改它。

    判据是"有没有工具能写到会话的模式字段上",不是名字里带不带 mode(list_generation_models
    也带)。会话的可写字段只有 PATCH 那一条路,而它不在工具面里。
    """
    client = fresh_client()
    names = {spec["name"] for spec in client.get("/api/agent/tools").json()}
    assert not [name for name in names if "permission_mode" in name or name.endswith("_mode")]
    assert "update_session" not in names and "set_permission_mode" not in names
