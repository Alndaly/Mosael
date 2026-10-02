"""数字人成片的 AI 标识(ADR 0028 §5):成片里有数字人片段(生成时带驱动音频)时 ——

- 显式:片头正中一块、整片右上角一行「AI 生成」,**默认开、允许关**;
- 隐式:MP4 元数据里的 AIGC 字段,**总写**,不随显式开关变;
- 没有数字人片段的成片一样都不加。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.db import SessionLocal
from app.db.models import Asset, Clip, GenerationJob, Project, Sequence, Track, Workspace
from app.domain.render import build_plan_for_sequence, digital_human_assets
from app.media.render_executor import build_ffmpeg_command
from tests.util import fresh_client


def _sequence(*, talking: bool) -> str:
    with SessionLocal() as db:
        ws = Workspace(name="W")
        db.add(ws)
        db.flush()
        project = Project(workspace_id=ws.id, name="P")
        db.add(project)
        db.flush()
        clip = Asset(workspace_id=ws.id, project_id=project.id, name="talk.mp4", kind="video", file_key="talk.mp4")
        db.add(clip)
        db.flush()
        roles = [{"asset_id": "face", "role": "first_frame"}] + ([{"asset_id": "line", "role": "driving_audio"}] if talking else [])
        db.add(GenerationJob(workspace_id=ws.id, provider="alibaba", model="wan2.2-s2v", kind="video",
                             request={"source_assets": roles, "parameters": {}}, result_asset_id=clip.id))
        sequence = Sequence(workspace_id=ws.id, project_id=project.id, name="S")
        track = Track(sequence=sequence, kind="video", name="V1", position=0)
        db.add_all([sequence, track])
        db.flush()
        db.add(Clip(workspace_id=ws.id, sequence_id=sequence.id, track_id=track.id, asset_id=clip.id,
                    timeline_start=0, src_in=0, src_out=8))
        db.commit()
        return sequence.id


def test_数字人成片_片头和角上加标识_元数据写_AIGC() -> None:
    fresh_client()
    sequence_id = _sequence(talking=True)
    with SessionLocal() as db:
        plan = build_plan_for_sequence(db, sequence_id, {})
    labels = [(item.start, item.duration, item.text, item.placement) for item in plan.ai_labels]
    assert labels == [(0.0, 3.0, "AI 生成", "center"), (0.0, 8.0, "AI 生成", "top_right")], "片头 3 秒一块,整片角上一行"
    assert plan.text_overlays == (), "标识不是花字"
    keys = dict(plan.output.metadata)
    assert json.loads(keys["AIGC"])["Label"] == "1" and json.loads(keys["AIGC"])["ProduceID"].startswith(sequence_id)
    command = build_ffmpeg_command(plan, lambda key: Path("/tmp") / key, Path("/tmp/out.mp4"))
    assert "-metadata" in command and "+faststart+use_metadata_tags" in command


def test_关掉显式标识_画面上没有_元数据照写() -> None:
    fresh_client()
    sequence_id = _sequence(talking=True)
    with SessionLocal() as db:
        plan = build_plan_for_sequence(db, sequence_id, {"ai_label": False})
    assert plan.ai_labels == ()
    assert "AIGC" in dict(plan.output.metadata)


def test_没有数字人片段_一样都不加() -> None:
    fresh_client()
    sequence_id = _sequence(talking=False)
    with SessionLocal() as db:
        plan = build_plan_for_sequence(db, sequence_id, {})
    assert plan.ai_labels == () and plan.output.metadata == ()
    command = build_ffmpeg_command(plan, lambda key: Path("/tmp") / key, Path("/tmp/out.mp4"))
    assert "-metadata" not in command and "+faststart" in command


def test_驱动音频换成直链的也认得出() -> None:
    fresh_client()
    with SessionLocal() as db:
        ws = Workspace(name="W")
        db.add(ws)
        db.flush()
        asset = Asset(workspace_id=ws.id, name="a.mp4", kind="video", file_key="a.mp4")
        db.add(asset)
        db.flush()
        db.add(GenerationJob(workspace_id=ws.id, provider="alibaba", model="videoretalk", kind="video",
                             request={"source_assets": [], "parameters": {"driving_audio_url": "oss://x"}},
                             result_asset_id=asset.id))
        db.commit()
        assert digital_human_assets(db, {asset.id, "other"}) == {asset.id}
