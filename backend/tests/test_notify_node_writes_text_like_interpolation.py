"""「通知」节点的标题、正文当文字用,和插值同一种写法(as_text);通知里带着是哪一次运行。

## 现场

整格引用一个对象 / 布尔时,通知节点 `str()` 了它:正文是 Python 的 `{'ok': True, 'n': None}`、标题是 `True`
—— 和同一个值插进别的文字里(`{"ok": true, "n": null}`、`true`)不一样。通知也只指回工作流,看不出是哪一次跑的。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Notification
from tests.util import fresh_client, wait_status


def test_通知节点整格引用对象和布尔_写成JSON文字_载荷带着这一次运行() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    workflow = client.post("/api/workflows", json={"workspace_id": ws, "name": "通知", "graph": {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "n", "type": "notify", "config": {"title": "{{start.flag}}", "body": "{{start.result}}"}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "n"}],
    }}).json()
    started = client.post(f"/api/workflows/{workflow['id']}/run",
                          json={"params": {"flag": True, "result": {"ok": True, "n": None, "名": "值"}}}).json()
    assert wait_status(client, started["id"]) == "succeeded"
    with SessionLocal() as db:
        notice = db.query(Notification).filter(Notification.workspace_id == ws).one()
    assert notice.title == "true"
    assert notice.body == '{"ok": true, "n": null, "名": "值"}'
    assert notice.payload == {"workflow_id": workflow["id"], "job_id": started["id"]}
