"""SRT / WebVTT 字幕文件的导入导出:格式本身(编码、换行、时间码、标记)和落到时间线上的规矩。"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from app.db.models import Asset
from app.domain.sequences.history import undo
from app.media.subtitle_files import Cue, SubtitleFileError, decode, parse, resolve_overlaps, to_srt, to_vtt
from tests.util import fresh_client

SRT = """1
00:00:01,000 --> 00:00:02,500
<i>你好</i>
Hello

2
00:00:03,000 --> 00:00:04,000
再见 &amp; 回见
"""

VTT = """WEBVTT
Kind: captions

NOTE 这是注释

STYLE
::cue { color: red }

intro
00:01.000 --> 00:02.500 align:start position:10%
<v 甲>你好</v>

00:00:03.000 --> 00:00:04.000
<c.yellow>再见</c> --&gt; 回见
"""


class Test读文件:
    def test_srt_去标记_多行_实体(self) -> None:
        assert parse(SRT) == [Cue(1.0, 2.5, "你好\nHello"), Cue(3.0, 4.0, "再见 & 回见")]

    def test_vtt_跳过注释样式块_cue标识与设置_省略小时(self) -> None:
        assert parse(VTT) == [Cue(1.0, 2.5, "你好"), Cue(3.0, 4.0, "再见 --> 回见")]

    def test_各种换行都认(self) -> None:
        assert parse(SRT.replace("\n", "\r\n")) == parse(SRT) == parse(SRT.replace("\n", "\r"))

    def test_编码_BOM_UTF16_GBK(self) -> None:
        assert decode("﻿你好".encode("utf-8")) == "你好"
        assert decode("你好".encode("utf-16")) == "你好"
        assert decode("你好,字幕".encode("gbk")) == "你好,字幕"

    def test_读不出字幕就说读不出(self) -> None:
        with pytest.raises(SubtitleFileError):
            parse("这不是字幕文件")

    def test_重叠的字幕_前一条截到后一条开始_几乎完全盖住的并成两行(self) -> None:
        resolved = resolve_overlaps([Cue(0, 3, "甲"), Cue(2, 4, "乙"), Cue(2.1, 5, "丙")])
        assert resolved == [Cue(0, 2, "甲"), Cue(2, 5, "乙\n丙")]


class Test写文件:
    def test_srt_vtt_往返一致(self) -> None:
        cues = [Cue(1.0, 2.5, "你好\nHello"), Cue(3723.004, 3724.0, "a < b --> c")]
        assert parse(to_srt(cues))[0] == cues[0]
        assert parse(to_vtt(cues)) == cues
        assert "01:02:03,004 --> 01:02:04,000" in to_srt(cues)
        assert to_vtt(cues).startswith("WEBVTT\n\n")


def _timeline(client) -> tuple[str, str]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sid = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "访谈"}).json()["id"]
    with SessionLocal() as db:
        footage = Asset(workspace_id=ws, kind="video", name="原片", file_key="media/v.mp4", media_info={"duration": 10.0})
        db.add(footage)
        db.commit()
        footage_id = footage.id
    assert client.post(f"/api/sequences/{sid}/append", json={"asset_id": footage_id}).status_code == 200
    return ws, sid


def _import(client, sid: str, content: bytes, name: str = "a.srt", **form):
    return client.post(f"/api/sequences/{sid}/subtitles/import", files={"file": (name, content, "text/plain")},
                       data={key: str(value) for key, value in form.items()})


def test_导入到新建的字幕轨_一步撤销连轨带字幕() -> None:
    client = fresh_client()
    _, sid = _timeline(client)
    response = _import(client, sid, SRT.encode("gbk"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["imported"], body["dropped"]) == (2, 0)
    track = next(t for t in body["sequence"]["tracks"] if t["id"] == body["track_id"])
    assert track["kind"] == "subtitle"
    assert sorted((c["timeline_start"], c["text_override"]) for c in track["clips"]) == [(1.0, "你好\nHello"), (3.0, "再见 & 回见")]
    with SessionLocal() as db:
        undo(db, sid)
        db.commit()
    seq = client.get(f"/api/sequences/{sid}").json()
    assert not [t for t in seq["tracks"] if t["kind"] == "subtitle"], "一次撤销:新建的轨和字幕都没了"


def test_导入可平移_内容之外的不落并报条数_可替换原有字幕() -> None:
    client = fresh_client()
    _, sid = _timeline(client)
    first = _import(client, sid, SRT.encode()).json()
    response = _import(client, sid, SRT.encode(), track_id=first["track_id"], offset=7.5, replace="true")
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["imported"], body["dropped"]) == (1, 1), "第二条平移到 10.5 秒,在 10 秒的原片之外"
    track = next(t for t in body["sequence"]["tracks"] if t["id"] == first["track_id"])
    [cue] = track["clips"]
    assert cue["timeline_start"] == 8.5 and cue["src_out"] - cue["src_in"] == 1.5


def test_导出_srt_vtt_双语可选只写译文() -> None:
    client = fresh_client()
    _, sid = _timeline(client)
    track = _import(client, sid, SRT.encode()).json()["track_id"]
    srt = client.get(f"/api/sequences/{sid}/subtitles/export", params={"track_id": track, "format": "srt"})
    assert srt.status_code == 200
    assert "attachment" in srt.headers["content-disposition"] and ".srt" in srt.headers["content-disposition"]
    assert parse(srt.content.decode("utf-8")) == [Cue(1.0, 2.5, "你好\nHello"), Cue(3.0, 4.0, "再见 & 回见")]
    vtt = client.get(f"/api/sequences/{sid}/subtitles/export", params={"track_id": track, "format": "vtt", "line": "last"})
    assert parse(vtt.content.decode("utf-8"))[0].text == "Hello"
    bad = client.get(f"/api/sequences/{sid}/subtitles/export", params={"track_id": track, "format": "ass"})
    assert bad.status_code == 422


def test_读不出来的文件说清楚() -> None:
    client = fresh_client()
    _, sid = _timeline(client)
    response = _import(client, sid, b"\x89PNG not a subtitle")
    assert response.status_code == 422


def test_导入照着它看到的那一版做_中间有人动过位置就409附最新序列() -> None:
    """和别的编辑同一个并发协议(sequences/concurrency):导入建片段、覆盖落点,依赖坐标。"""
    client = fresh_client()
    ws, sid = _timeline(client)
    seen = client.get(f"/api/sequences/{sid}").json()["revision"]
    with SessionLocal() as db:
        more = Asset(workspace_id=ws, kind="video", name="又一段", file_key="media/w.mp4", media_info={"duration": 5.0})
        db.add(more)
        db.commit()
        more_id = more.id
    assert client.post(f"/api/sequences/{sid}/append", json={"asset_id": more_id}).status_code == 200
    stale = client.post(f"/api/sequences/{sid}/subtitles/import?base_revision={seen}",
                        files={"file": ("a.srt", SRT.encode(), "text/plain")})
    assert stale.status_code == 409, stale.text
    detail = stale.json()["detail"]
    assert detail["code"] == "sequence_revision_conflict" and detail["sequence"]["revision"] > seen
    fresh = client.post(f"/api/sequences/{sid}/subtitles/import?base_revision={detail['sequence']['revision']}",
                        files={"file": ("a.srt", SRT.encode(), "text/plain")})
    assert fresh.status_code == 200, fresh.text
