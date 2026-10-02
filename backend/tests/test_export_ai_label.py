"""AI 生成内容的标识(ADR 0028 §5、《人工智能生成合成内容标识办法》):成片里用了 AI 生成 / 合成的素材时 ——

- 显式:片头正中一块、整片右上角一行「AI 生成」,**默认开、允许关**;
- 隐式:成片元数据里的 AIGC 字段,**总写**,不随显式开关变,而且 remux / 转码之后还在;
- 一份 AI 素材都没有的成片一样都不加。

「AI 素材」不只数字人:文生 / 图生视频、AI 图片、AI 音乐、配音(含克隆音色)、播客对话、数字人拼出的整段。
此前只认数字人,其余的进了成片什么标识都没有。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Clip, GenerationJob, Project, Sequence, Track, Workspace
from app.domain.render import aigc_metadata, ai_generated_assets, build_plan_for_sequence
from app.media.render_executor import build_ffmpeg_command, execute_render
from app.media.render_plan import build_render_plan
from tests.util import fresh_client


def _sequence(*, video: str = "plain", voice: str | None = None, voice_muted: bool = False) -> str:
    """一条 8 秒的时间线:视频轨一段画面,可选一条音频轨上的一段声音。

    video:plain(自己导入的)/ i2v(图生视频的产出)/ talking(数字人:生成时带驱动音频)。
    voice:None / tts(配音)/ imported(自己录的)。"""
    with SessionLocal() as db:
        ws = Workspace(name="W")
        db.add(ws)
        db.flush()
        project = Project(workspace_id=ws.id, name="P")
        db.add(project)
        db.flush()
        #: 「是不是 AI 做的」登记时就定下了(生成任务的产出、配音都带 ai_generated=True,见 assets/lineage)。
        picture = Asset(workspace_id=ws.id, project_id=project.id, name="v.mp4", kind="video", file_key="v.mp4",
                        source="generated" if video != "plain" else "imported", ai_generated=video != "plain")
        db.add(picture)
        db.flush()
        if video != "plain":
            roles = [{"asset_id": "face", "role": "first_frame"}]
            if video == "talking":
                roles.append({"asset_id": "line", "role": "driving_audio"})
            db.add(GenerationJob(workspace_id=ws.id, provider="alibaba", model="wan2.2-s2v", kind="video",
                                 request={"source_assets": roles, "parameters": {}}, result_asset_id=picture.id))
        sequence = Sequence(workspace_id=ws.id, project_id=project.id, name="S")
        v1 = Track(sequence=sequence, kind="video", name="V1", position=0)
        db.add_all([sequence, v1])
        db.flush()
        db.add(Clip(workspace_id=ws.id, sequence_id=sequence.id, track_id=v1.id, asset_id=picture.id,
                    timeline_start=0, src_in=0, src_out=8))
        if voice:
            sound = Asset(workspace_id=ws.id, project_id=project.id, name="a.wav", kind="audio", file_key="a.wav",
                          source="tts" if voice == "tts" else "imported", ai_generated=voice == "tts")
            a1 = Track(sequence=sequence, kind="audio", name="A1", position=1)
            db.add_all([sound, a1])
            db.flush()
            db.add(Clip(workspace_id=ws.id, sequence_id=sequence.id, track_id=a1.id, asset_id=sound.id,
                        timeline_start=0, src_in=0, src_out=4, muted=voice_muted))
        db.commit()
        return sequence.id


def _plan(sequence_id: str, params: dict | None = None):
    with SessionLocal() as db:
        return build_plan_for_sequence(db, sequence_id, params if params is not None else {})


def test_数字人成片_片头和角上加标识_元数据写_AIGC() -> None:
    fresh_client()
    sequence_id = _sequence(video="talking")
    plan = _plan(sequence_id)
    labels = [(item.start, item.duration, item.text, item.placement) for item in plan.ai_labels]
    assert labels == [(0.0, 3.0, "AI 生成", "center"), (0.0, 8.0, "AI 生成", "top_right")], "片头 3 秒一块,整片角上一行"
    assert plan.text_overlays == (), "标识不是花字"
    aigc = json.loads(dict(plan.output.metadata)["comment"])["AIGC"]
    assert aigc["Label"] == "1" and aigc["ProduceID"].startswith(sequence_id)
    command = build_ffmpeg_command(plan, lambda key: Path("/tmp") / key, Path("/tmp/out.mp4"))
    assert "-metadata" in command
    assert "+faststart" in command and "+faststart+use_metadata_tags" not in command, "自定义键 remux 后会丢,只写标准键"


@pytest.mark.parametrize(("video", "voice"), [("i2v", None), ("plain", "tts")], ids=["图生视频", "AI配音"])
def test_不是数字人的_AI_素材也加标识(video, voice) -> None:
    fresh_client()
    plan = _plan(_sequence(video=video, voice=voice))
    assert len(plan.ai_labels) == 2
    assert "AIGC" in json.loads(dict(plan.output.metadata)["comment"])


def test_静音的_AI_配音不进成片_不算() -> None:
    fresh_client()
    plan = _plan(_sequence(voice="tts", voice_muted=True))
    assert plan.ai_labels == () and plan.output.metadata == ()


def test_关掉显式标识_画面上没有_元数据照写() -> None:
    fresh_client()
    plan = _plan(_sequence(video="talking"), {"ai_label": False})
    assert plan.ai_labels == ()
    assert "AIGC" in json.loads(dict(plan.output.metadata)["comment"])


def test_一份_AI_素材都没有_一样都不加() -> None:
    fresh_client()
    plan = _plan(_sequence(voice="imported"))
    assert plan.ai_labels == () and plan.output.metadata == ()
    command = build_ffmpeg_command(plan, lambda key: Path("/tmp") / key, Path("/tmp/out.mp4"))
    assert "-metadata" not in command and "+faststart" in command


def test_哪些素材算_AI_生成() -> None:
    """看登记时定下的 ai_generated,不看来源名:截帧、导出这些 generated / exported 来源的,只要没含 AI 就不算。"""
    fresh_client()
    with SessionLocal() as db:
        ws = Workspace(name="W")
        db.add(ws)
        db.flush()

        def asset(source: str, ai: bool) -> str:
            one = Asset(workspace_id=ws.id, name="x", kind="video", file_key="x", source=source, ai_generated=ai)
            db.add(one)
            db.flush()
            return one.id

        made = {asset("generated", True), asset("tts", True), asset("podcast", True), asset("digital_human", True),
                asset("exported", True)}
        plain = {asset("imported", False), asset("generated", False), asset("exported", False)}
        db.commit()
        assert ai_generated_assets(db, made | plain | {"missing"}) == made


@pytest.mark.skipif(shutil.which(settings.ffmpeg) is None, reason="ffmpeg not installed")
def test_隐式标识_remux_和转码之后还读得出来(tmp_path) -> None:
    """平台转码、用户自己 `ffmpeg -c copy` 一遍:自定义的 mdta 键会丢(审查实测),标准键的 comment 还在。"""
    def comment(path: Path) -> dict:
        tags = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", str(path)],
                                         capture_output=True, text=True, check=True).stdout)["format"].get("tags", {})
        return json.loads({key.lower(): value for key, value in tags.items()}["comment"])["AIGC"]

    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=64x36:r=10:d=1",
                    "-pix_fmt", "yuv420p", str(tmp_path / "v.mp4")], check=True, timeout=30)
    metadata = aigc_metadata(SimpleNamespace(id="seq-1", revision=7))
    plan = build_render_plan(sequence_id="seq-1", revision=7, width=64, height=36, fps=10,
                             clips=[{"id": "c", "asset_id": "v", "timeline_start": 0, "src_in": 0, "src_out": 1}],
                             assets={"v": {"file_key": "v.mp4"}}, metadata=metadata)
    out = tmp_path / "out.mp4"
    execute_render(plan, lambda key: tmp_path / key, out)
    assert comment(out)["ProduceID"] == "seq-1:7"
    for name, codec in (("remux.mp4", ["-c", "copy"]), ("remux.mov", ["-c", "copy"]), ("transcoded.mp4", ["-c:v", "libx264"])):
        again = tmp_path / name
        subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-i", str(out), *codec, str(again)], check=True, timeout=60)
        assert comment(again)["Label"] == "1", f"{name} 之后 AIGC 标识没了"
