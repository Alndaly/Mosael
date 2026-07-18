from __future__ import annotations

from pathlib import Path

from app.media.render_executor import build_ffmpeg_command
from app.media.render_plan import build_render_plan
from tests.util import fresh_client

ASSETS = {"a1": {"file_key": "media/a.mp4"}}


def base_clip(**overrides) -> dict:
    clip = {"id": "c1", "asset_id": "a1", "timeline_start": 0, "src_in": 0, "src_out": 8}
    clip.update(overrides)
    return clip


def test_speed_shortens_segment_duration() -> None:
    plan = build_render_plan(
        sequence_id="s", revision=1, width=640, height=360, fps=30,
        clips=[base_clip(speed=2.0)], assets=ASSETS,
    )
    assert plan.video_segments[0].duration == 4.0
    assert plan.timeline_duration == 4.0


def test_fades_clamped_to_clip_duration() -> None:
    plan = build_render_plan(
        sequence_id="s", revision=1, width=640, height=360, fps=30,
        clips=[base_clip(src_out=2, effects={"fade_in": 3.0, "fade_out": 3.0})], assets=ASSETS,
    )
    segment = plan.video_segments[0]
    assert segment.fade_in == segment.fade_out == 1.0


def test_ffmpeg_command_contains_speed_and_fades(monkeypatch) -> None:
    monkeypatch.setattr("app.media.render_executor.probe_has_audio", lambda _: True)
    plan = build_render_plan(
        sequence_id="s", revision=1, width=640, height=360, fps=30,
        clips=[base_clip(speed=3.0, effects={"fade_in": 0.5, "fade_out": 0.5})], assets=ASSETS,
    )
    command = " ".join(build_ffmpeg_command(plan, lambda key: Path("/tmp") / key, Path("/tmp/out.mp4")))
    assert "(PTS-STARTPTS)/3.0" in command
    assert "atempo=2.0,atempo=1.5" in command
    assert "fade=t=in:st=0:d=0.5" in command
    # 8s source at 3x → 2.666667s; fade out starts at duration - 0.5
    assert "fade=t=out:st=2.166667:d=0.5" in command
    assert "afade=t=in:st=0:d=0.5" in command


def test_set_clip_speed_api_with_undo() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "project_id": project["id"], "kind": "video", "name": "S",
              "file_key": "media/s.mp4", "media_info": {"duration": 10}},
    ).json()
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"}
    ).json()
    track = next(t for t in sequence["tracks"] if t["kind"] == "video")
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": track["id"], "asset_id": asset["id"], "timeline_start": 0, "src_in": 0, "src_out": 8},
    ).json()
    clip = next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]

    state = client.patch(f"/api/sequences/{sequence['id']}/clips/{clip['id']}/speed", json={"speed": 2.0}).json()
    updated = next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]
    assert updated["speed"] == 2.0

    assert client.patch(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/speed", json={"speed": 9.0}
    ).status_code == 422

    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert next(t for t in undone["tracks"] if t["kind"] == "video")["clips"][0]["speed"] == 1.0


def test_audio_overlay_fades_in_command(monkeypatch) -> None:
    monkeypatch.setattr("app.media.render_executor.probe_has_audio", lambda _: True)
    plan = build_render_plan(
        sequence_id="s", revision=1, width=640, height=360, fps=30,
        clips=[base_clip()], assets={**ASSETS, "a2": {"file_key": "media/b.m4a"}},
        audio_clips=[{"id": "c2", "asset_id": "a2", "timeline_start": 1, "src_in": 0, "src_out": 4,
                      "gain": 0.8, "effects": {"fade_out": 1.0}}],
    )
    command = " ".join(build_ffmpeg_command(plan, lambda key: Path("/tmp") / key, Path("/tmp/out.mp4")))
    assert "afade=t=out:st=3.0:d=1.0" in command


def _cmd_for_fill(fill_mode: str, monkeypatch) -> str:
    monkeypatch.setattr("app.media.render_executor.probe_has_audio", lambda _: True)
    from app.media.render_executor import build_ffmpeg_command
    from pathlib import Path as _P
    plan = build_render_plan(
        sequence_id="s", revision=1, width=1080, height=1920, fps=30,
        clips=[base_clip()], assets=ASSETS, fill_mode=fill_mode,
    )
    return " ".join(build_ffmpeg_command(plan, lambda k: _P("/media") / k, _P("/out.mp4")))


def test_fill_mode_cover_crops(monkeypatch) -> None:
    cmd = _cmd_for_fill("cover", monkeypatch)
    assert "force_original_aspect_ratio=increase" in cmd and "crop=1080:1920" in cmd


def test_fill_mode_contain_letterboxes(monkeypatch) -> None:
    cmd = _cmd_for_fill("contain", monkeypatch)
    assert "force_original_aspect_ratio=decrease" in cmd and "pad=1080:1920" in cmd


def test_fill_mode_blur_has_blurred_background(monkeypatch) -> None:
    cmd = _cmd_for_fill("blur", monkeypatch)
    assert "gblur" in cmd and "split=2" in cmd
