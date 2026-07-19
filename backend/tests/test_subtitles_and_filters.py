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


def test_plan_collects_subtitles_and_ass_burnin(tmp_path) -> None:
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
    ass = (tmp_path / "out.ass").read_text(encoding="utf-8")
    assert "Dialogue: 0,0:00:01.00,0:00:03.00,Default" in ass and "你好" in ass


def test_subtitle_style_flows_into_ass(tmp_path) -> None:
    """subtitle_style → ASS Style line: font size, top alignment, opaque box, bold."""
    plan = build_render_plan(
        sequence_id="s", revision=1, width=1920, height=1080, fps=30,
        clips=[{"id": "c1", "asset_id": "a1", "timeline_start": 0, "src_in": 0, "src_out": 4}],
        assets=ASSETS,
        subtitle_clips=[{"id": "t1", "asset_id": None, "timeline_start": 0, "src_in": 0, "src_out": 2, "text_override": "hi"}],
        subtitle_style={"font_size": 48, "color": "#ff0000", "bg_color": "#000000",
                        "bg_opacity": 1.0, "bold": True, "position": "top", "offset": 10},
    )
    build_ffmpeg_command(plan, lambda key: tmp_path / key, tmp_path / "out.mp4")
    ass = (tmp_path / "out.ass").read_text(encoding="utf-8")
    style_line = next(line for line in ass.splitlines() if line.startswith("Style: Default"))
    fields = style_line.split(",")
    assert fields[2] == "48"  # Fontsize
    assert fields[3] == "&H000000FF"  # PrimaryColour = red, opaque
    assert fields[7] == "-1"  # Bold
    assert fields[15] == "3"  # BorderStyle = opaque box (bg_opacity 1.0)
    assert fields[18] == "8"  # Alignment = top-centre
    assert fields[21] == str(round(0.10 * 1080))  # MarginV = 108


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


def grade_command(tmp_path, color: dict) -> str:
    plan = build_render_plan(
        sequence_id="s", revision=1, width=640, height=360, fps=30,
        clips=[{"id": "c1", "asset_id": "a1", "timeline_start": 0, "src_in": 0, "src_out": 8,
                "effects": {"color": color}}],
        assets=ASSETS,
    )
    return " ".join(build_ffmpeg_command(plan, lambda key: tmp_path / key, tmp_path / "o.mp4"))


def test_manual_grade_in_plan_and_command(tmp_path) -> None:
    plan = build_render_plan(
        sequence_id="s", revision=1, width=640, height=360, fps=30,
        clips=[{"id": "c1", "asset_id": "a1", "timeline_start": 0, "src_in": 0, "src_out": 8,
                "effects": {"color": {"brightness": 0.5, "contrast": -0.5, "saturation": 2.5}}}],
        assets=ASSETS,
    )
    assert dict(plan.video_segments[0].grade) == {"brightness": 0.5, "contrast": -0.5, "saturation": 1.0}
    command = " ".join(build_ffmpeg_command(plan, lambda key: tmp_path / key, tmp_path / "o.mp4"))
    assert "contrast=0.500" in command and "brightness=0.500" in command and "saturation=2.000" in command


def test_zero_grade_adds_no_filter(tmp_path) -> None:
    plan = build_render_plan(
        sequence_id="s", revision=1, width=640, height=360, fps=30,
        clips=[{"id": "c1", "asset_id": "a1", "timeline_start": 0, "src_in": 0, "src_out": 8}],
        assets=ASSETS,
    )
    command = " ".join(build_ffmpeg_command(plan, lambda key: tmp_path / key, tmp_path / "o.mp4"))
    assert "eq=" not in command and "curves=" not in command


def test_full_grade_field_mapping(tmp_path) -> None:
    # mibu-video parity: every field family lands in its FFmpeg filter.
    command = grade_command(tmp_path, {
        "exposure": 0.4, "gamma": 0.2, "highlights": 0.5, "blacks": 0.5, "fade": 0.5,
        "temperature": 0.6, "tint": 0.5, "hue": 0.5, "vibrance": 0.5,
        "sharpen": 0.5, "vignette": 0.5,
    })
    assert "brightness=0.200" in command          # exposure folded into brightness factor
    assert "gamma=1.200" in command
    assert "curves=master=" in command            # highlights/blacks/fade tone curve
    assert "hue=h=90.0" in command
    assert "colortemperature=temperature=5000" in command
    assert "vibrance=intensity=1.000" in command
    assert "colorbalance=gm=-0.100" in command
    assert "unsharp=5:5:0.750" in command
    assert "vignette=angle=PI/12.000" in command


def test_lut3d_burned_in_after_grade(tmp_path) -> None:
    plan = build_render_plan(
        sequence_id="s", revision=1, width=640, height=360, fps=30,
        clips=[{"id": "c1", "asset_id": "a1", "timeline_start": 0, "src_in": 0, "src_out": 8,
                "effects": {"color": {"contrast": 0.2, "lut": "lut-1"}}}],
        assets=ASSETS,
        luts={"lut-1": "media/luts/w/lut-1/look.cube"},
    )
    assert plan.video_segments[0].lut == "media/luts/w/lut-1/look.cube"
    command = " ".join(build_ffmpeg_command(plan, lambda key: tmp_path / key, tmp_path / "o.mp4"))
    # lut3d appears, and after the eq= grade in the chain (creative LUT on top).
    assert "lut3d=file=" in command
    assert command.index("eq=") < command.index("lut3d=")


def test_unknown_lut_reference_rejected() -> None:
    import pytest

    from app.media.render_plan import RenderPlanError

    with pytest.raises(RenderPlanError):
        build_render_plan(
            sequence_id="s", revision=1, width=640, height=360, fps=30,
            clips=[{"id": "c1", "asset_id": "a1", "timeline_start": 0, "src_in": 0, "src_out": 8,
                    "effects": {"color": {"lut": "ghost"}}}],
            assets=ASSETS,
        )


def test_cube_parser_validates_size() -> None:
    import pytest

    from app.domain.luts import LutError, parse_cube_size

    good = "TITLE \"x\"\nLUT_3D_SIZE 2\n" + "\n".join(["0 0 0"] * 8)
    assert parse_cube_size(good) == 2

    with pytest.raises(LutError):
        parse_cube_size("# no size here\n0 0 0")
    with pytest.raises(LutError):
        parse_cube_size("LUT_1D_SIZE 16\n0 0 0")
    with pytest.raises(LutError):
        parse_cube_size("LUT_3D_SIZE 4\n0 0 0")  # far too few data rows
