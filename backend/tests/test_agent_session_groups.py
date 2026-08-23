"""会话分组:收纳方式,不是所有权。

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
    group = client.post("/api/agent/session-groups", json={"workspace_id": ws["id"], "name": "客户 A"}).json()
    sid = _session(client, ws["id"])
    client.patch(f"/api/agent/sessions/{sid}", json={"group_id": group["id"]})
    assert client.get(f"/api/agent/sessions/{sid}").json()["group_id"] == group["id"]

    assert client.delete(f"/api/agent/session-groups/{group['id']}").status_code == 204

    session = client.get(f"/api/agent/sessions/{sid}").json()
    assert session["id"] == sid, "对话被分组带走了"
    assert session["group_id"] is None, "对话还挂在一个已经不存在的分组上"
    assert client.get(f"/api/agent/session-groups?workspace_id={ws['id']}").json() == []


def test_空串把对话移出分组() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    group = client.post("/api/agent/session-groups", json={"workspace_id": ws["id"], "name": "归档"}).json()
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
    foreign = client.post("/api/agent/session-groups", json={"workspace_id": other["id"], "name": "别人的"}).json()
    sid = _session(client, mine["id"])

    assert client.patch(f"/api/agent/sessions/{sid}", json={"group_id": foreign["id"]}).status_code == 404
    assert client.get(f"/api/agent/sessions/{sid}").json()["group_id"] is None


def test_改名是一次操作_不必挨个改成员() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    group = client.post("/api/agent/session-groups", json={"workspace_id": ws["id"], "name": "旧名"}).json()
    sids = [_session(client, ws["id"]) for _ in range(3)]
    for sid in sids:
        client.patch(f"/api/agent/sessions/{sid}", json={"group_id": group["id"]})

    client.patch(f"/api/agent/session-groups/{group['id']}", json={"name": "新名"})

    groups = client.get(f"/api/agent/session-groups?workspace_id={ws['id']}").json()
    assert [g["name"] for g in groups] == ["新名"]
    for sid in sids:
        assert client.get(f"/api/agent/sessions/{sid}").json()["group_id"] == group["id"]


def test_拖放落库_顺序生效而updated_at不被顶掉() -> None:
    """拖动是整理,不是活动。

    让 updated_at 跟着涨的话,被拖过的对话会显得"刚聊过" —— 而"最近更新"正是没排过的那些人
    赖以排序的东西(默认顺序就是它),整理一次就把别人的顺序搅了。
    """
    from app.core.db import SessionLocal
    from app.db.models import AgentSession

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    ids = [_session(client, ws["id"]) for _ in range(3)]
    for index, sid in enumerate(ids):
        client.patch(f"/api/agent/sessions/{sid}", json={"title": f"第{index}个"})

    with SessionLocal() as db:
        before = {s.id: s.updated_at for s in db.query(AgentSession).filter(AgentSession.id.in_(ids))}

    # 倒过来排
    reversed_ids = list(reversed(ids))
    assert client.post(
        "/api/agent/sessions/reorder",
        json={"workspace_id": ws["id"], "group_id": "", "ordered_ids": reversed_ids},
    ).json() == {"ordered": 3}

    listed = [s["id"] for s in client.get(f"/api/agent/sessions?workspace_id={ws['id']}").json()]
    assert listed == reversed_ids, "拖出来的顺序没生效"

    with SessionLocal() as db:
        after = {s.id: s.updated_at for s in db.query(AgentSession).filter(AgentSession.id.in_(ids))}
    assert after == before, "拖一下就把 updated_at 顶成了现在 —— 对话会显得刚聊过"


def test_没排过的时候就是最近更新在前() -> None:
    """默认顺序不变:sort_order 全是 0,退化成纯粹的 updated_at desc。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    first = _session(client, ws["id"])
    second = _session(client, ws["id"])
    # 动一下第一个,它就该回到最前
    client.patch(f"/api/agent/sessions/{first}", json={"title": "刚改过"})

    listed = [s["id"] for s in client.get(f"/api/agent/sessions?workspace_id={ws['id']}").json()]
    assert listed[0] == first, f"默认排序不是最近更新在前:{listed}"
    assert second in listed
