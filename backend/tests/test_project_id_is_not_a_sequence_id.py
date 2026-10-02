"""把项目 id 当成时间线 id 时,报错直接说「这是项目 xxx 的 id」和它的时间线是哪几条。

用户会话(Kimi · k3):edit_timeline 拿项目 id 当 sequence_id,只拿到「Sequence not found in this workspace」,
重试了六次 —— 那句话没告诉它错在哪,它只能猜是时间线被删了、还是工作区不对。项目 id 和时间线 id 长得一样
(都是 32 位十六进制),list_projects 又把两者摆在同一行里,拿错是很自然的事。

走真实入口:智能体经 /api/agent/tools 调 edit_timeline(开卡前的校验就是那句话的出处)。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import User
from tests.util import fresh_client

OPS = [{"op": "add_track", "kind": "video"}]


def _turn():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    sid = client.post("/api/agent/sessions", json={"workspace_id": ws, "title": "T"}).json()["id"]
    with SessionLocal() as db:
        me = db.query(User).filter(User.username == "tester").one()
        token = mint_service_session(db, me.id, agent_session_id=sid)
    return client, ws, {"Authorization": f"Bearer {token}"}


def _edit(client, headers, ws: str, sequence_id: str) -> str:
    response = client.post(
        "/api/agent/tools/edit_timeline",
        json={"arguments": {"sequence_id": sequence_id, "operations": OPS, "workspace_id": ws}},
        headers=headers,
    )
    body = response.json()
    assert "result" not in body, f"拿项目 id 也开出了卡:{body}"
    return str(body.get("error") or body.get("detail"))


def test_项目id当时间线id_报错说这是哪个项目_它的时间线是哪几条() -> None:
    client, ws, headers = _turn()
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "宣传片"}).json()["id"]
    timeline = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "主序列"}).json()["id"]

    said = _edit(client, headers, ws, project)

    assert "宣传片" in said and "项目" in said, f"没说这是项目的 id:{said}"
    assert timeline in said and "主序列" in said, f"没给出它的时间线:{said}"


def test_项目还没有时间线_报错指路去建() -> None:
    client, ws, headers = _turn()
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "空项目"}).json()["id"]

    said = _edit(client, headers, ws, project)

    assert "空项目" in said and "create_project" in said, f"没说怎么建:{said}"


def test_真不存在的id_照旧说找不到() -> None:
    client, ws, headers = _turn()
    said = _edit(client, headers, ws, "no-such-thing")
    assert "not found" in said.lower() or "找不到" in said
