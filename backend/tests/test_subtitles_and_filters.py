from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.media.render_executor import build_ffmpeg_command
from app.media.render_plan import build_render_plan
from tests.util import fresh_client

ASSETS = {"a1": {"file_key": "media/a.mp4"}}


def setup_sequence(client: TestClient) -> dict:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    return client.post(
        "/api/sequences", json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"}
    ).json()


def test_subtitle_track_and_text_clip_lifecycle() -> None:
    client = fresh_client()
    sequence = setup_sequence(client)

    state = client.post(f"/api/sequences/{sequence['id']}/tracks", json={"kind": "subtitle"}).json()
    track = next(t for t in state["tracks"] if t["kind"] == "subtitle")
    assert track["name"] == "S1"

    state = client.post(
        f"/api/sequences/{sequence['id']}/text-clips",
        json={"track_id": track["id"], "text": "大家好", "timeline_start": 1.0, "duration": 2.5},
    ).json()
    clip = next(t for t in state["tracks"] if t["kind"] == "subtitle")["clips"][0]
    assert clip["asset_id"] is None and clip["text_override"] == "大家好"

    state = client.patch(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/text", json={"text": "改过的字幕"}
    ).json()
    updated = next(t for t in state["tracks"] if t["kind"] == "subtitle")["clips"][0]
    assert updated["text_override"] == "改过的字幕"

    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert next(t for t in undone["tracks"] if t["kind"] == "subtitle")["clips"][0]["text_override"] == "大家好"

    # undo the insert too — clip disappears; redo brings it back with its text
    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert next(t for t in undone["tracks"] if t["kind"] == "subtitle")["clips"] == []
    redone = client.post(f"/api/sequences/{sequence['id']}/redo").json()
    assert next(t for t in redone["tracks"] if t["kind"] == "subtitle")["clips"][0]["text_override"] == "大家好"


def test_text_clip_rejected_on_video_track() -> None:
    client = fresh_client()
    sequence = setup_sequence(client)
    video = next(t for t in sequence["tracks"] if t["kind"] == "video")
    res = client.post(
        f"/api/sequences/{sequence['id']}/text-clips",
        json={"track_id": video["id"], "text": "x", "timeline_start": 0, "duration": 1},
    )
    assert res.status_code == 422


def test_plan_collects_subtitles_and_srt_burnin(tmp_path) -> None:
    plan = build_render_plan(
        sequence_id="s", revision=1, width=640, height=360, fps=30,
        clips=[{"id": "c1", "asset_id": "a1", "timeline_start": 0, "src_in": 0, "src_out": 8}],
        assets=ASSETS,
        subtitle_clips=[
            {"id": "t1", "asset_id": None, "timeline_start": 1, "src_in": 0, "src_out": 2, "text_override": "你好"},
            {"id": "t2", "asset_id": None, "timeline_start": 4, "src_in": 0, "src_out": 1.5, "text_override": "world"},
        ],
    )
    assert [(s.start, s.text) for s in plan.subtitles] == [(1.0, "你好"), (4.0, "world")]

    out = tmp_path / "out.mp4"
    command = " ".join(build_ffmpeg_command(plan, lambda key: tmp_path / key, out))
    assert "subtitles=filename=" in command
    srt = (tmp_path / "out.srt").read_text(encoding="utf-8")
    assert "00:00:01,000 --> 00:00:03,000" in srt and "你好" in srt


def test_filter_preset_in_plan_and_command(tmp_path) -> None:
    plan = build_render_plan(
        sequence_id="s", revision=1, width=640, height=360, fps=30,
        clips=[{"id": "c1", "asset_id": "a1", "timeline_start": 0, "src_in": 0, "src_out": 8,
                "effects": {"filter": "bw"}}],
        assets=ASSETS,
    )
    assert plan.video_segments[0].filter == "bw"
    command = " ".join(build_ffmpeg_command(plan, lambda key: tmp_path / key, tmp_path / "o.mp4"))
    assert "hue=s=0" in command


def test_unknown_filter_preset_rejected() -> None:
    import pytest

    from app.media.render_plan import RenderPlanError

    with pytest.raises(RenderPlanError):
        build_render_plan(
            sequence_id="s", revision=1, width=640, height=360, fps=30,
            clips=[{"id": "c1", "asset_id": "a1", "timeline_start": 0, "src_in": 0, "src_out": 8,
                    "effects": {"filter": "nope"}}],
            assets=ASSETS,
        )
