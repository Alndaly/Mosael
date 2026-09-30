"""「查素材」的标签接一个真列表 —— 和「素材打标签」同一种解析。

此前 `str(config.get("tags"))`:上游交来 `["口播", "封面"]`,被当成一个叫 `['口播'` 的标签,
什么都筛不出来,也不报错。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Asset, Workflow
from app.domain.workflows.engine import execute_graph
from tests.util import fresh_client


def _setup() -> str:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        for name, tags in (("a", ["口播"]), ("b", ["封面"]), ("c", ["别的"])):
            db.add(Asset(workspace_id=ws, kind="video", name=name, source="imported", file_key="x", tags=tags))
        workflow = Workflow(workspace_id=ws, name="查", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        return workflow.id


def _query(wf_id: str, tags, limit="") -> dict:
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "q", "type": "asset_query", "config": {"kind": "all", "tags": "", "limit": limit}},
        ],
        "edges": [{"id": "d1", "source": "start", "target": "q", "kind": "data",
                   "source_output": "tags", "target_input": "tags"}],
    }
    context, _ = execute_graph(graph, wf_id=wf_id, params={"tags": tags})
    return context["q"]


def test_上游交来一个标签列表() -> None:
    wf_id = _setup()
    out = _query(wf_id, ["口播", "封面"])
    assert sorted(one["name"] for one in out["assets"]) == ["a", "b"]


def test_手填的逗号分隔照旧() -> None:
    wf_id = _setup()
    assert sorted(one["name"] for one in _query(wf_id, "口播，封面")["assets"]) == ["a", "b"]


def test_数量上限写成小数形式的整数照样认() -> None:
    wf_id = _setup()
    assert _query(wf_id, "", limit="1.0")["count"] == 1
