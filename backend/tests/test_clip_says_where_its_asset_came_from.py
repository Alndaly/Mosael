"""时间线上的片段带着素材的来源(asset_source)—— 逐字稿据此不把分离出来的人声 / 背景音再算一遍
(前端 domain/timeline/transcriptSources)。"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Asset
from tests.util import fresh_client


def test_序列里的片段带着素材来源() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sid = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()["id"]
    with SessionLocal() as db:
        stem = Asset(workspace_id=ws, kind="audio", name="原片 · 背景音", file_key="media/bg.wav", source="separated",
                     media_info={"duration": 5.0})
        db.add(stem)
        db.commit()
        stem_id = stem.id
    seq = client.post(f"/api/sequences/{sid}/append", json={"asset_id": stem_id}).json()
    [clip] = [clip for track in seq["tracks"] for clip in track["clips"]]
    assert clip["asset_source"] == "separated"
