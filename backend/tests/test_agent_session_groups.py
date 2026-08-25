"""对话分组:收纳方式,不是所有权。

(分组表两边共用,生成那一侧另见 test_generation_session_groups.py。)

钉住三件容易做错的事:
  · 删分组**不删对话** —— 它们退回未分组。删一个文件夹不该连着删掉里面的东西;
  · 移出分组要能表达 —— 这套 schema 用 None 表示"这次没改",所以"改成没有"走空串;
  · 不能把对话塞进**别的工作区**的分组里 —— 分组按工作区列出,那条对话会两边都不着落。
"""

from __future__ import annotations

from tests.util import fresh_client


def _session(client, workspace_id: str) -> str:
    return client.post("/api/agent/sessions", json={"workspace_id": workspace_id}).json()["id"]


def test_删分组不删对话_成员退回未分组() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    group = client.post("/api/session-groups", json={"workspace_id": ws["id"], "kind": "agent", "name": "客户 A"}).json()
    sid = _session(client, ws["id"])
    client.patch(f"/api/agent/sessions/{sid}", json={"group_id": group["id"]})
    assert client.get(f"/api/agent/sessions/{sid}").json()["group_id"] == group["id"]

    assert client.delete(f"/api/session-groups/{group['id']}").status_code == 204

    session = client.get(f"/api/agent/sessions/{sid}").json()
    assert session["id"] == sid, "对话被分组带走了"
    assert session["group_id"] is None, "对话还挂在一个已经不存在的分组上"
    assert client.get(f"/api/session-groups?workspace_id={ws['id']}").json() == []


def test_空串把对话移出分组() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    group = client.post("/api/session-groups", json={"workspace_id": ws["id"], "kind": "agent", "name": "归档"}).json()
    sid = _session(client, ws["id"])
    client.patch(f"/api/agent/sessions/{sid}", json={"group_id": group["id"]})

    client.patch(f"/api/agent/sessions/{sid}", json={"group_id": ""})
    assert client.get(f"/api/agent/sessions/{sid}").json()["group_id"] is None

    # 对照:不传 group_id 的更新不该动分组(None = 这次没改)
    client.patch(f"/api/agent/sessions/{sid}", json={"group_id": group["id"]})
    client.patch(f"/api/agent/sessions/{sid}", json={"title": "改个名"})
    assert client.get(f"/api/agent/sessions/{sid}").json()["group_id"] == group["id"]


def test_不能收进别的工作区的分组() -> None:
    client = fresh_client()
    mine = client.post("/api/workspaces", json={"name": "我的"}).json()
    other = client.post("/api/workspaces", json={"name": "另一个"}).json()
    foreign = client.post("/api/session-groups", json={"workspace_id": other["id"], "kind": "agent", "name": "别人的"}).json()
    sid = _session(client, mine["id"])

    assert client.patch(f"/api/agent/sessions/{sid}", json={"group_id": foreign["id"]}).status_code == 404
    assert client.get(f"/api/agent/sessions/{sid}").json()["group_id"] is None


def test_改名是一次操作_不必挨个改成员() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    group = client.post("/api/session-groups", json={"workspace_id": ws["id"], "kind": "agent", "name": "旧名"}).json()
    sids = [_session(client, ws["id"]) for _ in range(3)]
    for sid in sids:
        client.patch(f"/api/agent/sessions/{sid}", json={"group_id": group["id"]})

    client.patch(f"/api/session-groups/{group['id']}", json={"name": "新名"})

    groups = client.get(f"/api/session-groups?workspace_id={ws['id']}").json()
    assert [g["name"] for g in groups] == ["新名"]
    for sid in sids:
        assert client.get(f"/api/agent/sessions/{sid}").json()["group_id"] == group["id"]


def test_换分组不把对话顶成刚聊过() -> None:
    """拖进分组是整理,不是活动。

    让 updated_at 跟着涨的话,被拖过的对话会显得「刚聊过」—— 而列表就是按最近更新排的,
    整理一次就把顺序搅了。(手动拖排序这个能力已经去掉:组内先后一律由最近更新决定,
    所以这条更要紧了 —— 现在没有任何东西能把被搅乱的顺序再摆回去。)
    """
    from app.core.db import SessionLocal
    from app.db.models import AgentSession

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    group = client.post("/api/session-groups", json={"workspace_id": ws["id"], "kind": "agent", "name": "客户 A"}).json()
    sid = _session(client, ws["id"])
    client.patch(f"/api/agent/sessions/{sid}", json={"title": "聊过了"})

    with SessionLocal() as db:
        before = db.get(AgentSession, sid).updated_at

    client.patch(f"/api/agent/sessions/{sid}", json={"group_id": group["id"]})

    with SessionLocal() as db:
        after = db.get(AgentSession, sid).updated_at
    assert after == before, "收进分组就把 updated_at 顶成了现在 —— 对话会显得刚聊过"


def test_不再有手动排序这个入口() -> None:
    """对话不支持手动拖排序 —— 端点和列都删了,顺序只由最近更新决定。

    钉住它没有以「留着不用」的形式回来:一个还在的端点迟早会被某个地方调上。
    """
    client = fresh_client()
    # 直接查路由表,不去打那个地址 —— `reorder` 会被 /agent/sessions/{session_id} 当成一个
    # session_id 接住,POST 于是回 405 而不是 404,拿状态码判断会把「还在」和「没了」搞混。
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/agent/sessions/reorder" not in paths, "reorder 端点还在路由表里"

    from app.db.models import AgentSession

    assert not hasattr(AgentSession, "sort_order"), "AgentSession 上还留着 sort_order"


def test_顺序就是最近更新在前() -> None:
    """唯一的排序规则:updated_at desc。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    first = _session(client, ws["id"])
    second = _session(client, ws["id"])
    # 动一下第一个,它就该回到最前
    client.patch(f"/api/agent/sessions/{first}", json={"title": "刚改过"})

    listed = [s["id"] for s in client.get(f"/api/agent/sessions?workspace_id={ws['id']}").json()]
    assert listed[0] == first, f"默认排序不是最近更新在前:{listed}"
    assert second in listed
