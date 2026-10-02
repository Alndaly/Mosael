"""分离音频:声音带着它的淡入淡出和音量曲线走;重做时背景音素材删了也不卡住。

此前分出来的音频片段只带速度和音量:淡入淡出、音量关键帧都没了,而视频片段被静音,那份设置再也
听不见。重做按改动日志重建那一段,译配的背景音素材删掉之后要还成脱机占位(见 undo/rows)。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.domain.sequences.operations import DetachClipAudio, detach_clip_audio
from tests.util import fresh_client, insert_asset


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()["id"]
    sequence = client.post("/api/sequences", json={"workspace_id": ws, "project_id": project, "name": "S"}).json()
    seq = sequence["id"]
    track = next(t["id"] for t in sequence["tracks"] if t["kind"] == "video")
    video = insert_asset(ws, kind="video", name="v", file_key="x", media_info={"duration": 30})
    state = client.post(f"/api/sequences/{seq}/clips", json={
        "track_id": track, "asset_id": video, "timeline_start": 0, "src_in": 0, "src_out": 10}).json()
    clip = next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]["id"]
    return client, ws, seq, clip


def _audio_clips(state: dict) -> list[dict]:
    return [c for t in state["tracks"] if t["kind"] == "audio" for c in t["clips"]]


def test_分离出的音频带着淡入淡出和音量曲线_画面那一侧的留在视频上() -> None:
    client, _ws, seq, clip = _setup()
    effects = {"fade_in": 1.5, "fade_out": 2.0, "gain_keyframes": [{"t": 0, "gain": 0}, {"t": 1, "gain": 1}],
               "video_fade_in": 1.0, "filter": "bw"}
    assert client.patch(f"/api/sequences/{seq}/clips/{clip}/effects", json={"effects": effects}).status_code == 200
    state = client.post(f"/api/sequences/{seq}/clips/{clip}/detach-audio").json()
    (audio,) = _audio_clips(state)
    assert audio["effects"] == {"fade_in": 1.5, "fade_out": 2.0,
                                "gain_keyframes": [{"t": 0.0, "gain": 0.0}, {"t": 1.0, "gain": 1.0}]}

    undone = client.post(f"/api/sequences/{seq}/undo").json()
    assert _audio_clips(undone) == []
    redone = client.post(f"/api/sequences/{seq}/redo").json()
    assert _audio_clips(redone)[0]["effects"] == audio["effects"]


def test_背景音素材删了之后重做_还回脱机占位而不是卡住() -> None:
    client, ws, seq, clip = _setup()
    background = insert_asset(ws, kind="audio", name="bg.wav", file_key="", media_info={"duration": 10})
    with SessionLocal() as db:
        detach_clip_audio(db, seq, DetachClipAudio(clip_id=clip, audio_asset_id=background))
        db.commit()
    assert client.post(f"/api/sequences/{seq}/undo").status_code == 200
    assert client.delete(f"/api/assets/{background}").status_code == 204
    redone = client.post(f"/api/sequences/{seq}/redo")
    assert redone.status_code == 200, redone.text
    (audio,) = _audio_clips(redone.json())
    assert audio["offline_asset"]["name"] == "bg.wav"
