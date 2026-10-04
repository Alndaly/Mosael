"""一步失败，已经做出来的照实交出来;失败的那一步单独标失败。

隔离环境里真跑「模特上身图」:上身图出了、付了钱，接着用它出视频的那一步被服务商拒了(写实人像首帧)。
循环选的是「一项失败就记下、接着跑别的」,模板也特意只交上身图(「带不带视频都一样」)—— 可工作流输出里的
图片数是 0:引擎在体里有节点失败时把这一项**整个**丢掉，连同已经落定的那张图。顶层也一样：一条工作流失败了，
任务结果里只剩一句失败原因，前面已经跑完、付过钱的节点产物一样都不在。
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from app.core.unit_of_work import unit_of_work
from app.db.models import Workflow
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows import executors as registry
from tests.util import fresh_client


def _workspace() -> str:
    client = fresh_client()
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _workflow(ws: str) -> Workflow:
    with unit_of_work() as db:
        workflow = Workflow(workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        db.refresh(workflow)
        db.expunge(workflow)
        return workflow


@pytest.fixture
def shoot(monkeypatch):
    """体里两步：出图(每一项都成)→ 用这张图出视频(第 2 项被拒)。"""

    def picture(db, workflow, config: dict[str, Any]) -> dict[str, Any]:
        return {"asset_id": f"img-{config['item']}"}

    def clip(db, workflow, config: dict[str, Any]) -> dict[str, Any]:
        if config["item"] == "2":
            raise WorkflowDomainError("wfErr_llmPromptEmpty")
        return {"asset_id": f"clip-{config['item']}"}

    monkeypatch.setitem(registry._REGISTRY, "t_picture", picture)
    monkeypatch.setitem(registry._REGISTRY, "t_clip", clip)


def _loop(output: str, concurrency: int) -> dict[str, Any]:
    return {
        "id": "each",
        "type": "loop_foreach",
        "config": {
            "items": ["1", "2", "3"],
            "on_item_error": "skip",
            "concurrency": concurrency,
            "body": {
                "nodes": [
                    {"id": "picture", "type": "t_picture", "name": "出上身图", "config": {"item": "{{loop.item}}"}},
                    {"id": "clip", "type": "t_clip", "name": "出视频", "config": {"item": "{{loop.item}}"}},
                ],
                "edges": [{"id": "e", "source": "picture", "target": "clip"}],
            },
            "output": output,
        },
    }


@pytest.mark.parametrize("concurrency", [1, 3])
def test_体里后一步失败_前一步做出来的照样进结果_失败的那一步单独记下(shoot, concurrency: int) -> None:
    from app.domain.workflows.engine import execute_graph

    ws = _workspace()
    context, cancelled = execute_graph(
        {"nodes": [_loop("{{picture.asset_id}}", concurrency)], "edges": []}, wf_id=_workflow(ws).id, entry_is_root=True
    )

    assert not cancelled
    out = context["each"]
    assert out["results"] == ["img-1", "img-2", "img-3"], "第 2 项的图已经出了、付了钱，得交出来"
    assert out["count"] == 3
    assert out["failed"] == [2], "失败的那一步照样记下"
    assert "第 2 项" in out["failure_note"] and "出视频" in out["failure_note"], out["failure_note"]


@pytest.mark.parametrize("concurrency", [1, 3])
def test_交付要的正是失败的那一步时_这一项照旧不进结果(shoot, concurrency: int) -> None:
    """交的是视频、视频没出来:没有可交的东西，不拿一个空串顶上。"""
    from app.domain.workflows.engine import execute_graph

    ws = _workspace()
    context, _ = execute_graph(
        {"nodes": [_loop("{{clip.asset_id}}", concurrency)], "edges": []}, wf_id=_workflow(ws).id, entry_is_root=True
    )

    out = context["each"]
    assert out["results"] == ["clip-1", "clip-3"]
    assert out["failed"] == [2] and "第 2 项" in out["failure_note"]


def test_顶层一步失败_任务结果里照样有已经跑完的节点产物() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {"params": {}}},
            {"id": "made", "type": "template", "name": "已经做好的", "config": {"template": "img-1"}},
            {"id": "check", "type": "condition", "name": "随后失败",
             "config": {"left": "不是数", "op": "gt", "right": "2"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "made"},
            {"id": "e2", "source": "made", "target": "check"},
        ],
    }
    workflow = client.post("/api/workflows", json={"workspace_id": ws, "name": "后一步失败", "graph": graph})
    job_id = client.post(f"/api/workflows/{workflow.json()['id']}/run", json={"params": {}}).json()["id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.2)

    assert job["status"] == "failed", job
    assert job["result"]["failure"], "失败现场照旧"
    assert job["result"]["context"]["made"] == {"text": "img-1"}, job["result"]
    assert "check" not in job["result"]["context"]
