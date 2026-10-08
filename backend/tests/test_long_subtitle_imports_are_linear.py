"""一次铺很多条字幕(导入 .srt、一键生成)是**线性**的,结果和一条一条放下一模一样。

此前每放一条就把整条轨重新查一遍、逐段比(`coverage.clear_range`):两千条字幕 18 秒,全程攥着写锁,
而那个端点又是 async 的 —— 那十八秒里整个后端一个请求都答不出来(端点的那半见 test_async_routes_do_not_touch_the_database)。
现在轨上的片段只查一次、在内存里按起点排好、二分找落点(`coverage.TrackCover`)。

两件事要同时成立:查库的次数不随条数长;放下的结果和老办法(每条 clear_range)逐条一致 —— 包括盖住原有字幕、
新字幕之间互相盖住、切开一条横跨落点的老字幕。
"""

from __future__ import annotations

import random

from app.core.db import SessionLocal
from app.db.models import Asset, Clip, Sequence
from app.domain.sequences import coverage
from app.domain.sequences.coverage import clear_range, clip_end
from app.domain.sequences.journal import Journal
from app.domain.sequences.text import GenerateSubtitles, generate_subtitles
from tests.util import fresh_client


def _timeline(client, seconds: float = 4000.0) -> tuple[str, str]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sid = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()["id"]
    with SessionLocal() as db:
        footage = Asset(workspace_id=ws, kind="video", name="原片", file_key="media/v.mp4", media_info={"duration": seconds})
        db.add(footage)
        db.commit()
        footage_id = footage.id
    assert client.post(f"/api/sequences/{sid}/append", json={"asset_id": footage_id}).status_code == 200
    seq = client.post(f"/api/sequences/{sid}/tracks", json={"kind": "subtitle"}).json()
    return sid, next(t["id"] for t in seq["tracks"] if t["kind"] == "subtitle")


def _laid(sid: str, track: str) -> list[tuple[float, float, float, str]]:
    with SessionLocal() as db:
        clips = db.query(Clip).filter(Clip.sequence_id == sid, Clip.track_id == track).all()
        return sorted((round(c.timeline_start, 6), round(c.src_in, 6), round(c.src_out, 6), c.text_override or "") for c in clips)


def _lay_one_by_one(sid: str, track: str, cues: list[tuple[str, float, float]]) -> None:
    """老办法:每条建好就 clear_range 一遍整条轨。作对照用。"""
    with SessionLocal() as db:
        sequence = db.get(Sequence, sid)
        journal = Journal(db, sequence)
        for text, start, duration in cues:
            clip = journal.create(Clip(workspace_id=sequence.workspace_id, sequence_id=sid, track_id=track, asset_id=None,
                                       timeline_start=start, src_in=0, src_out=duration, text_override=text))
            clear_range(journal, track, clip.timeline_start, clip_end(clip), keep={clip.id})
        db.commit()


def _lay_with_generate(sid: str, track: str, cues: list[tuple[str, float, float]]) -> None:
    with SessionLocal() as db:
        generate_subtitles(db, sid, GenerateSubtitles(track_id=track, cues=tuple(cues)))
        db.commit()


def _messy_cues(rng: random.Random, count: int) -> list[tuple[str, float, float]]:
    """互相叠着、长短不一、乱序的字幕 —— 正好把「盖住」「切开」「整条删掉」都走一遍。"""
    return [(f"第{i}句", round(rng.uniform(0, 300), 3), round(rng.uniform(0.2, 12), 3)) for i in range(count)]


def test_laying_many_cues_gives_the_same_track_as_one_by_one() -> None:
    client = fresh_client()
    rng = random.Random(20261008)
    for _round in range(3):
        existing = _messy_cues(rng, 40)
        incoming = _messy_cues(rng, 120)
        old_sid, old_track = _timeline(client)
        new_sid, new_track = _timeline(client)
        # 两条轨上先放一样的老字幕(同一个老办法),再分别用两种办法铺新的。
        _lay_one_by_one(old_sid, old_track, existing)
        _lay_one_by_one(new_sid, new_track, existing)
        _lay_one_by_one(old_sid, old_track, incoming)
        _lay_with_generate(new_sid, new_track, incoming)
        assert _laid(new_sid, new_track) == _laid(old_sid, old_track)


def test_the_track_is_read_once_not_once_per_cue(monkeypatch) -> None:
    client = fresh_client()
    sid, track = _timeline(client)
    reads: list[str] = []
    real = coverage.clips_on_track

    def counting(db, track_id):
        reads.append(track_id)
        return real(db, track_id)

    monkeypatch.setattr(coverage, "clips_on_track", counting)
    cues = [(f"第{i}句", i * 1.5, 1.2) for i in range(300)]
    _lay_with_generate(sid, track, cues)

    assert len(_laid(sid, track)) == 300
    assert reads.count(track) <= 2, f"铺 300 条字幕把字幕轨查了 {reads.count(track)} 遍 —— 又回到了每条一遍"


def test_a_cue_that_splits_an_old_one_leaves_both_ends() -> None:
    client = fresh_client()
    sid, track = _timeline(client)
    _lay_one_by_one(sid, track, [("老的一长条", 0.0, 10.0)])
    _lay_with_generate(sid, track, [("插进来", 4.0, 2.0)])
    assert _laid(sid, track) == [(0.0, 0.0, 4.0, "老的一长条"), (4.0, 0.0, 2.0, "插进来"), (6.0, 6.0, 10.0, "老的一长条")]
