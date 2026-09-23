"""首页项目卡片的封面:时间线上最早出现的那个画面。

真机:一个项目的时间线第一段就是一张图,卡片却显示「等待你的第一个画面」。封面此前由前端从
「归属这个项目的素材」里挑 —— 而那段片段引用的是工作区里别处的素材,项目自己名下 0 个素材。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Asset, Clip, Sequence, Track
from tests.util import fresh_client


def _setup(client):
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "混剪"}).json()
    return ws, project


def _cover(client, ws_id: str, project_id: str) -> str | None:
    return next(p for p in client.get(f"/api/projects?workspace_id={ws_id}").json() if p["id"] == project_id)["cover_asset_id"]


def _asset(db, ws_id: str, *, project_id: str | None, kind: str, name: str) -> str:
    asset = Asset(workspace_id=ws_id, project_id=project_id, name=name, kind=kind, file_key=f"{name}")
    db.add(asset)
    db.flush()
    return asset.id


def test_时间线引用别处的素材_封面就是它() -> None:
    client = fresh_client()
    ws, project = _setup(client)
    with SessionLocal() as db:
        elsewhere = _asset(db, ws["id"], project_id=None, kind="image", name="bed.png")
        later = _asset(db, ws["id"], project_id=None, kind="video", name="later.mp4")
        audio = _asset(db, ws["id"], project_id=None, kind="audio", name="vo.mp3")
        seq = Sequence(workspace_id=ws["id"], project_id=project["id"], name="S")
        video = Track(sequence=seq, kind="video", name="V1", position=0)
        sound = Track(sequence=seq, kind="audio", name="A1", position=1)
        db.add_all([seq, video, sound])
        db.flush()
        db.add_all([
            Clip(workspace_id=ws["id"], sequence_id=seq.id, track_id=sound.id, asset_id=audio, timeline_start=0, src_in=0, src_out=5),
            Clip(workspace_id=ws["id"], sequence_id=seq.id, track_id=video.id, asset_id=later, timeline_start=5, src_in=0, src_out=5),
            Clip(workspace_id=ws["id"], sequence_id=seq.id, track_id=video.id, asset_id=elsewhere, timeline_start=0, src_in=0, src_out=5),
        ])
        db.commit()

    assert _cover(client, ws["id"], project["id"]) == elsewhere


def test_时间线上还没有画面_用项目自己的第一张图() -> None:
    client = fresh_client()
    ws, project = _setup(client)
    with SessionLocal() as db:
        own = _asset(db, ws["id"], project_id=project["id"], kind="image", name="own.png")
        db.commit()

    assert _cover(client, ws["id"], project["id"]) == own


def test_什么画面都没有_就是空() -> None:
    client = fresh_client()
    ws, project = _setup(client)
    assert _cover(client, ws["id"], project["id"]) is None
