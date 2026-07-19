from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.media.render_plan import build_render_plan
from tests.util import fresh_client

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def test_render_plan_includes_overlays_and_audio() -> None:
    assets = {"a": {"file_key": "media/a.mp4"}, "b": {"file_key": "media/b.mp4"}, "m": {"file_key": "media/m.m4a"}}
    plan = build_render_plan(
        sequence_id="s",
        revision=1,
        width=1280,
        height=720,
        fps=30,
        clips=[{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 4}],
        assets=assets,
        overlay_clips=[
            {
                "id": "c2",
                "asset_id": "b",
                "timeline_start": 1,
                "src_in": 0,
                "src_out": 2,
                "transform": {"scale": 0.25, "x": -0.5, "y": 0.5, "rotation": 0, "opacity": 1},
            }
        ],
        audio_clips=[
            {"id": "c3", "asset_id": "m", "timeline_start": 0.5, "src_in": 0, "src_out": 5, "gain": 0.8, "muted": False},
            {"id": "c4", "asset_id": "m", "timeline_start": 0, "src_in": 0, "src_out": 1, "muted": True},
        ],
    )
    assert len(plan.overlays) == 1
    overlay = plan.overlays[0]
    assert (overlay.start, overlay.duration) == (1, 2)
    assert (overlay.transform.scale, overlay.transform.x, overlay.transform.y) == (0.25, -0.5, 0.5)
    assert len(plan.audio_overlays) == 1  # muted clip dropped
    assert plan.audio_overlays[0].gain == 0.8
    assert plan.timeline_duration == 5.5  # extended by the audio tail


def test_overlay_changes_plan_hash() -> None:
    base = dict(
        sequence_id="s", revision=1, width=640, height=360, fps=30,
        clips=[{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 2}],
        assets={"a": {"file_key": "k"}, "b": {"file_key": "k2"}},
    )
    p1 = build_render_plan(**base)
    p2 = build_render_plan(
        **base,
        overlay_clips=[{"id": "c2", "asset_id": "b", "timeline_start": 0, "src_in": 0, "src_out": 1}],
    )
    assert p1.render_plan_hash != p2.render_plan_hash


def test_transform_geometry_in_command() -> None:
    """Lock the transform→overlay-offset math against the preview formula so export parity
    can't silently drift. For a 320×180 frame, scale 0.5 → 160×90; centre (0.5+x·0.5)·W."""
    from app.media.render_executor import build_ffmpeg_command

    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=[{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 2}],
        assets={"a": {"file_key": "a"}, "b": {"file_key": "b"}},
        overlay_clips=[{"id": "c2", "asset_id": "b", "timeline_start": 0, "src_in": 0, "src_out": 2,
                        "transform": {"scale": 0.5, "x": 0, "y": 0}}],
    )
    fc = build_ffmpeg_command(plan, lambda key: Path(f"/x/{key}"), Path("/tmp/o.mp4"))
    graph = fc[fc.index("-filter_complex") + 1]
    assert "scale=160:90" in graph  # 0.5 · (320×180)
    assert "overlay=x=80:y=45" in graph  # centred: 160−80, 90−45


def test_offset_transform_geometry() -> None:
    """x=1 shifts the element centre right by half the frame (translate(x·50%))."""
    from app.media.render_executor import build_ffmpeg_command

    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=[{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 2}],
        assets={"a": {"file_key": "a"}, "b": {"file_key": "b"}},
        overlay_clips=[{"id": "c2", "asset_id": "b", "timeline_start": 0, "src_in": 0, "src_out": 2,
                        "transform": {"scale": 0.5, "x": 1, "y": 0}}],
    )
    fc = build_ffmpeg_command(plan, lambda key: Path(f"/x/{key}"), Path("/tmp/o.mp4"))
    graph = fc[fc.index("-filter_complex") + 1]
    assert "overlay=x=240:y=45" in graph  # cx=(0.5+0.5)·320=320 → 320−80


def setup_project(client: TestClient) -> tuple[dict, dict, dict]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main", "width": 320, "height": 180},
    ).json()
    return ws, project, sequence


def test_add_and_remove_track_with_undo() -> None:
    client = fresh_client()
    _, _, sequence = setup_project(client)

    added = client.post(f"/api/sequences/{sequence['id']}/tracks", json={"kind": "video"}).json()
    names = [track["name"] for track in added["tracks"]]
    assert "V2" in names

    v2 = next(track for track in added["tracks"] if track["name"] == "V2")
    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert "V2" not in [track["name"] for track in undone["tracks"]]

    redone = client.post(f"/api/sequences/{sequence['id']}/redo").json()
    assert "V2" in [track["name"] for track in redone["tracks"]]

    removed = client.delete(f"/api/sequences/{sequence['id']}/tracks/{v2['id']}").json()
    assert "V2" not in [track["name"] for track in removed["tracks"]]


def test_set_clip_effects_undoable() -> None:
    client = fresh_client()
    ws, project, sequence = setup_project(client)
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "project_id": project["id"], "kind": "video", "name": "S",
              "file_key": "media/s.mp4", "media_info": {"duration": 5}},
    ).json()
    track = next(t for t in sequence["tracks"] if t["kind"] == "video")
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": track["id"], "asset_id": asset["id"], "timeline_start": 0, "src_in": 0, "src_out": 5},
    ).json()
    clip = next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]

    updated = client.patch(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/effects",
        json={"effects": {"pip": {"x": 0.05, "y": 0.05, "scale": 0.5}}},
    ).json()
    updated_clip = next(t for t in updated["tracks"] if t["kind"] == "video")["clips"][0]
    assert updated_clip["effects"]["pip"]["scale"] == 0.5

    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    undone_clip = next(t for t in undone["tracks"] if t["kind"] == "video")["clips"][0]
    assert undone_clip["effects"] == {}


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_export_with_pip_overlay_and_music(tmp_path: Path) -> None:
    client = fresh_client()
    ws, project, sequence = setup_project(client)

    def import_media(name: str, args: list[str]) -> dict:
        path = tmp_path / name
        subprocess.run(["ffmpeg", "-y", "-v", "error", *args, str(path)], check=True, timeout=60)
        return client.post(
            "/api/assets/import",
            data={"workspace_id": ws["id"], "project_id": project["id"]},
            files={"file": (name, path.read_bytes())},
        ).json()

    base = import_media("base.mp4", ["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=3",
                                     "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                                     "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"])
    pip = import_media("pip.mp4", ["-f", "lavfi", "-i", "smptebars=size=320x180:rate=30:duration=2",
                                   "-c:v", "libx264", "-pix_fmt", "yuv420p"])
    music = import_media("music.wav", ["-f", "lavfi", "-i", "sine=frequency=880:duration=3"])

    tracks = {track["name"]: track for track in sequence["tracks"]}
    with_v2 = client.post(f"/api/sequences/{sequence['id']}/tracks", json={"kind": "video"}).json()
    v2 = next(track for track in with_v2["tracks"] if track["name"] == "V2")

    client.post(f"/api/sequences/{sequence['id']}/clips",
                json={"track_id": tracks["V1"]["id"], "asset_id": base["id"], "timeline_start": 0, "src_in": 0, "src_out": 3})
    client.post(f"/api/sequences/{sequence['id']}/clips",
                json={"track_id": v2["id"], "asset_id": pip["id"], "timeline_start": 0.5, "src_in": 0, "src_out": 2})
    client.post(f"/api/sequences/{sequence['id']}/clips",
                json={"track_id": tracks["A1"]["id"], "asset_id": music["id"], "timeline_start": 0, "src_in": 0, "src_out": 3})

    job = client.post(f"/api/sequences/{sequence['id']}/export").json()
    deadline = time.time() + 120
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.5)
    assert job["status"] == "succeeded", job.get("error")

    exported = next(a for a in client.get(f"/api/assets?workspace_id={ws['id']}").json() if a["source"] == "exported")
    assert abs(exported["media_info"]["duration"] - 3.0) < 0.2


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_export_applies_clip_transform(tmp_path: Path) -> None:
    """A non-identity transform on both the base clip (scale+offset+rotation+opacity) and an
    overlay must produce a valid render — exercises the full transform filter graph in ffmpeg."""
    from app.media.render_executor import execute_render

    def make(name: str, args: list[str]) -> Path:
        path = tmp_path / name
        subprocess.run(["ffmpeg", "-y", "-v", "error", *args, str(path)], check=True, timeout=60)
        return path

    base = make("base.mp4", ["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=2",
                             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"])
    ov = make("ov.mp4", ["-f", "lavfi", "-i", "smptebars=size=320x180:rate=30:duration=2",
                         "-c:v", "libx264", "-pix_fmt", "yuv420p"])
    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=[{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 2,
                "transform": {"scale": 0.6, "x": 0.2, "y": -0.1, "rotation": 15, "opacity": 0.8}}],
        assets={"a": {"file_key": str(base)}, "b": {"file_key": str(ov)}},
        overlay_clips=[{"id": "c2", "asset_id": "b", "timeline_start": 0, "src_in": 0, "src_out": 2,
                        "transform": {"scale": 0.4, "x": -0.5, "y": 0.5, "rotation": 0, "opacity": 1}}],
    )
    out = tmp_path / "out.mp4"
    execute_render(plan, lambda key: Path(key), out)
    assert out.exists() and out.stat().st_size > 0
