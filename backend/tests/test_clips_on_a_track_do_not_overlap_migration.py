"""库里已经叠在一起的片段,升级时按「后开始的盖住先开始的」规整:`_migrate_clips_on_a_track_do_not_overlap`。

这些重叠来自此前不守不变量的算子(非波纹插入 / 移动、修剪、慢放)。规整和现在的覆盖同一条规矩:
被盖住的部分裁掉、两头都露出来就切成两段、剩不到最小余量的碎片不留;关键帧跟着每一截重投影。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Clip, Sequence
from tests.test_clips_never_overlap import assert_no_overlap
from tests.util import create_asset, fresh_client


def test_叠着的片段规整成后开始的盖住先开始的_改过的序列换一个版本号() -> None:
    from app.db.migrations import _migrate_clips_on_a_track_do_not_overlap

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    asset = create_asset(client, {"workspace_id": ws, "project_id": project, "kind": "video", "name": "V",
                                  "file_key": "media/v.mp4", "media_info": {"duration": 60}})["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    untouched = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "T"}).json()
    video = next(t for t in sequence["tracks"] if t["kind"] == "video")["id"]
    audio = next(t for t in sequence["tracks"] if t["kind"] == "audio")["id"]

    def clip(clip_id, track, start, src_in, src_out, **extra):
        return Clip(id=clip_id, workspace_id=ws, sequence_id=sequence["id"], track_id=track, asset_id=asset,
                    timeline_start=start, src_in=src_in, src_out=src_out, **extra)

    fade = {"keyframes": [{"t": 0, "opacity": 0}, {"t": 1, "opacity": 1}]}
    with SessionLocal() as db:
        db.add_all([
            # V1:BIG[0,10) 里落着 MID[3,5)(切开 BIG),TAIL[8,12) 盖住 BIG 的尾巴(裁掉)。
            clip("BIG", video, 0, 0, 10, transform=fade),
            clip("MID", video, 3, 20, 22),
            clip("TAIL", video, 8, 30, 34),
            # A1:两段同时开始 —— 后建的盖住先建的;2 倍速的那段按时间线长度算。
            clip("FIRST", audio, 0, 0, 4),
            clip("SECOND", audio, 0, 10, 12, speed=2.0),
            # 只露出 0.02 秒(源时间)的头:碎片不留。
            clip("SLIVER", audio, 0.99, 0, 1.01),
            clip("LATE", audio, 1, 40, 45),
        ])
        db.commit()
        revision = db.get(Sequence, sequence["id"]).revision

    _migrate_clips_on_a_track_do_not_overlap()
    body = client.get(f"/api/sequences/{sequence['id']}").json()
    assert_no_overlap(body)

    def spans(track_id):
        clips = next(t for t in body["tracks"] if t["id"] == track_id)["clips"]
        return sorted(
            (c["id"][:6] if c["id"] in {"BIG", "MID", "TAIL", "FIRST", "SECOND", "SLIVER", "LATE"} else "new",
             round(c["timeline_start"], 3), round(c["src_in"], 3), round(c["src_out"], 3))
            for c in clips
        )

    assert spans(video) == [("BIG", 0, 0, 3), ("MID", 3, 20, 22), ("TAIL", 8, 30, 34), ("new", 5, 5, 8)]
    big = next(c for t in body["tracks"] for c in t["clips"] if c["id"] == "BIG")
    assert [round(k["opacity"], 3) for k in big["transform"]["keyframes"]] == [0, 0.3], "关键帧跟着裁剩的那截重投影"
    assert spans(audio) == [("LATE", 1, 40, 45), ("SECOND", 0, 10, 12)], "FIRST 被同时开始、后建的 SECOND 盖住;碎片不留"
    assert body["revision"] == revision + 1
    assert client.get(f"/api/sequences/{untouched['id']}").json()["revision"] == untouched["revision"], "没叠着的序列不换版本号"

    _migrate_clips_on_a_track_do_not_overlap()
    assert client.get(f"/api/sequences/{sequence['id']}").json() == body, "再跑一次什么都不做"
