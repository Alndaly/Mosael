"""运行产出里的长文字:事件快照截断了,全文另存一份,「本次产出」的复制 / 下载拿得到。

此前事件和 job.result 只存前 2000 字加一个省略号,界面上看不出它被截过,复制到的也是截断版 ——
一段三千字的模型回复,用户以为自己拿到了全部。
"""

from __future__ import annotations

import time

from app.core.db import SessionLocal
from app.db.models import TaskEvent
from app.domain.workflows.run_outputs import OUTPUT_TEXT_LIMIT
from tests.util import fresh_client, second_client

LONG = "长" * (OUTPUT_TEXT_LIMIT + 500)


def _run(client, graph: dict) -> dict:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "长文", "graph": graph})
    assert workflow.status_code == 200, workflow.text
    job_id = client.post(f"/api/workflows/{workflow.json()['id']}/run", json={"params": {}}).json()["id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.2)
    raise AssertionError("run did not finish")


def test_长文字在事件里截断并标明全文多长_全文从接口取得到() -> None:
    client = fresh_client()
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "long", "type": "template", "config": {"template": LONG}},
            {"id": "short", "type": "template", "config": {"template": "短的"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "long"},
            {"id": "e2", "source": "start", "target": "short"},
        ],
    }
    job = _run(client, graph)
    assert job["status"] == "succeeded", job

    with SessionLocal() as db:
        finished = {
            event.payload["node_id"]: event.payload
            for event in db.query(TaskEvent).filter(TaskEvent.job_id == job["id"], TaskEvent.type == "workflow.node.finished")
        }
    # 快照照旧有界,并说明截了哪一个、全文多少字。
    assert len(finished["long"]["outputs"]["text"]) == OUTPUT_TEXT_LIMIT + 1
    assert finished["long"]["truncated"] == {"text": len(LONG)}
    # 没截的不带这一格。
    assert "truncated" not in finished["short"]

    full = client.get(f"/api/workflows/runs/{job['id']}/outputs/long/text")
    assert full.status_code == 200, full.text
    assert full.json() == {"value": LONG}

    # 没截断的输出没有另存全文:快照本身就是全文。
    assert client.get(f"/api/workflows/runs/{job['id']}/outputs/short/text").status_code == 404


def test_别人看不见的运行取不到全文() -> None:
    client = fresh_client()
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "long", "type": "template", "config": {"template": LONG}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "long"}],
    }
    job = _run(client, graph)
    assert job["status"] == "succeeded", job

    outsider = second_client()
    assert outsider.get(f"/api/workflows/runs/{job['id']}/outputs/long/text").status_code == 404
