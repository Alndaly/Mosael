"""给时间线铺背景音乐(sequences.background_music):带货口播成片只剩旁白,维护者说「背景音乐也没了」。"""

from __future__ import annotations

import math
import subprocess

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Clip, Sequence, Track
from app.domain.sequences.background_music import (
    BED_LOUDNESS,
    GAIN_RANGE,
    MUSIC_ROLE,
    UNMEASURED_GAIN,
    bed_gain,
    lay_background_music,
)
from app.media.loudness import integrated_loudness
from app.domain.sequences.errors import SequenceDomainError
from app.domain.sequences.placement import InsertClip, insert_clip
from tests.util import fresh_client, insert_asset


def _timeline_with_narration(seconds: float) -> tuple[str, str]:
    """一条时间线,音频轨上一段 `seconds` 秒的旁白。交回 (工作区, 时间线)。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "成片"}).json()
    voice = insert_asset(ws, kind="audio", name="旁白", media_info={"duration": seconds})
    with SessionLocal() as db:
        track = next(one for one in db.get(Sequence, sequence["id"]).tracks if one.kind == "audio")
        insert_clip(db, sequence["id"], InsertClip(track_id=track.id, asset_id=voice, timeline_start=0.0,
                                                  src_in=0.0, src_out=seconds))
        db.commit()
    return ws, sequence["id"]


def _lay(sequence_id: str, music_id: str):
    from app.db.models import Asset

    with SessionLocal() as db:
        laid = lay_background_music(db, db.get(Sequence, sequence_id), db.get(Asset, music_id), actor_id=None)
        db.commit()
        return laid


def _music_clips(sequence_id: str) -> list[Clip]:
    with SessionLocal() as db:
        tracks = [one for one in db.get(Sequence, sequence_id).tracks if one.role == MUSIC_ROLE]
        assert len(tracks) == 1, "配乐只有一条轨"
        return [clip for clip in tracks[0].clips]


def test_铺到成片末尾_不加速_压低_闪避_淡入淡出() -> None:
    ws, sequence_id = _timeline_with_narration(10.0)
    music = insert_asset(ws, kind="audio", name="配乐", media_info={"duration": 60.0})
    laid = _lay(sequence_id, music)
    assert laid.duration == pytest.approx(10.0) and laid.content_end == pytest.approx(10.0)
    [clip] = _music_clips(sequence_id)
    assert clip.timeline_start == 0 and clip.src_in == 0 and clip.src_out == pytest.approx(10.0)
    assert clip.speed == 1.0, "音乐不能被加速,会变调"
    assert clip.gain == pytest.approx(UNMEASURED_GAIN), "量不出响度(这里没有文件)就原样铺,交给闪避"
    assert clip.effects["fade_in"] > 0 and clip.effects["fade_out"] > 0
    with SessionLocal() as db:
        assert db.get(Track, laid.track_id).duck, "有旁白的地方自动压低"


def test_再铺一次换掉原来那首_不叠第二首() -> None:
    ws, sequence_id = _timeline_with_narration(10.0)
    first = insert_asset(ws, kind="audio", name="第一首", media_info={"duration": 60.0})
    second = insert_asset(ws, kind="audio", name="第二首", media_info={"duration": 60.0})
    _lay(sequence_id, first)
    _lay(sequence_id, second)
    assert [clip.asset_id for clip in _music_clips(sequence_id)] == [second]


def test_配乐比成片短_放完为止不循环() -> None:
    ws, sequence_id = _timeline_with_narration(10.0)
    short = insert_asset(ws, kind="audio", name="短的", media_info={"duration": 4.0})
    assert _lay(sequence_id, short).duration == pytest.approx(4.0)


def test_空时间线和不是音频的素材当场拒() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    empty = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "空"}).json()["id"]
    music = insert_asset(ws, kind="audio", name="配乐", media_info={"duration": 60.0})
    with pytest.raises(SequenceDomainError) as caught:
        _lay(empty, music)
    assert caught.value.key == "seqErr_nothingToScore"

    _ws, sequence_id = _timeline_with_narration(10.0)
    picture = insert_asset(_ws, kind="video", name="画面", media_info={"duration": 10.0})
    with pytest.raises(SequenceDomainError) as caught:
        _lay(sequence_id, picture)
    assert caught.value.key == "seqErr_musicNotAudio"


def _tone(name: str, *, seconds: float, volume_db: float) -> str:
    """数据目录里一段 `seconds` 秒的正弦波,交回存储键。ffmpeg 的 sine 默认幅度 1/8,约 −22 LUFS(和实测那首伴奏差不多);
    `volume_db` 在这上面加减。"""
    key = f"{name}.wav"
    subprocess.run(
        [settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-af", f"volume={volume_db}dB", str(settings.data_dir / key)],
        check=True,
    )
    return key


def test_按这首曲子实际多响定音量_轻的伴奏不被压没() -> None:
    """起初「× 0.35 再闪避」把一首 −22.8 LUFS 的伴奏压到旁白底下 22 dB,成片里听不见。"""
    ws, sequence_id = _timeline_with_narration(10.0)
    quiet = insert_asset(ws, kind="audio", name="轻的伴奏", file_key=_tone("quiet", seconds=20, volume_db=0),
                         media_info={"duration": 20.0})
    loud = insert_asset(ws, kind="audio", name="响的原曲", file_key=_tone("loud", seconds=20, volume_db=8),
                        media_info={"duration": 20.0})
    for music in (quiet, loud):
        laid = _lay(sequence_id, music)
        with SessionLocal() as db:
            from app.db.models import Asset

            measured = integrated_loudness(settings.data_dir / db.get(Asset, music).file_key, seconds=10.0)
        assert measured is not None
        assert measured + 20 * math.log10(laid.gain) == pytest.approx(BED_LOUDNESS, abs=0.2), "垫到同一个响度"
    assert _lay(sequence_id, quiet).gain > _lay(sequence_id, loud).gain


def test_给了音量就照给的() -> None:
    ws, sequence_id = _timeline_with_narration(10.0)
    music = insert_asset(ws, kind="audio", name="配乐", file_key=_tone("given", seconds=20, volume_db=0),
                         media_info={"duration": 20.0})
    from app.db.models import Asset

    with SessionLocal() as db:
        laid = lay_background_music(db, db.get(Sequence, sequence_id), db.get(Asset, music), gain=0.5, actor_id=None)
        db.commit()
    assert laid.gain == 0.5


def test_增益换算_夹在范围里_量不到原样() -> None:
    assert bed_gain(BED_LOUDNESS) == pytest.approx(1.0)
    assert bed_gain(BED_LOUDNESS + 6) == pytest.approx(0.501, abs=0.001)
    assert bed_gain(-90.0) == GAIN_RANGE[1], "几乎无声的不放大几千倍"
    assert bed_gain(10.0) == GAIN_RANGE[0]
    assert bed_gain(None) == UNMEASURED_GAIN


def test_静音和读不了的文件量不出响度(tmp_path) -> None:
    silent = tmp_path / "silent.wav"
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=d=3", str(silent)], check=True)
    assert integrated_loudness(silent) is None
    assert integrated_loudness(tmp_path / "missing.wav") is None
