"""生成会话的分组:和对话同一张表、同一组接口,但**两边各自一套**。

分组表原本叫 agent_session_groups,只装对话分组。生成栏要有同样的能力时有两条路:
再建一张表(两份一模一样的建/改名/删/拖放),或者把这张表提升成通用的、用 kind 分开。
选了后者,于是这里钉的就是「kind 真的把两边隔开了」——
它一旦失效,现象是「对话里建的分组跑到生成栏里空着站着」,而不是报错。
"""

from __future__ import annotations

from tests.util import fresh_client


def _group(client, workspace_id: str, kind: str, name: str) -> dict:
    return client.post(
        "/api/session-groups", json={"workspace_id": workspace_id, "kind": kind, "name": name}
    ).json()


def _gen_session(client, workspace_id: str) -> str:
    return client.post("/api/generation/sessions", json={"workspace_id": workspace_id}).json()["id"]


def _read(client, workspace_id: str, session_id: str) -> dict | None:
    """生成会话没有单条 GET(本来就没有),从列表里挑。"""
    listed = client.get(f"/api/generation/sessions?workspace_id={workspace_id}").json()
    return next((s for s in listed if s["id"] == session_id), None)


def test_两边的分组互不出现() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    _group(client, ws["id"], "agent", "对话的组")
    _group(client, ws["id"], "generation", "生成的组")

    agent = client.get(f"/api/session-groups?workspace_id={ws['id']}&kind=agent").json()
    generation = client.get(f"/api/session-groups?workspace_id={ws['id']}&kind=generation").json()
    assert [g["name"] for g in agent] == ["对话的组"]
    assert [g["name"] for g in generation] == ["生成的组"]


def test_生成会话不能塞进对话的分组() -> None:
    """少了 kind 这条校验,它会落进一个自己那一侧永远列不出来的分组里 —— 从此不见。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    chat_group = _group(client, ws["id"], "agent", "对话的组")
    sid = _gen_session(client, ws["id"])

    assert client.patch(f"/api/generation/sessions/{sid}", json={"group_id": chat_group["id"]}).status_code == 404
    assert _read(client, ws["id"], sid)["group_id"] is None


def test_对话不能塞进生成的分组() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    gen_group = _group(client, ws["id"], "generation", "生成的组")
    sid = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()["id"]

    assert client.patch(f"/api/agent/sessions/{sid}", json={"group_id": gen_group["id"]}).status_code == 404


def test_删生成分组不删会话_成员退回未分组() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    group = _group(client, ws["id"], "generation", "客户 A")
    sid = _gen_session(client, ws["id"])
    client.patch(f"/api/generation/sessions/{sid}", json={"group_id": group["id"]})
    assert _read(client, ws["id"], sid)["group_id"] == group["id"]

    assert client.delete(f"/api/session-groups/{group['id']}").status_code == 204

    session = _read(client, ws["id"], sid)
    assert session["id"] == sid, "生成会话被分组带走了"
    assert session["group_id"] is None, "会话还挂在一个已经不存在的分组上"


def test_删对话分组不碰生成会话() -> None:
    """delete_group 按 kind 挑该清空哪张表。挑错的话,它会去清另一张表的同名列。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    gen_group = _group(client, ws["id"], "generation", "生成的组")
    chat_group = _group(client, ws["id"], "agent", "对话的组")
    sid = _gen_session(client, ws["id"])
    client.patch(f"/api/generation/sessions/{sid}", json={"group_id": gen_group["id"]})

    client.delete(f"/api/session-groups/{chat_group['id']}")

    assert _read(client, ws["id"], sid)["group_id"] == gen_group["id"], (
        "删对话分组把生成会话也踢出组了"
    )


def test_空串把生成会话移出分组() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    group = _group(client, ws["id"], "generation", "归档")
    sid = _gen_session(client, ws["id"])
    client.patch(f"/api/generation/sessions/{sid}", json={"group_id": group["id"]})

    client.patch(f"/api/generation/sessions/{sid}", json={"group_id": ""})
    assert _read(client, ws["id"], sid)["group_id"] is None

    # 对照:不传 group_id 的更新不该动分组
    client.patch(f"/api/generation/sessions/{sid}", json={"group_id": group["id"]})
    client.patch(f"/api/generation/sessions/{sid}", json={"title": "改个名"})
    assert _read(client, ws["id"], sid)["group_id"] == group["id"]


def test_换分组不把生成会话顶成刚生成过() -> None:
    """和对话同一条:收纳不是活动。列表按 updated_at 倒序,整理一次不该把顺序搅了。"""
    from app.core.db import SessionLocal
    from app.db.models import GenerationSession

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    group = _group(client, ws["id"], "generation", "客户 A")
    sid = _gen_session(client, ws["id"])
    client.patch(f"/api/generation/sessions/{sid}", json={"title": "生成过了"})

    with SessionLocal() as db:
        before = db.get(GenerationSession, sid).updated_at

    client.patch(f"/api/generation/sessions/{sid}", json={"group_id": group["id"]})

    with SessionLocal() as db:
        after = db.get(GenerationSession, sid).updated_at
    assert after == before, "收进分组就把 updated_at 顶成了现在 —— 会话会显得刚生成过"
