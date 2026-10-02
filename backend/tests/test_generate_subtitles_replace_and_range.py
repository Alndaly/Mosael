"""生成字幕:再生成一次是**替换**(一步撤销),时间先验过再落库。

审查实测(探针 P5):同一条字幕轨生成两次,每一句叠成两份;一条起点 1e9 秒的字幕照样 200。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Asset
from app.domain.sequences.history import undo
from tests.util import fresh_client


def _timeline(client) -> tuple[str, str]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sid = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()["id"]
    with SessionLocal() as db:
        footage = Asset(workspace_id=ws, kind="video", name="原片", file_key="media/v.mp4", media_info={"duration": 20.0})
        db.add(footage)
        db.commit()
        footage_id = footage.id
    assert client.post(f"/api/sequences/{sid}/append", json={"asset_id": footage_id}).status_code == 200
    seq = client.post(f"/api/sequences/{sid}/tracks", json={"kind": "subtitle"}).json()
    return sid, next(t["id"] for t in seq["tracks"] if t["kind"] == "subtitle")


def _generate(client, sid: str, track: str, cues: list[tuple[str, float, float]], **extra):
    return client.post(f"/api/sequences/{sid}/subtitles/generate",
                       json={"track_id": track, "cues": [{"text": t, "timeline_start": s, "duration": d} for t, s, d in cues],
                             **extra})


def _cues(client, sid: str, track: str) -> list[tuple[float, str]]:
    seq = client.get(f"/api/sequences/{sid}").json()
    return sorted((c["timeline_start"], c["text_override"]) for c in next(t for t in seq["tracks"] if t["id"] == track)["clips"])


def test_重新生成替换原来的字幕_一步撤销回到上一版() -> None:
    client = fresh_client()
    sid, track = _timeline(client)
    assert _generate(client, sid, track, [("甲", 1.0, 2.0), ("乙", 3.5, 2.0)]).status_code == 200
    response = _generate(client, sid, track, [("甲二", 1.0, 2.0)], replace=True)
    assert response.status_code == 200, response.text
    assert _cues(client, sid, track) == [(1.0, "甲二")], "原来的两条换掉了,没有叠成两份"
    with SessionLocal() as db:
        undo(db, sid)
        db.commit()
    assert _cues(client, sid, track) == [(1.0, "甲"), (3.5, "乙")], "一次撤销:删旧和铺新一起退回"


def test_不说替换时照旧追加() -> None:
    client = fresh_client()
    sid, track = _timeline(client)
    _generate(client, sid, track, [("甲", 1.0, 2.0)])
    _generate(client, sid, track, [("乙", 5.0, 2.0)])
    assert _cues(client, sid, track) == [(1.0, "甲"), (5.0, "乙")]


def test_起点在时间线内容之外的字幕被拒_说是第几条() -> None:
    client = fresh_client()
    sid, track = _timeline(client)
    response = _generate(client, sid, track, [("好", 1.0, 2.0), ("X", 1e9, 1e9)])
    assert response.status_code == 422
    assert "第 2 条" in response.json()["detail"] or "Subtitle 2" in response.json()["detail"]
    assert _cues(client, sid, track) == [], "整批不落"


def test_尾巴超出内容末尾的截到末尾() -> None:
    client = fresh_client()
    sid, track = _timeline(client)
    assert _generate(client, sid, track, [("尾", 19.0, 5.0)]).status_code == 200
    seq = client.get(f"/api/sequences/{sid}").json()
    [cue] = next(t for t in seq["tracks"] if t["id"] == track)["clips"]
    assert cue["src_out"] - cue["src_in"] == 1.0
