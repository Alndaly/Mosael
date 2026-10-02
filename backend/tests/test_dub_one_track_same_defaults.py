"""配音「配哪几条、默认怎么配」归领域层一处,剪辑台 / 智能体 / 工作流三个入口一致。

审查时的两处分叉:
- 剪辑台把**所有字幕轨**的条目一起交下去,后端照单全收(探针 P2):双语分两条轨时,同一秒上一句念原文、
  一句念译文。
- 「压进原字幕长度」剪辑台默认关、智能体和工作流默认开:同一条时间线从两个入口配出来不一样。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.domain.voices.subtitle_dub import DEFAULT_MATCH_DURATION, DubError, dub_targets, start_subtitle_dub
from tests.util import fresh_client


def _two_tracks(client) -> tuple[str, dict[str, list[str]]]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sid = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()["id"]
    cues: dict[str, list[str]] = {}
    for text in ("你好", "Hello"):
        seq = client.post(f"/api/sequences/{sid}/tracks", json={"kind": "subtitle"}).json()
        track = [t for t in seq["tracks"] if t["kind"] == "subtitle"][-1]["id"]
        seq = client.post(f"/api/sequences/{sid}/subtitles/generate",
                          json={"track_id": track, "cues": [{"text": text, "timeline_start": 1.0, "duration": 2.0}]}).json()
        cues[track] = [c["id"] for c in next(t for t in seq["tracks"] if t["id"] == track)["clips"]]
    return sid, cues


def test_跨两条字幕轨的一批被拒_一次只配一条() -> None:
    client = fresh_client()
    sid, cues = _two_tracks(client)
    every = [clip for ids in cues.values() for clip in ids]
    with SessionLocal() as db, pytest.raises(DubError, match="不止一条字幕轨"):
        start_subtitle_dub(db, sequence_id=sid, clip_ids=every, match_duration=True, created_by=None,
                           synthesis={"engine": "builtin:volcano", "engine_voice": "v"})


def test_点名条目又给了轨道_只取那条轨上的() -> None:
    client = fresh_client()
    sid, cues = _two_tracks(client)
    first, second = cues
    every = [clip for ids in cues.values() for clip in ids]
    with SessionLocal() as db:
        assert dub_targets(db, sid, every, second) == cues[second]
        assert dub_targets(db, sid, [], first) == cues[first], "没点名 = 整条轨"
        with pytest.raises(DubError, match="多条字幕轨"):
            dub_targets(db, sid, [], "")


def test_剪辑台的接口带上轨道_只把那条轨交下去(monkeypatch) -> None:
    import app.domain.voices.subtitle_dub as dub

    seen: dict = {}

    def fake_start(db, **kwargs):
        seen.update(kwargs)
        raise DubError("到此为止")

    monkeypatch.setattr(dub, "start_subtitle_dub", fake_start)
    client = fresh_client()
    sid, cues = _two_tracks(client)
    first, second = cues
    response = client.post(f"/api/sequences/{sid}/dub-subtitles",
                           json={"track_id": second, "engine": "builtin:edge", "engine_voice": "zh-CN-XiaoxiaoNeural"})
    assert response.status_code == 422 and "到此为止" in response.text, response.text
    assert seen["clip_ids"] == cues[second]
    assert seen["match_duration"] is DEFAULT_MATCH_DURATION, "接口不传时用领域层那一个默认"


def test_三个入口的默认值都是领域层那一个() -> None:
    import inspect

    from app.api.schemas.voices import SubtitleDubRequest
    from app.domain.workflows.node_types import NODE_TYPES

    assert SubtitleDubRequest.model_fields["match_duration"].default is DEFAULT_MATCH_DURATION
    node_default = NODE_TYPES["dub_subtitles"]["config"]["match_duration"]["default"]
    assert (node_default == "yes") is DEFAULT_MATCH_DURATION, "工作流节点的默认写成 yes/no,意思得一样"
    from app.domain.agent.confirmable import media
    from app.domain.workflows.executors import subjobs

    for source in (inspect.getsource(media._execute_dub_subtitles), inspect.getsource(subjobs.dub_subtitles)):
        assert "DEFAULT_MATCH_DURATION" in source, "智能体与工作流不各写一个字面量默认"
