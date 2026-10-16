"""整条动静曲线的落地和对外(`domain/shots/track.py` + `GET /assets/{id}/shots/track`)。

量出来的曲线此前**算完就丢**:库里只留每镜的中位数(`shots[].motion`),整条 5Hz 序列谁也拿不到。
这里守的是它现在留着,以及留成什么样:

① 量完落库,素材目录里有一份 `shots/track.json`(和 `frames/`、`sheets/` 同一层),点数 = 5Hz × 时长;
② 时间轴约定:第 i 个采样在 `(i + 1) / MOTION_HZ` 秒处(ffmpeg 的 `tblend` 要前一帧,第 0 帧不出值,整条偏一位);
③ 曲线**原样**存:拿它现算一遍每镜中位数 == 库里 `shots[].motion` —— 不做平滑、不补洞,机器量到的是事实;
④ **没有曲线也是 200**(没拆过 / 老行没有这一栏 / 文件丢了或被人动过),不是 404、不炸;
⑤ 重拆覆盖:和帧、联系表一起进 `shots.new/`,换掉旧的。

量 + 取帧用 ffmpeg 现造的小片子(四段纯色,刀口在 1/2/3 秒),和 test_shots_breakdowns 同一招。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, ShotBreakdown
from app.domain.shots import breakdowns, detect, track
from tests.util import fresh_client, insert_asset, wait_settled

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


def _make_cut_video(target: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=red:s=320x180:r=25:d=1",
         "-f", "lavfi", "-i", "color=c=white:s=320x180:r=25:d=1",
         "-f", "lavfi", "-i", "color=c=black:s=320x180:r=25:d=1",
         "-f", "lavfi", "-i", "color=c=yellow:s=320x180:r=25:d=1",
         "-filter_complex", "[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         str(target)],
        check=True, timeout=60,
    )


@pytest.fixture
def client():
    return fresh_client()


@pytest.fixture
def video(client):
    """素材库里一份真实的 4 秒四刀口小片子(和 test_shots_breakdowns 同一份造法)。"""
    ws_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    media = settings.media_dir / "test-shots-track"
    media.mkdir(parents=True, exist_ok=True)
    source = media / f"cuts-{uuid4().hex[:8]}.mp4"
    _make_cut_video(source)
    asset_id = insert_asset(
        ws_id, kind="video", name="刀口样片",
        file_key=source.relative_to(settings.data_dir).as_posix(),
        media_info={"duration": 4.0, "width": 320, "height": 180, "fps": 25},
    )
    yield {"id": asset_id, "workspace_id": ws_id}
    shutil.rmtree(media / "test-shots-track", ignore_errors=True)


def _break_down(client, video) -> dict:
    job = client.post(f"/api/assets/{video['id']}/shots").json()
    assert wait_settled(client, job["id"]) == "succeeded"
    return client.get(f"/api/assets/{video['id']}/shots").json()


# --------------------------------------------------------------------------------------
# track.py:写下来、读回来(不跑 ffmpeg)
# --------------------------------------------------------------------------------------

def test_写下来的曲线读回来一个数都不差(tmp_path: Path) -> None:
    values = [0.0, 3.2, 3.2, 127.5, 0.0, 12.0]
    summary = track.write_track(tmp_path, hz=5, duration=4.0, values=values)
    with track.track_file(tmp_path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["hz"] == 5
    assert payload["values"] == values, "原样存:不筛选、不合并、不补洞"
    assert payload["duration"] == pytest.approx(4.0)
    assert payload["points"] == len(values)

    loaded = track.read_track(tmp_path, expect_digest=summary["digest"])
    assert loaded is not None
    assert loaded["values"] == values
    assert loaded["hz"] == 5 and loaded["points"] == len(values)
    assert loaded["digest"] == summary["digest"] == track.digest_of(track.track_file(tmp_path).read_bytes())
    #: 时间轴约定写进文件本身:第 0 个采样在 1/hz 秒处,相邻两个差 1/hz 秒。
    assert loaded["first_sample_seconds"] == pytest.approx(1 / detect.MOTION_HZ)
    assert loaded["sample_interval_seconds"] == pytest.approx(1 / detect.MOTION_HZ)
    assert set(summary) == {"hz", "points", "digest"}, "库里只留这三样"
    assert summary["digest"].startswith("sha256:")


def test_不认的曲线一律当它不在(tmp_path: Path) -> None:
    assert track.read_track(tmp_path) is None, "文件还没写"
    path = track.track_file(tmp_path)

    path.write_text("{ 不是 JSON", encoding="utf-8")
    assert track.read_track(tmp_path) is None

    path.write_text(json.dumps({"hz": 0, "duration": 1.0, "points": 1, "values": [1.0]}), encoding="utf-8")
    assert track.read_track(tmp_path) is None, "采样率不是正数"

    path.write_text(json.dumps({"hz": 5, "duration": 1.0, "points": 9, "values": [1.0]}), encoding="utf-8")
    assert track.read_track(tmp_path) is None, "点数对不上 = 文件被截过"

    path.write_text(json.dumps({"hz": 5, "duration": 1.0, "points": 1, "values": []}), encoding="utf-8")
    assert track.read_track(tmp_path) is None, "一条空的曲线不是曲线"

    path.write_text(json.dumps({"hz": 5, "duration": 1.0, "points": 1, "values": [float("nan")]}), encoding="utf-8")
    assert track.read_track(tmp_path) is None, "NaN 进不了响应(ApiModel 拒收非有限的数)"

    track.write_track(tmp_path, hz=5, duration=4.0, values=[1.0, 2.0])
    assert track.read_track(tmp_path, expect_digest="sha256:deadbeef") is None, "摘要对不上 = 被人动过"


# --------------------------------------------------------------------------------------
# ① 量完落库:文件、点数、库里的摘要
# --------------------------------------------------------------------------------------

@needs_ffmpeg
def test_量完_曲线落在素材目录里_点数按_5Hz_算(video) -> None:
    with SessionLocal() as db:
        asset = db.get(Asset, video["id"])
        row = breakdowns.measure_into(db, asset, created_by=None, lang="zh")
        db.commit()
        summary = dict(row.motion_track)
        duration = float(row.meta["duration"])
        folder = breakdowns.shots_dir(asset)

    assert summary, "量完要在库里留下曲线去哪了(采样率 + 点数 + 摘要)"
    path = folder / "track.json"
    assert path.is_file(), "曲线落在 shots/ 下,和 frames/、sheets/ 同一层"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["hz"] == detect.MOTION_HZ
    assert payload["points"] == len(payload["values"]) == summary["points"]
    #: 5Hz × 时长:ffmpeg 的 fps 滤镜出 duration × hz 帧,而 tblend 要前一帧、少一个。
    assert summary["points"] == pytest.approx(duration * detect.MOTION_HZ, abs=1)
    assert summary["digest"] == track.digest_of(path.read_bytes())
    assert summary["digest"] == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    assert payload["duration"] == pytest.approx(duration, abs=0.05)


@needs_ffmpeg
def test_曲线是原样的_现算的每镜中位数和库里一致(video) -> None:
    """③ 存下来的曲线就是 `shots[].motion` 的来源:拿它按同一套掐两头重算一遍,一个数都不差。"""
    with SessionLocal() as db:
        asset = db.get(Asset, video["id"])
        row = breakdowns.measure_into(db, asset, created_by=None, lang="zh")
        db.commit()
        shots = [dict(shot) for shot in row.shots]
        folder = breakdowns.shots_dir(asset)
    values = json.loads((folder / "track.json").read_text(encoding="utf-8"))["values"]
    assert values, "不该是空曲线"
    for shot in shots:
        assert shot["motion"] == detect.shot_motion(values, shot["start"], shot["end"]), shot["id"]


@needs_ffmpeg
def test_重拆覆盖曲线(video) -> None:
    """⑤ 和帧、联系表一起进 `shots.new/` 再换:重拆之后盘上那份就是这一次量的。"""
    with SessionLocal() as db:
        asset = db.get(Asset, video["id"])
        first = breakdowns.measure_into(db, asset, created_by=None, lang="zh")
        db.commit()
        before = dict(first.motion_track)
        folder = breakdowns.shots_dir(asset)
    #: 把旧的动过(内容和摘要都对不上了):重拆若不覆盖,它就会带着这份旧内容留在那儿。
    track.track_file(folder).write_text('{"hz": 1, "values": [9.0]}', encoding="utf-8")
    assert track.read_track(folder, expect_digest=before["digest"]) is None, "动过的那份自己都认不出来"

    with SessionLocal() as db:
        asset = db.get(Asset, video["id"])
        breakdowns.measure_into(db, asset, created_by=None, lang="zh", threshold=0.15)
        db.commit()
    with SessionLocal() as db:
        rows = db.query(ShotBreakdown).filter_by(asset_id=video["id"]).all()
        assert len(rows) == 1, "一份视频只留一份镜头表"
        after = dict(rows[0].motion_track)
    assert after["digest"] == track.digest_of(track.track_file(folder).read_bytes())
    assert track.read_track(folder, expect_digest=after["digest"]) is not None, "盘上那份要重新认得出来"
    assert json.loads(track.track_file(folder).read_text(encoding="utf-8"))["values"] != [9.0], "旧的那份被换掉了"
    assert after["points"] == before["points"], "同一条片子,点数不该变"


# --------------------------------------------------------------------------------------
# ②④ 对外:全量、时间轴、没有曲线也不炸
# --------------------------------------------------------------------------------------

@needs_ffmpeg
def test_曲线接口交出全量和时间轴(client, video) -> None:
    shape = _break_down(client, video)
    body = client.get(f"/api/assets/{video['id']}/shots/track")
    assert body.status_code == 200, body.text
    curve = body.json()
    assert set(curve) == {"asset_id", "status", "hz", "points", "duration", "first_sample_seconds",
                          "sample_interval_seconds", "digest", "values"}, "接口形状就是这个,不多不少"
    assert curve["asset_id"] == video["id"] and curve["status"] == "ready"
    assert curve["hz"] == detect.MOTION_HZ
    assert curve["points"] == len(curve["values"]) == shape["motion_track"]["points"]
    assert curve["points"] == pytest.approx(shape["meta"]["duration"] * detect.MOTION_HZ, abs=1)
    assert curve["duration"] == pytest.approx(shape["meta"]["duration"], abs=0.05)
    #: 时间轴约定:第 i 个采样在 (i + 1) / hz 秒处 —— 第 0 个在 1/hz,相邻差 1/hz。
    assert curve["first_sample_seconds"] == pytest.approx(1 / detect.MOTION_HZ)
    assert curve["sample_interval_seconds"] == pytest.approx(1 / detect.MOTION_HZ)
    assert curve["digest"] == shape["motion_track"]["digest"], "读镜头表那一次拿到的摘要和这条路上的一致"
    assert all(isinstance(value, float) for value in curve["values"]), "曲线是数,机器读得了"
    #: 刀口不在这里重复一遍(它在 shots[].start/end)。
    assert "cuts" not in curve and "shots" not in curve


@needs_ffmpeg
def test_镜头表里带上曲线的摘要(client, video) -> None:
    """"这份表量到的曲线有多少点、摘要是谁"要在读镜头表那一次就有 —— 界面据此决定画不画节奏条。"""
    shape = _break_down(client, video)
    assert shape["motion_track"] == {
        "hz": detect.MOTION_HZ,
        "points": shape["motion_track"]["points"],
        "digest": shape["motion_track"]["digest"],
    }
    assert shape["motion_track"]["points"] > 0
    assert shape["motion_track"]["digest"].startswith("sha256:")


def test_没拆过的视频读曲线也是200(client, video) -> None:
    body = client.get(f"/api/assets/{video['id']}/shots/track")
    assert body.status_code == 200, "「还没有曲线」是一次正常的回答,不是 404"
    curve = body.json()
    assert curve["status"] == "none" and curve["values"] == [] and curve["points"] == 0


def test_看不到的素材还是404(client) -> None:
    assert client.get("/api/assets/no-such-asset/shots/track").status_code == 404


@needs_ffmpeg
def test_老行没有曲线那一栏也不炸(client, video) -> None:
    """曲线是这一版才留的:此前量的行没有 `motion_track`(默认 `{}`),读它要照常出镜头表。"""
    shots = [{"id": "S01", "start": 0.0, "end": 4.0, "seconds": 4.0, "motion": 0.5}]
    with SessionLocal() as db:
        db.add(ShotBreakdown(asset_id=video["id"], workspace_id=video["workspace_id"], lang="zh",
                             params={}, meta={"duration": 4.0}, cuts=[], shots=shots, sheets=[]))
        db.commit()

    shape = client.get(f"/api/assets/{video['id']}/shots").json()
    assert shape["status"] == "ready" and shape["motion_track"] == {}
    curve = client.get(f"/api/assets/{video['id']}/shots/track").json()
    assert curve["status"] == "none" and curve["values"] == []


@needs_ffmpeg
def test_曲线文件丢了要说清楚_而不是假装没有(client, video) -> None:
    _break_down(client, video)
    with SessionLocal() as db:
        asset = db.get(Asset, video["id"])
        folder = breakdowns.shots_dir(asset)
        recorded = dict(breakdowns.breakdown_for(db, video["id"]).motion_track)
    track.track_file(folder).unlink()

    curve = client.get(f"/api/assets/{video['id']}/shots/track").json()
    assert curve["status"] == "missing", "库里记着一条曲线、盘上却没有 —— 这两种「没有」要分得开"
    assert curve["values"] == []
    assert curve["points"] == recorded["points"], "记下的事实照样交回去,人知道该重拆一次"
    assert curve["digest"] == recorded["digest"]
    assert client.get(f"/api/assets/{video['id']}/shots").json()["status"] == "ready", "镜头表本身还在"


@needs_ffmpeg
def test_被人动过的曲线当它不在(client, video) -> None:
    """摘要取的是文件原样:字节变过就当这条曲线不在 —— 机器证据的价值全在「没被动过」。"""
    _break_down(client, video)
    with SessionLocal() as db:
        asset = db.get(Asset, video["id"])
        path = track.track_file(breakdowns.shots_dir(asset))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["values"][0] = 200.0
    path.write_text(json.dumps(payload), encoding="utf-8")

    curve = client.get(f"/api/assets/{video['id']}/shots/track").json()
    assert curve["status"] == "missing" and curve["values"] == []
