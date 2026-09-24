"""轨道头上的独奏(S)/ 闪避(D)是**声音**的开关。

有人问「S 和 D 是干什么的,点了没反应」。两件事:

- 字幕轨头上也摆着 S。字幕轨没有声音,独奏它的结果是反的 —— 「有轨在独奏」成立,别的轨一律
  闭嘴,预览和成片里所有声音都没了。现在字幕轨不给设这两个标记,老库里的由迁移清掉。
- 最常见的片子是人声在基底视频里、音乐在音频轨上。给音乐按下 D,此前**什么都不发生**:闪避的
  触发源只认音频轨和上层视频轨,基底轨的声音不算。现在它算。
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import engine
from app.db.migrations import _migrate_subtitle_tracks_carry_no_sound
from app.media.render_plan import build_render_plan
from tests.util import fresh_client


def _sequence_with_subtitle_track():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": ws, "name": "P"}).json()
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws, "project_id": project["id"], "name": "S"}
    ).json()
    updated = client.post(f"/api/sequences/{sequence['id']}/tracks", json={"kind": "subtitle"}).json()
    track_id = next(t["id"] for t in updated["tracks"] if t["kind"] == "subtitle")
    return client, sequence["id"], track_id


def _track(client, seq_id: str, track_id: str) -> dict:
    sequence = client.get(f"/api/sequences/{seq_id}").json()
    return next(t for t in sequence["tracks"] if t["id"] == track_id)


def test_a_subtitle_track_cannot_be_soloed_or_ducked() -> None:
    client, seq, track_id = _sequence_with_subtitle_track()
    for body in ({"solo": True}, {"duck": True}):
        res = client.patch(f"/api/sequences/{seq}/tracks/{track_id}", json=body)
        assert res.status_code == 422, res.text
    track = _track(client, seq, track_id)
    assert track["solo"] is False and track["duck"] is False


def test_a_subtitle_track_can_still_be_hidden_and_locked() -> None:
    """拒的只是声音开关;字幕轨的「静音」(隐藏字幕)和锁定照旧。"""
    client, seq, track_id = _sequence_with_subtitle_track()
    res = client.patch(f"/api/sequences/{seq}/tracks/{track_id}", json={"muted": True, "locked": True, "solo": False})
    assert res.status_code == 200, res.text
    track = _track(client, seq, track_id)
    assert track["muted"] is True and track["locked"] is True


def test_migration_clears_solo_and_duck_left_on_subtitle_tracks() -> None:
    client, seq, track_id = _sequence_with_subtitle_track()
    audio = client.post(f"/api/sequences/{seq}/tracks", json={"kind": "audio"}).json()
    audio_id = next(t["id"] for t in audio["tracks"] if t["kind"] == "audio")
    client.patch(f"/api/sequences/{seq}/tracks/{audio_id}", json={"solo": True, "duck": True})
    # 老库里的样子:字幕轨上按下过独奏(那时轨道头还给它摆着 S)。
    with engine.begin() as conn:
        conn.execute(text("UPDATE tracks SET solo = 1, duck = 1 WHERE id = :id"), {"id": track_id})

    _migrate_subtitle_tracks_carry_no_sound()

    subtitle = _track(client, seq, track_id)
    assert subtitle["solo"] is False and subtitle["duck"] is False
    # 音频轨上的标记是用户真的想要的,不动。
    kept = _track(client, seq, audio_id)
    assert kept["solo"] is True and kept["duck"] is True


def _plan(*, base: dict, audio: list[dict], mute_base_audio: bool = False, duck_base_audio: bool = False):
    return build_render_plan(
        sequence_id="s",
        revision=1,
        width=32,
        height=32,
        fps=20,
        clips=[{"id": "base", "asset_id": "v", "timeline_start": 0, "src_in": 0, "src_out": 10, **base}],
        assets={"v": {"file_key": "v.mp4"}, "m": {"file_key": "m.wav"}},
        audio_clips=audio,
        mute_base_audio=mute_base_audio,
        duck_base_audio=duck_base_audio,
    )


MUSIC = {"id": "music", "asset_id": "m", "timeline_start": 0, "src_in": 0, "src_out": 10, "duck": True}


def test_ducked_music_yields_to_the_base_video_sound() -> None:
    plan = _plan(base={"has_audio": True, "src_out": 6}, audio=[MUSIC])
    assert plan.audio_overlays[0].duck_windows == ((0.0, 6.0),)


def test_an_image_or_silenced_base_does_not_duck_music() -> None:
    assert _plan(base={"has_audio": False}, audio=[MUSIC]).audio_overlays[0].duck_windows == ()
    assert _plan(base={"has_audio": True, "muted": True}, audio=[MUSIC]).audio_overlays[0].duck_windows == ()
    # 基底被静音 / 被独奏关掉
    assert _plan(base={"has_audio": True}, audio=[MUSIC], mute_base_audio=True).audio_overlays[0].duck_windows == ()


def test_a_ducked_base_is_not_a_trigger_for_other_ducked_tracks() -> None:
    """基底自己也在让路(译配)时,它不去压同样在让路的音乐 —— 两者都只给配音让路。"""
    plan = _plan(base={"has_audio": True}, audio=[MUSIC], duck_base_audio=True)
    assert plan.audio_overlays[0].duck_windows == ()
    assert plan.base_audio_duck_windows == ()
