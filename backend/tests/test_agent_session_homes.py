"""对话记住在哪开的(ADR 0044 §2):建会话必须带家、按家列、出参的家和名字(按看的人查)、消息的 `place`、
ComfyUI 的家跟着挪、`open_view` 认工作流、死掉的三条工作流会话路由没了。
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import AgentSession, Note, now
from app.domain.agent.prompt import build_system_prompt
from tests.fake_comfyui import FakeComfyUI, comfyui_grants
from tests.util import fresh_client, second_client

STUDIO = {"kind": "studio"}
COMFY_PACKAGE = "dev.mosael.comfyui"
COMFY_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "comfyui" / "agent"


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _note(client, workspace: str, title: str = "宣传片周报") -> str:
    return client.post("/api/notes", json={"workspace_id": workspace, "title": title, "markdown": "正文"}).json()["id"]


def _session(client, workspace: str, home: dict, **fields) -> dict:
    created = client.post("/api/agent/sessions", json={"workspace_id": workspace, "home": home, **fields})
    assert created.status_code == 200, created.text
    return created.json()


def _team():
    owner = fresh_client()
    workspace = _workspace(owner)
    mate = second_client("mate")
    owner.post(f"/api/workspaces/{workspace}/invitations", json={"username": "mate", "role": "editor"})
    invitation = mate.get("/api/invitations").json()["invitations"][0]
    mate.post(f"/api/invitations/{invitation['id']}/accept")
    return owner, workspace, mate


def _connect_comfy(client, comfy: FakeComfyUI) -> str:
    created = client.post(f"/api/plugins/{COMFY_PACKAGE}/instances", json={"config": {"server_url": comfy.url}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
    client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True})
    return instance_id


@pytest.fixture
def comfy():
    with FakeComfyUI() as fake:
        fake.state.object_info = json.loads((COMFY_FIXTURES / "object_info.json").read_text(encoding="utf-8"))
        yield fake


# ---------- 建 ----------


def test_不带家不让建_没有缺省当_AI_Studio_这条路() -> None:
    client = fresh_client()
    workspace = _workspace(client)
    assert client.post("/api/agent/sessions", json={"workspace_id": workspace}).status_code == 422


def test_家在一篇笔记里_出参带着家和现查的名字() -> None:
    client = fresh_client()
    workspace = _workspace(client)
    note = _note(client, workspace)
    session = _session(client, workspace, {"kind": "note", "id": note})
    assert (session["home_kind"], session["home_id"], session["home_name"], session["home_state"]) == (
        "note", note, "宣传片周报", "ok")
    studio = _session(client, workspace, STUDIO)
    assert (studio["home_kind"], studio["home_id"], studio["home_state"]) == ("studio", "", "ok")


@pytest.mark.parametrize("home", [
    {"kind": "studio", "id": "x"},
    {"kind": "comfyui", "id": "conn/../secret.json"},
    {"kind": "comfyui", "id": "conn/"},
    {"kind": "comfyui", "id": "conn#"},
    {"kind": "note", "id": ""},
    {"kind": "notebook", "id": "n1"},
])
def test_形状不对的家是_422(home: dict) -> None:
    client = fresh_client()
    workspace = _workspace(client)
    assert client.post("/api/agent/sessions", json={"workspace_id": workspace, "home": home}).status_code == 422


def test_家是看不见的东西_404_别的工作区的笔记和不存在的同一个回答() -> None:
    client = fresh_client()
    workspace = _workspace(client)
    elsewhere = _note(client, _workspace(client))
    for home in ({"kind": "note", "id": elsewhere}, {"kind": "board", "id": "no-such-board"}):
        assert client.post("/api/agent/sessions", json={"workspace_id": workspace, "home": home}).status_code == 404


def test_ComfyUI_的连接不是他的_422(comfy) -> None:
    owner, workspace, mate = _team()
    connection = _connect_comfy(owner, comfy)
    home = {"kind": "comfyui", "id": f"{connection}/portraits/qwen.json"}
    assert _session(owner, workspace, home)["home_name"] == "qwen"
    refused = mate.post("/api/agent/sessions", json={"workspace_id": workspace, "home": home})
    assert refused.status_code == 422, "别人的连接"
    gone = owner.post("/api/agent/sessions", json={"workspace_id": workspace, "home": {"kind": "comfyui", "id": "nope"}})
    assert gone.status_code == 422


# ---------- 列 ----------


def test_按家列_只列家在这里的_掉出前_50_的老对话也列得出() -> None:
    client = fresh_client()
    workspace = _workspace(client)
    note = _note(client, workspace)
    old = _session(client, workspace, {"kind": "note", "id": note})["id"]
    with SessionLocal() as db:
        db.get(AgentSession, old).updated_at = now() - timedelta(days=21)
        db.commit()
    for _ in range(50):
        _session(client, workspace, STUDIO)

    everything = client.get(f"/api/agent/sessions?workspace_id={workspace}").json()
    assert len(everything) == 50 and old not in {one["id"] for one in everything}, "全工作区只给最近 50 条"
    here = client.get(f"/api/agent/sessions?workspace_id={workspace}&home_kind=note&home_id={note}").json()
    assert [one["id"] for one in here] == [old]
    studio = client.get(f"/api/agent/sessions?workspace_id={workspace}&home_kind=studio").json()
    assert len(studio) == 50 and old not in {one["id"] for one in studio}
    assert client.get(f"/api/agent/sessions?workspace_id={workspace}&home_kind=notebook").status_code == 422


# ---------- 家的名字:按看的人查 ----------


def test_回收站里的笔记算还在_删了的写已删除_名字不给() -> None:
    client = fresh_client()
    workspace = _workspace(client)
    note = _note(client, workspace)
    session = _session(client, workspace, {"kind": "note", "id": note})["id"]
    with SessionLocal() as db:
        db.get(Note, note).trashed = True
        db.commit()
    assert client.get(f"/api/agent/sessions/{session}").json()["home_state"] == "ok"
    with SessionLocal() as db:
        db.delete(db.get(Note, note))
        db.commit()
    detail = client.get(f"/api/agent/sessions/{session}").json()
    assert (detail["home_state"], detail["home_name"]) == ("deleted", "")
    listed = client.get(f"/api/agent/sessions?workspace_id={workspace}").json()
    assert [(one["home_state"], one["home_name"]) for one in listed] == [("deleted", "")], "对话照常在"


def test_同事共享来的对话_家他看不见_只说是一篇笔记_标题不出现在响应里(comfy) -> None:
    owner, workspace, mate = _team()
    connection = _connect_comfy(owner, comfy)
    comfy_home = _session(owner, workspace, {"kind": "comfyui", "id": f"{connection}/客户机密方案.json"})["id"]
    owner.post(f"/api/shares/agent_session/{comfy_home}", json={"workspace_id": workspace})
    # 家是一篇他所在工作区以外的笔记(只能直接写库造出来 —— 接口建会话时就拒了)。
    secret_workspace = _workspace(owner)
    secret_note = _note(owner, secret_workspace, title="绝密笔记")
    in_note = _session(owner, workspace, STUDIO)["id"]
    with SessionLocal() as db:
        row = db.get(AgentSession, in_note)
        row.home_kind, row.home_id = "note", secret_note
        db.commit()
    owner.post(f"/api/shares/agent_session/{in_note}", json={"workspace_id": workspace})

    seen = mate.get(f"/api/agent/sessions?workspace_id={workspace}")
    by_id = {one["id"]: one for one in seen.json()}
    assert (by_id[comfy_home]["home_state"], by_id[comfy_home]["home_name"]) == ("hidden", "")
    assert (by_id[in_note]["home_state"], by_id[in_note]["home_name"]) == ("hidden", "")
    assert "客户机密方案" not in seen.text and "绝密笔记" not in seen.text
    assert "绝密笔记" not in mate.get(f"/api/agent/sessions/{in_note}").text
    mine = {one["id"]: one for one in owner.get(f"/api/agent/sessions?workspace_id={workspace}").json()}
    assert mine[comfy_home]["home_name"] == "客户机密方案", "主人自己看得见"


# ---------- 家跟着挪 ----------


def test_家跟着挪_只收_ComfyUI_只挪自己的_不顶到最前(comfy) -> None:
    owner, workspace, mate = _team()
    connection = _connect_comfy(owner, comfy)
    unsaved = f"{connection}#workflows/Unsaved Workflow (2).json"
    mine = _session(owner, workspace, {"kind": "comfyui", "id": unsaved})
    assert mine["home_name"] == "Unsaved Workflow (2)"
    #: 同一台连接在另一个工作区里也用着:文件换了地方,那边家在它上面的也跟着挪
    elsewhere = _workspace(owner)
    there = _session(owner, elsewhere, {"kind": "comfyui", "id": unsaved})
    untouched = _session(owner, workspace, {"kind": "comfyui", "id": f"{connection}#workflows/Unsaved Workflow (3).json"})
    #: 同事的对话哪怕家写着同一处(界面建不出来,直接写库),也不归他挪
    theirs_row = _session(mate, workspace, STUDIO)
    with SessionLocal() as db:
        row = db.get(AgentSession, theirs_row["id"])
        row.home_kind, row.home_id = "comfyui", unsaved
        db.commit()
    saved = f"{connection}/人像/qwen 编辑.json"

    moved = owner.post("/api/agent/homes/move", json={"workspace_id": workspace, "kind": "comfyui", "from_id": unsaved, "to_id": saved})
    assert moved.status_code == 200 and moved.json() == {"moved": 2}
    after = owner.get(f"/api/agent/sessions/{mine['id']}").json()
    assert (after["home_id"], after["home_name"]) == (saved, "qwen 编辑")
    assert after["updated_at"] == mine["updated_at"], "挪家不算对话里有动静"
    assert owner.get(f"/api/agent/sessions/{there['id']}").json()["home_id"] == saved
    assert owner.get(f"/api/agent/sessions/{untouched['id']}").json()["home_id"] == untouched["home_id"]
    with SessionLocal() as db:
        assert db.get(AgentSession, theirs_row["id"]).home_id == unsaved, "只挪他自己的"

    note = _note(owner, workspace)
    wrong = owner.post("/api/agent/homes/move", json={"workspace_id": workspace, "kind": "note", "from_id": note, "to_id": note})
    assert wrong.status_code == 422, "Mosael 自家的东西按 id 认,永远不用挪"
    theirs = mate.post("/api/agent/homes/move", json={"workspace_id": workspace, "kind": "comfyui", "from_id": saved, "to_id": unsaved})
    assert theirs.status_code == 422, "连接不是他的"
    assert owner.get(f"/api/agent/sessions/{mine['id']}").json()["home_id"] == saved


# ---------- 消息的 place ----------


def test_消息带着在哪说的_落进_payload_形状不对是_422(monkeypatch) -> None:
    from app.ai.sidecar.pi_client import TurnResult
    from app.domain.agent import host
    from tests.test_agent_host import _configured

    monkeypatch.setattr(host, "run_turn", lambda adapter, *, prompt, **_: TurnResult(text="好"))
    client = fresh_client()
    _configured(client)
    workspace = _workspace(client)
    note = _note(client, workspace)
    session = _session(client, workspace, STUDIO)["id"]
    place = {"kind": "note", "id": note}
    sent = client.post(f"/api/agent/sessions/{session}/messages", json={"content": "看看这篇", "place": place})
    assert sent.status_code == 200, sent.text
    assert host.wait_for_idle_turns()
    assert sent.json()["payload"]["place"] == place
    assert client.get(f"/api/agent/sessions/{session}").json()["home_kind"] == "studio", "在别处接着聊,家不变"
    bad = client.post(f"/api/agent/sessions/{session}/messages", json={"content": "x", "place": {"kind": "studio", "id": "x"}})
    assert bad.status_code == 422


# ---------- 记忆跟着家 ----------


def test_剪辑里开的对话带上那个项目的记忆_别处的不带() -> None:
    client = fresh_client()
    workspace = _workspace(client)
    project = client.post("/api/projects", json={"workspace_id": workspace, "name": "宣传片"}).json()["id"]
    client.post("/api/agent/memories", json={"workspace_id": workspace, "project_id": project, "content": "片头用 brand-intro.mp4"})
    in_project = _session(client, workspace, {"kind": "project", "id": project})["id"]
    elsewhere = _session(client, workspace, STUDIO)["id"]
    with SessionLocal() as db:
        assert "brand-intro.mp4" in build_system_prompt(db, db.get(AgentSession, in_project))
        assert "brand-intro.mp4" not in build_system_prompt(db, db.get(AgentSession, elsewhere))


# ---------- open_view 认工作流、死路由 ----------


def test_open_view_带工作流的_id_记下什么时候要求的_清掉时一起清() -> None:
    from app.core.security import mint_service_session
    from tests.util import user_id

    client = fresh_client()
    workspace = _workspace(client)
    workflow = client.post("/api/workflows", json={"workspace_id": workspace, "name": "出海流程"}).json()["id"]
    session = _session(client, workspace, STUDIO)["id"]
    with SessionLocal() as db:
        token = mint_service_session(db, user_id(), agent_session_id=session)
        db.commit()
    answer = client.post("/api/agent/tools/open_view", json={"arguments": {"view": "workflows", "id": workflow}},
                         headers={"Authorization": f"Bearer {token}"})
    assert answer.status_code == 200, answer.text
    detail = client.get(f"/api/agent/sessions/{session}").json()
    assert detail["pending_view"] == f"workflows:{workflow}" and detail["pending_view_at"]
    client.delete(f"/api/agent/sessions/{session}/view")
    detail = client.get(f"/api/agent/sessions/{session}").json()
    assert (detail["pending_view"], detail["pending_view_at"]) == ("", None)


def test_工作流的三条会话路由没了() -> None:
    client = fresh_client()
    workspace = _workspace(client)
    workflow = client.post("/api/workflows", json={"workspace_id": workspace, "name": "WF"}).json()["id"]
    assert client.post(f"/api/workflows/{workflow}/agent-session").status_code in (404, 405)
    assert client.post(f"/api/workflows/{workflow}/agent-sessions").status_code in (404, 405)
    assert client.get(f"/api/workflows/{workflow}/agent-sessions").status_code in (404, 405)


def test_list_agent_sessions_工具说得出每段是在哪开的() -> None:
    client = fresh_client()
    workspace = _workspace(client)
    note = _note(client, workspace)
    _session(client, workspace, {"kind": "note", "id": note})
    _session(client, workspace, STUDIO)
    listed = client.post("/api/agent/tools/list_agent_sessions", json={"arguments": {"workspace_id": workspace}}).json()["result"]
    assert sorted(one["where"] for one in listed) == ["在 AI Studio 里开的", "在笔记《宣传片周报》里开的"]


# ---------- 草稿上选好的设置(维护者 2026-10-07:第一句话发出去才建会话) ----------


def test_草稿上选好的设置建会话时一起带上_哪一项不合规整个不建() -> None:
    client = fresh_client()
    workspace = _workspace(client)
    created = _session(client, workspace, STUDIO, thinking_level="high", analysis_video_mode="frames", permission_mode="auto")
    assert (created["thinking_level"], created["analysis_video_mode"], created["permission_mode"]) == ("high", "frames", "auto")

    refused = client.post("/api/agent/sessions", json={"workspace_id": workspace, "home": STUDIO, "thinking_level": "max"})
    assert refused.status_code == 422
    listed = client.get(f"/api/agent/sessions?workspace_id={workspace}").json()
    assert [one["id"] for one in listed] == [created["id"]], "不合规的那一次一行都没留下"
