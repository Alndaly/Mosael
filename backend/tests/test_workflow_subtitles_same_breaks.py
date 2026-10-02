"""工作流的「生成字幕」和剪辑台用同一套断句,时间按片段的入点与倍速映射。

审查时:工作流直接拿引擎的段落当字幕(一段二三十秒、上百个字),剪辑台却是一句一行;时间只能整体平移 ——
片段从素材中间开始、或者调过速,字幕就对不上嘴。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Asset, Clip, Sequence, Track, Workflow
from app.domain.workflows.executors import get_executor
from app.domain.workflows.executors.subjobs import transcript_sentences
from tests.util import fresh_client

#: 一段 6 秒、两句话的引擎段落,带词级时间戳(词里没有标点,标点在段落原文里)。
PARAGRAPH = {
    "start": 0.0, "end": 6.0, "text": "今天我们去公园。然后回家吃饭!", "speaker": "",
    "tokens": [
        {"start": 0.0, "end": 0.6, "text": "今天"}, {"start": 0.6, "end": 1.0, "text": "我们"},
        {"start": 1.0, "end": 1.4, "text": "去"}, {"start": 1.4, "end": 2.4, "text": "公园"},
        {"start": 3.0, "end": 3.6, "text": "然后"}, {"start": 3.6, "end": 4.2, "text": "回家"},
        {"start": 4.2, "end": 5.8, "text": "吃饭"},
    ],
}


def _timeline(*, src_in: float = 0.0, speed: float = 1.0, timeline_start: float = 0.0) -> tuple[str, str, str]:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sid = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()["id"]
    with SessionLocal() as db:
        footage = Asset(workspace_id=ws, kind="video", name="原片", file_key="media/v.mp4", media_info={"duration": 60.0})
        db.add(footage)
        db.flush()
        video = next(track for track in db.get(Sequence, sid).tracks if track.kind == "video")
        clip = Clip(workspace_id=ws, sequence_id=sid, track_id=video.id, asset_id=footage.id,
                    timeline_start=timeline_start, src_in=src_in, src_out=src_in + 4.0, speed=speed)
        db.add(clip)
        db.commit()
        return ws, sid, clip.id


def _run(ws: str, config: dict) -> dict:
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="W", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        out = get_executor("generate_subtitles")(db, workflow, config)
        db.commit()
        return out


def _cues(sid: str) -> list[tuple[str, float, float]]:
    with SessionLocal() as db:
        track = db.query(Track).filter(Track.sequence_id == sid, Track.kind == "subtitle").first()
        return sorted((c.text_override, round(c.timeline_start, 3), round(c.src_out - c.src_in, 3))
                      for c in db.query(Clip).filter(Clip.track_id == track.id))


def test_引擎段落按剪辑台那套切成一句一行() -> None:
    ws, sid, _ = _timeline()
    _run(ws, {"sequence_id": sid, "segments": [PARAGRAPH]})
    assert [text for text, _, _ in _cues(sid)] == ["今天我们去公园。", "然后回家吃饭!"]
    assert [row["text"] for row in transcript_sentences([PARAGRAPH])] == ["今天我们去公园。", "然后回家吃饭!"]


def test_按片段的入点和倍速映射_片段外的不上屏() -> None:
    # 片段从素材第 2 秒开始用 4 秒(到第 6 秒),2 倍速,接在时间线第 10 秒。
    ws, sid, clip_id = _timeline(src_in=2.0, speed=2.0, timeline_start=10.0)
    segments = [
        {"start": 0.0, "end": 1.5, "text": "片段之前", "speaker": "", "tokens": []},
        {"start": 3.0, "end": 5.0, "text": "片段里", "speaker": "", "tokens": []},
        {"start": 5.0, "end": 8.0, "text": "跨出片段尾", "speaker": "", "tokens": []},
    ]
    _run(ws, {"sequence_id": sid, "segments": segments, "clip_id": clip_id})
    # 素材 3–5 秒 → 时间线 10 + (3-2)/2 = 10.5 起、1 秒长;5–6 秒(截到片段尾)→ 11.5 起、0.5 秒。
    assert _cues(sid) == [("片段里", 10.5, 1.0), ("跨出片段尾", 11.5, 0.5)]
