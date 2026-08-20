"""清空已读只删已读:未读的通知是还没送达的信息,清空不该顺手带走。"""

from __future__ import annotations

from tests.util import fresh_client


def test_清空已读只删已读_未读不动() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    for title in ("旧闻", "新闻"):
        client.post("/api/notifications", json={"workspace_id": ws["id"], "title": title})
    items = client.get(f"/api/notifications?workspace_id={ws['id']}").json()["items"]
    old = next(item for item in items if item["title"] == "旧闻")
    client.post(f"/api/notifications/{old['id']}/read")

    removed = client.delete(f"/api/notifications/read?workspace_id={ws['id']}").json()
    assert removed == {"removed": 1}

    left = client.get(f"/api/notifications?workspace_id={ws['id']}").json()
    assert [item["title"] for item in left["items"]] == ["新闻"], "未读的那条必须还在"
    assert left["unread"] == 1
