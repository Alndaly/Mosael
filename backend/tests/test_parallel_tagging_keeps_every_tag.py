"""并行的几个「素材打标签」往同一份素材上加标签,一个都不丢。

## 现场

asset_tag 读标签 → 合并 → 整列写回。两条分支(或并发的循环项)各在自己的会话里读到同一份标签、各自合并、
各自写回:后写的那个把先写的那个加的标签盖掉。六条并行分支各加一个标签,跑完常常只剩两三个。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Asset
from tests.util import fresh_client, wait_status


def test_六条并行分支各加一个标签_跑完六个都在() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        asset = Asset(workspace_id=ws, kind="image", name="a.png", source="imported", file_key="x",
                      media_info={}, tags=["原有的", "老"])
        db.add(asset)
        db.commit()
        asset_id = asset.id
    names = [f"标签{i}" for i in range(6)]
    graph = {
        "nodes": [{"id": "start", "type": "start", "config": {}}] + [
            {"id": f"t{i}", "type": "asset_tag", "config": {"asset_ids": asset_id, "tags": name, "mode": "add"}}
            for i, name in enumerate(names)
        ],
        "edges": [{"id": f"e{i}", "source": "start", "target": f"t{i}"} for i in range(len(names))],
    }
    workflow = client.post("/api/workflows", json={"workspace_id": ws, "name": "打标签", "graph": graph}).json()
    for _round in range(3):
        with SessionLocal() as db:
            db.get(Asset, asset_id).tags = ["原有的", "老"]
            db.commit()
        started = client.post(f"/api/workflows/{workflow['id']}/run", json={"params": {}}).json()
        assert wait_status(client, started["id"], timeout=20) == "succeeded"
        with SessionLocal() as db:
            tags = db.get(Asset, asset_id).tags
        assert sorted(tags) == sorted(["原有的", "老", *names]), tags
