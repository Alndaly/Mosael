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


_AUDIO_ASSETS = {"a": {"file_key": "a"}, "m": {"file_key": "m"}, "v": {"file_key": "v"}}
_BASE_CLIP = [{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 10}]


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_overlay_video_audio_mixed_but_silent_source_skipped(tmp_path) -> None:
    """An overlay video-track clip's own audio is mixed over the base (marked optional so the
    executor probes it); an optional source with no audio stream is skipped, not fatal."""
    from app.media.render_executor import build_ffmpeg_command

    tone = tmp_path / "tone.m4a"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(tone)],
        check=True, timeout=30,
    )
    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=_BASE_CLIP, assets={"a": {"file_key": "a"}, "tone": {"file_key": "tone.m4a"}, "sil": {"file_key": "sil"}},
        audio_clips=[
            {"id": "ov", "asset_id": "tone", "timeline_start": 0, "src_in": 0, "src_out": 2, "optional": True},
            {"id": "silent", "asset_id": "sil", "timeline_start": 0, "src_in": 0, "src_out": 2, "optional": True},
        ],
    )
    assert [a.optional for a in plan.audio_overlays] == [True, True]
    resolve = lambda key: (tmp_path / key) if key == "tone.m4a" else Path("/nonexistent/" + key)
    graph = " ".join(build_ffmpeg_command(plan, resolve, tmp_path / "o.mp4"))
    assert "amix=inputs=2" in graph  # base + tone only; the silent (missing-audio) overlay was skipped


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_image_overlay_is_looped_even_without_keyframes(tmp_path) -> None:
    """图片作**叠层**且没有关键帧时也必须 -loop。

    单帧图片时间戳不推进,叠加用的 enable='between(t,…)' 窗口永不命中 → 该图片叠层整段不显示
    (逐帧像素校验抓到的真实 bug)。此前只在"有关键帧"时才 loop,恰好漏掉最常见的静态贴图。"""
    from app.media.render_executor import build_ffmpeg_command

    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=[{"id": "bg", "asset_id": "vid", "timeline_start": 0, "src_in": 0, "src_out": 3}],
        assets={"vid": {"file_key": "bg.mp4"}, "pic": {"file_key": "pic.png"}},
        overlay_clips=[
            {
                "id": "ov", "asset_id": "pic", "timeline_start": 0.5, "src_in": 0, "src_out": 2,
                # 无 keyframes —— 正是此前漏掉 loop 的那条路径
                "transform": {"scale": 0.5, "x": 0, "y": 0, "rotation": 0, "opacity": 1},
            }
        ],
    )
    cmd = build_ffmpeg_command(plan, lambda key: Path("/x/" + key), tmp_path / "o.mp4")
    # 图片叠层的输入前必须紧跟 -loop 1(在它自己的 -i 之前)
    idx = cmd.index("/x/pic.png")
    assert "-loop" in cmd[max(0, idx - 5) : idx], f"image overlay not looped: {cmd[max(0, idx - 5): idx + 1]}"


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_base_image_is_looped_so_overlays_enable_over_it(tmp_path) -> None:
    """A base-track IMAGE must be fed as looped multi-frame video, not a single frame. A single
    frame freezes the base timestamp, so an overlay's enable='between(t,...)' never activates over
    the image segment — transformed / picture-in-picture overlays vanish over an image background in
    the export (they render fine over video/gap segments, whose timestamps advance)."""
    from app.media.render_executor import build_ffmpeg_command

    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=[{"id": "bg", "asset_id": "img", "timeline_start": 0, "src_in": 0, "src_out": 5}],
        assets={"img": {"file_key": "bg.png"}, "ov": {"file_key": "ov.mp4"}},
        overlay_clips=[
            {
                "id": "pip", "asset_id": "ov", "timeline_start": 1, "src_in": 0, "src_out": 3,
                "transform": {"scale": 0.5, "x": 0.3, "y": 0.3, "rotation": 0, "opacity": 1},
            }
        ],
    )
    cmd = build_ffmpeg_command(plan, lambda key: Path("/x/" + key), tmp_path / "o.mp4")
    joined = " ".join(cmd)
    # The base image input carries -loop 1 (so it produces real frames across its duration)…
    assert "-loop" in cmd and "bg.png" in joined
    # …and the transformed overlay's enable window is present to gate over it.
    assert "enable='between(t," in joined


def test_solo_silences_non_soloed_audio_and_base() -> None:
    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=_BASE_CLIP, assets=_AUDIO_ASSETS,
        audio_clips=[
            {"id": "m1", "asset_id": "m", "timeline_start": 0, "src_in": 0, "src_out": 5, "solo": True, "duck": False},
            {"id": "m2", "asset_id": "m", "timeline_start": 0, "src_in": 0, "src_out": 5, "solo": False, "duck": False},
        ],
        solo_active=True, mute_base_audio=True,
    )
    assert len(plan.audio_overlays) == 1  # only the soloed clip survives
    assert plan.mute_base_audio is True


def test_duck_windows_from_overlapping_non_ducked_clip() -> None:
    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=_BASE_CLIP, assets=_AUDIO_ASSETS,
        audio_clips=[
            # music (ducked) spans 0..10; voice (not ducked) spans 2..5 → duck window (2,5).
            {"id": "music", "asset_id": "m", "timeline_start": 0, "src_in": 0, "src_out": 10, "solo": False, "duck": True},
            {"id": "voice", "asset_id": "v", "timeline_start": 2, "src_in": 0, "src_out": 3, "solo": False, "duck": False},
        ],
    )
    music = next(a for a in plan.audio_overlays if a.duration == 10)
    voice = next(a for a in plan.audio_overlays if a.duration == 3)
    assert music.duck_windows == ((2.0, 5.0),)
    assert voice.duck_windows == ()  # the key clip itself isn't ducked


def test_duck_and_solo_in_command() -> None:
    from app.media.render_executor import build_ffmpeg_command

    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=_BASE_CLIP, assets=_AUDIO_ASSETS,
        audio_clips=[
            {"id": "music", "asset_id": "m", "timeline_start": 0, "src_in": 0, "src_out": 10, "solo": False, "duck": True},
            {"id": "voice", "asset_id": "v", "timeline_start": 2, "src_in": 0, "src_out": 3, "solo": False, "duck": False},
        ],
        mute_base_audio=True,
    )
    graph = " ".join(build_ffmpeg_command(plan, lambda key: Path(f"/x/{key}"), Path("/tmp/o.mp4")))
    assert "volume=enable='between(t,2.0,5.0)':volume=0.3" in graph  # music ducked over voice
    assert "anullsrc" in graph  # base audio silenced by solo


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
    assert "overlay=x='80':y='45'" in graph  # centred: 160−80, 90−45


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
    assert "overlay=x='240':y='45'" in graph  # cx=(0.5+0.5)·320=320 → 320−80


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
def test_export_ducks_and_solos_audio(tmp_path: Path) -> None:
    """A ducked music track under a voice clip, with the base audio silenced by solo, renders to
    a valid file — exercises the volume-enable duck windows and the anullsrc base-mute path."""
    from app.media.render_executor import execute_render

    def make(name: str, args: list[str]) -> Path:
        path = tmp_path / name
        subprocess.run(["ffmpeg", "-y", "-v", "error", *args, str(path)], check=True, timeout=60)
        return path

    base = make("base.mp4", ["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=6",
                             "-f", "lavfi", "-i", "sine=frequency=200:duration=6",
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"])
    music = make("music.wav", ["-f", "lavfi", "-i", "sine=frequency=440:duration=6"])
    voice = make("voice.wav", ["-f", "lavfi", "-i", "sine=frequency=880:duration=2"])
    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=[{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 6}],
        assets={"a": {"file_key": str(base)}, "m": {"file_key": str(music)}, "v": {"file_key": str(voice)}},
        audio_clips=[
            {"id": "music", "asset_id": "m", "timeline_start": 0, "src_in": 0, "src_out": 6, "duck": True, "solo": False},
            {"id": "voice", "asset_id": "v", "timeline_start": 2, "src_in": 0, "src_out": 2, "duck": False, "solo": False},
        ],
        mute_base_audio=True,
    )
    music_item = next(a for a in plan.audio_overlays if a.duration == 6)
    assert music_item.duck_windows == ((2.0, 4.0),)
    out = tmp_path / "out.mp4"
    execute_render(plan, lambda key: Path(key), out)
    assert out.exists() and out.stat().st_size > 0


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


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_overlays_hold_last_frame_instead_of_dropping_to_black(tmp_path) -> None:
    """叠加层用 eof_action=repeat,不能用 pass。

    叠加流常比它的 enable 窗口短一丁点(输入级 -ss 快进后,解码从 src_in 之后的第一帧起,
    尾巴少了不到一帧)。pass 会在流结束的瞬间放出底层 → 每个叠加片段最后 1~2 帧变黑,
    连续片段之间就是"切换处闪一下黑"(真实工程里 blackdetect 逐个边界都抓到过)。"""
    from app.media.render_executor import build_ffmpeg_command

    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=[{"id": "b", "asset_id": "v", "timeline_start": 0, "src_in": 0, "src_out": 5}],
        assets={"v": {"file_key": "v.mp4"}},
        overlay_clips=[
            {"id": "o1", "asset_id": "v", "timeline_start": 1, "src_in": 2, "src_out": 3,
             "transform": {"scale": 0.5, "x": 0, "y": 0, "rotation": 0, "opacity": 1}},
            {"id": "o2", "asset_id": "v", "timeline_start": 2, "src_in": 3, "src_out": 4,
             "transform": {"scale": 0.5, "x": 0, "y": 0, "rotation": 0, "opacity": 1}},
        ],
    )
    command = " ".join(build_ffmpeg_command(plan, lambda key: Path("/x/" + key), tmp_path / "o.mp4"))
    assert "eof_action=pass" not in command
    assert command.count("eof_action=repeat") >= 2
