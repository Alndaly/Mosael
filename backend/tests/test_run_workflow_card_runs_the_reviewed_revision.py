"""「运行工作流」卡批准时跑的,必须是开卡时审的那一版。

卡的档位(图里有没有对外的节点)和卡上的后果说明,都按**开卡那一刻**的图算;而执行体此前跑的是批准那一刻的
最新修订。于是:智能体对一张只有文本节点的图开卡(ai-cost,卡上没有任何对外警示),之后图里加了一个 HTTP
节点,用户照着那张卡批下去,跑的是会往外发请求的那一版。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Job
from app.domain.jobs import wait_for_idle_jobs
from tests.util import fresh_client

HARMLESS = {
    "nodes": [{"id": "start", "type": "start", "config": {"params": {}}},
              {"id": "t", "type": "template", "config": {"template": "x"}}],
    "edges": [{"id": "e", "source": "start", "target": "t"}],
}
OUTWARD = {
    "nodes": [{"id": "start", "type": "start", "config": {"params": {}}},
              {"id": "h", "type": "http_request", "config": {"url": "https://example.com/hook", "method": "POST"}}],
    "edges": [{"id": "e", "source": "start", "target": "h"}],
}


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    wf = client.post("/api/workflows", json={"workspace_id": ws, "name": "日更", "graph": HARMLESS}).json()["id"]
    card = client.post("/api/confirmations", json={
        "workspace_id": ws, "tool": "run_workflow", "requested_by": "pi", "payload": {"workflow_id": wf, "params": {}},
    }).json()
    assert card["permission"] == "ai-cost" and not card["warning"]
    return client, ws, wf, card


def _workflow_jobs(ws: str) -> list[Job]:
    with SessionLocal() as db:
        return db.query(Job).filter(Job.kind == "workflow", Job.workspace_id == ws).all()


def test_开卡之后图被改过_批准时不跑_说清是改过了() -> None:
    client, ws, wf, card = _setup()
    base = client.get(f"/api/workflows/{wf}").json()["graph_hash"]
    changed = client.patch(f"/api/workflows/{wf}", json={"graph": OUTWARD, "base_graph_hash": base})
    assert changed.status_code == 200, changed.text

    settled = client.post(f"/api/confirmations/{card['id']}/approve").json()
    wait_for_idle_jobs(timeout=10)

    assert settled["status"] == "failed"
    assert "被改过" in settled["error"] and "日更" in settled["error"], settled["error"]
    assert _workflow_jobs(ws) == [], "改过之后的那一版不能借这张卡跑起来"


def test_没改过_照常跑开卡时那一版() -> None:
    client, ws, wf, card = _setup()
    opened = client.get(f"/api/workflows/{wf}").json()["revision"]

    settled = client.post(f"/api/confirmations/{card['id']}/approve").json()
    wait_for_idle_jobs(timeout=10)

    assert settled["status"] == "executed", settled.get("error")
    [job] = _workflow_jobs(ws)
    assert job.payload["workflow_revision"] == opened == settled["result"]["workflow_revision"]
