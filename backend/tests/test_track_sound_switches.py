"""轨道头上的独奏(S)/ 闪避(D)是**声音**的开关。

有人问「S 和 D 是干什么的,点了没反应」。两件事:

- 字幕轨头上也摆着 S。字幕轨没有声音,独奏它的结果是反的 —— 「有轨在独奏」成立,别的轨一律
  闭嘴,预览和成片里所有声音都没了。现在字幕轨不给设这两个标记,老库里的由迁移清掉。
- 最常见的片子是人声在基底视频里、音乐在音频轨上。给音乐按下 D,此前**什么都不发生**:闪避的
  触发源只认音频轨和上层视频轨,基底轨的声音不算。现在它算。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import engine
from app.db.migrations import _migrate_subtitle_tracks_carry_no_sound, _migrate_subtitle_tracks_hide_instead_of_mute
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


def test_a_subtitle_track_cannot_be_muted() -> None:
    """静音也是声音开关。字幕轨不显示用的是隐藏 —— 一个字段不再兼两个意思。"""
    client, seq, track_id = _sequence_with_subtitle_track()
    res = client.patch(f"/api/sequences/{seq}/tracks/{track_id}", json={"muted": True})
    assert res.status_code == 422, res.text
    assert _track(client, seq, track_id)["muted"] is False


def test_a_subtitle_track_can_be_hidden_and_locked_with_undo() -> None:
    client, seq, track_id = _sequence_with_subtitle_track()
    res = client.patch(f"/api/sequences/{seq}/tracks/{track_id}", json={"hidden": True, "locked": True, "solo": False})
    assert res.status_code == 200, res.text
    track = _track(client, seq, track_id)
    assert track["hidden"] is True and track["locked"] is True and track["muted"] is False

    client.post(f"/api/sequences/{seq}/undo")
    track = _track(client, seq, track_id)
    assert track["hidden"] is False and track["locked"] is False
    client.post(f"/api/sequences/{seq}/redo")
    assert _track(client, seq, track_id)["hidden"] is True


def test_only_subtitle_tracks_can_be_hidden() -> None:
    """隐藏目前只在字幕上有定义;给别的轨存下来也不会起作用,不如当场说清楚。"""
    client, seq, _track_id = _sequence_with_subtitle_track()
    sequence = client.get(f"/api/sequences/{seq}").json()
    video_id = next(t["id"] for t in sequence["tracks"] if t["kind"] == "video")
    res = client.patch(f"/api/sequences/{seq}/tracks/{video_id}", json={"hidden": True})
    assert res.status_code == 422, res.text


def test_a_removed_hidden_subtitle_track_comes_back_hidden() -> None:
    client, seq, track_id = _sequence_with_subtitle_track()
    client.patch(f"/api/sequences/{seq}/tracks/{track_id}", json={"hidden": True})
    client.delete(f"/api/sequences/{seq}/tracks/{track_id}")
    client.post(f"/api/sequences/{seq}/undo")
    assert _track(client, seq, track_id)["hidden"] is True


def _operations(sequence_id: str) -> list[tuple[str, dict]]:
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT kind, payload FROM sequence_operations WHERE sequence_id = :s ORDER BY created_at"),
            {"s": sequence_id},
        ).all()
    return [(kind, json.loads(payload) if isinstance(payload, str) else payload) for kind, payload in rows]


def test_migration_turns_subtitle_mute_into_hidden() -> None:
    """老库:字幕轨借 muted 表示「不显示」,操作日志里记的也是 muted。迁移后两处都说 hidden。"""
    client, seq, track_id = _sequence_with_subtitle_track()
    audio = client.post(f"/api/sequences/{seq}/tracks", json={"kind": "audio"}).json()
    audio_id = next(t["id"] for t in audio["tracks"] if t["kind"] == "audio")
    client.patch(f"/api/sequences/{seq}/tracks/{audio_id}", json={"muted": True})
    client.patch(f"/api/sequences/{seq}/tracks/{track_id}", json={"hidden": True})
    # 还原成老库的样子:字幕轨上是 muted,日志里的状态没有 hidden 这一格。
    with engine.begin() as conn:
        conn.execute(text("UPDATE tracks SET muted = 1, hidden = 0 WHERE id = :id"), {"id": track_id})
        for op_id, raw in conn.execute(
            text("SELECT id, payload FROM sequence_operations WHERE sequence_id = :s AND kind = 'set_track_state'"),
            {"s": seq},
        ).all():
            payload = json.loads(raw) if isinstance(raw, str) else dict(raw)
            for state in (payload, payload["previous"]):
                if payload["track_id"] == track_id:
                    state["muted"] = state["hidden"]
                del state["hidden"]
            conn.execute(
                text("UPDATE sequence_operations SET payload = :p WHERE id = :id"),
                {"p": json.dumps(payload), "id": op_id},
            )

    _migrate_subtitle_tracks_hide_instead_of_mute()
    _migrate_subtitle_tracks_hide_instead_of_mute()  # 重跑什么都不做

    subtitle = _track(client, seq, track_id)
    assert subtitle["hidden"] is True and subtitle["muted"] is False
    # 音频轨的静音是真的静音,不动。
    kept = _track(client, seq, audio_id)
    assert kept["muted"] is True and kept["hidden"] is False
    states = {payload["track_id"]: payload for kind, payload in _operations(seq) if kind == "set_track_state"}
    assert states[track_id]["hidden"] is True and states[track_id]["muted"] is False
    assert states[track_id]["previous"] == {**states[track_id]["previous"], "hidden": False, "muted": False}
    assert states[audio_id]["muted"] is True and states[audio_id]["hidden"] is False
    # 改写过的日志撤得回去:撤销那次隐藏,字幕重新显示。
    client.post(f"/api/sequences/{seq}/undo")
    assert _track(client, seq, track_id)["hidden"] is False


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
