"""转写要挑**转得了的**那个素材,而不是排在最前的那个。

用户点「AI 转写」看到:`422 Unprocessable Content: {"detail":"只有视频或音频素材可以转写"}`,
而他那条时间线上明明有一段录音。

原因是界面按**轨道类型**收素材(第一条视频轨 + 所有音频轨的全部片段),再拿第一个去转写。
而视频轨上完全可以放**图片** —— AI 生成的静图就是这么落上去的。他的 V1 前六段全是 seedream
生成的静态图,音频在 A1。于是它挑中一张图,后端如实拒绝。

轨道类型说明不了素材类型。片段因此要带上 `asset_kind`,界面据它筛。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Asset, Clip, Sequence, Track
from tests.util import fresh_client


def _timeline(client) -> str:
    """一条和用户那条同形状的时间线:视频轨上先放一张图,音频在另一条轨。"""
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project_id = client.post("/api/projects", json={"workspace_id": workspace_id, "name": "P"}).json()["id"]
    with SessionLocal() as db:
        image = Asset(workspace_id=workspace_id, name="生成的静图", kind="image", file_key="a.png")
        audio = Asset(workspace_id=workspace_id, name="录音.webm", kind="audio", file_key="b.webm")
        sequence = Sequence(workspace_id=workspace_id, project_id=project_id, name="主序列")
        db.add_all([image, audio, sequence])
        db.flush()
        video_track = Track(sequence_id=sequence.id, kind="video", name="V1", position=0)
        audio_track = Track(sequence_id=sequence.id, kind="audio", name="A1", position=1)
        db.add_all([video_track, audio_track])
        db.flush()
        db.add(Clip(workspace_id=workspace_id, sequence_id=sequence.id, track_id=video_track.id,
                    asset_id=image.id, timeline_start=0, src_in=0, src_out=3))
        db.add(Clip(workspace_id=workspace_id, sequence_id=sequence.id, track_id=audio_track.id,
                    asset_id=audio.id, timeline_start=0, src_in=0, src_out=3))
        db.commit()
        return sequence.id


def test_clips_carry_the_asset_kind(client=None) -> None:
    """界面靠它筛 —— 而 asset_id 本身说明不了这一段是图还是视频。"""
    client = fresh_client()
    sequence_id = _timeline(client)

    payload = client.get(f"/api/sequences/{sequence_id}").json()
    kinds = {
        clip["asset_kind"]
        for track in payload["tracks"]
        for clip in track["clips"]
    }

    assert kinds == {"image", "audio"}, f"片段没带上素材类型:{kinds}"


def test_the_backend_still_refuses_an_image() -> None:
    """后端这道闸留着 —— 界面挑错了它也得拦住,而且话要说得像人话。"""
    from app.domain.voices import transcription

    client = fresh_client()
    sequence_id = _timeline(client)
    with SessionLocal() as db:
        image = db.query(Asset).filter(Asset.kind == "image").one()
        try:
            transcription.start_transcription(db, image.id, created_by=None)
        except transcription.ASRError as exc:
            assert "视频或音频" in str(exc)
        else:
            raise AssertionError("图片被放行了")
