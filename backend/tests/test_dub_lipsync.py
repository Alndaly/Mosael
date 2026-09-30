"""译配对口型(ADR 0028 阶段 3「视频翻译 · 改口型」)。

- 切块:每块在模型收得下的长度里,切点优先落在两句之间;没有空当才在上限处硬切;最后一块太短就把上一个切点往前挪;
- 有配音的块交给改口型,一句都没有的块用原片、不花钱;接回整段不带声音,放到最上面一条新视频轨,原片不动;
- 授权没确认、原片变过速、配音轨上没有话,都在动手之前说。
"""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from app.core.unit_of_work import unit_of_work
from app.core.config import settings
from app.db.models import Clip, Project, Sequence, Track, Workspace
from app.domain.assets.importer import register_file_asset
from app.domain.render import build_plan_for_sequence, digital_human_assets
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import dub_lipsync as module
from app.domain.workflows.executors.dub_lipsync import dub_lipsync, plan_chunks
from tests.util import fresh_client


def test_切块_切点落在两句之间_没空当才硬切_最后一块太短往前挪() -> None:
    assert plan_chunks(50, [(1, 10)], 2, 120) == [(0.0, 50)]
    lines = [(0, 50), (60, 110), (130, 200)]
    assert plan_chunks(200, lines, 2, 120) == [(0.0, 120.0), (120.0, 200)], "55 和 120 都是空当,取不超上限的最远那个"
    assert plan_chunks(250, [(0, 250)], 2, 120) == [(0.0, 120.0), (120.0, 240.0), (240.0, 250)], "一直在说话:上限处硬切"
    assert plan_chunks(241, [(0, 241)], 2, 120) == [(0.0, 120.0), (120.0, 239), (239, 241)], "最后一块 1 秒不收:切点往前挪"


def _media(key: str, args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args, str(settings.data_dir / key)], check=True)


@pytest.fixture()
def dubbed(monkeypatch):
    """一条 6 秒原片 + 一条配音轨(第 1 秒、第 4 秒各一句,每句 1 秒)。改口型换成「交回那一块原片」。"""
    fresh_client()
    _media("src.mp4", ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=6", "-f", "lavfi", "-i",
                       "sine=duration=6", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p"])
    _media("line.wav", ["-f", "lavfi", "-i", "sine=frequency=660:duration=1"])
    with unit_of_work() as db:
        ws = Workspace(name="W")
        db.add(ws)
        db.flush()
        project = Project(workspace_id=ws.id, name="P")
        db.add(project)
        db.flush()
        video = register_file_asset(db, workspace_id=ws.id, project_id=None, source_path=settings.data_dir / "src.mp4", name="原片")
        line = register_file_asset(db, workspace_id=ws.id, project_id=None, source_path=settings.data_dir / "line.wav", name="一句")
        sequence = Sequence(workspace_id=ws.id, project_id=project.id, name="译配版", width=320, height=240, fps=25)
        base = Track(sequence=sequence, kind="video", name="V1", position=0)
        dub = Track(sequence=sequence, kind="audio", name="A1", position=1)
        db.add_all([sequence, base, dub])
        db.flush()
        source = Clip(workspace_id=ws.id, sequence_id=sequence.id, track_id=base.id, asset_id=video.id,
                      timeline_start=0, src_in=0, src_out=6)
        db.add(source)
        for at in (1, 4):
            db.add(Clip(workspace_id=ws.id, sequence_id=sequence.id, track_id=dub.id, asset_id=line.id,
                        timeline_start=at, src_in=0, src_out=1))
        db.commit()
        ids = SimpleNamespace(ws=ws.id, sequence=sequence.id, clip=source.id, dub=dub.id, base=base.id)
    calls: list = []
    model = {"id": "p:video:videoretalk", "capabilities": {"source_duration_seconds": {"source_video": [2, 4]}}}
    monkeypatch.setattr(module, "_pick_model", lambda db, choice, mode: model)
    monkeypatch.setattr(module, "_generate", lambda db, scope, model, sources, parameters=None: calls.append(sources) or [sources[0]["asset_id"]])
    return ids, calls


def _config(ids, **extra):
    return {"sequence_id": ids.sequence, "clip_id": ids.clip, "track_id": ids.dub, "consent": "yes", **extra}


def test_整条跑通_切两块都改口型_接回整段放在最上面_原片不动(dubbed) -> None:
    ids, calls = dubbed
    scope = SimpleNamespace(workspace_id=ids.ws, id="wf:1", name="译配")
    with unit_of_work() as db:
        out = dub_lipsync(db, scope, _config(ids))
    assert (out["chunk_count"], out["generated_count"]) == (2, 2), "6 秒按 4 秒上限、在两句之间(第 3 秒)切成两块"
    assert [[one["role"] for one in sources] for sources in calls] == [["source_video", "driving_audio"]] * 2
    with unit_of_work() as db:
        sequence = db.get(Sequence, ids.sequence)
        top = min(sequence.tracks, key=lambda track: track.position)
        assert top.id == out["track_id"] and top.kind == "video", "新轨挪到最上面,盖住原片"
        placed = db.get(Clip, out["clip_id"])
        assert placed.track_id == top.id and placed.timeline_start == 0 and abs(placed.src_out - 6) < 0.2
        assert db.get(Clip, ids.clip).track_id == ids.base, "原片不动"
        final = settings.data_dir / placed.asset.file_key
        assert digital_human_assets(db, {placed.asset_id}) == {placed.asset_id}, "接回的整段不是生成记录的产出,也认得出是数字人"
        plan = build_plan_for_sequence(db, ids.sequence, {})
        assert "AIGC" in dict(plan.output.metadata) and plan.text_overlays, "导出这条时间线:画面标识、AIGC 元数据都加上"
    streams = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(final)],
                                        capture_output=True, text=True, check=True).stdout)["streams"]
    assert [one["codec_type"] for one in streams] == ["video"], "声音在配音轨和背景轨上,接回的整段不带声音"


def test_没有配音的块用原片_不花钱(dubbed) -> None:
    ids, calls = dubbed
    with unit_of_work() as db:
        for clip in db.query(Clip).filter(Clip.track_id == ids.dub, Clip.timeline_start == 4):
            db.delete(clip)
        db.commit()
    scope = SimpleNamespace(workspace_id=ids.ws, id="wf:1", name="译配")
    with unit_of_work() as db:
        out = dub_lipsync(db, scope, _config(ids))
    assert (out["chunk_count"], out["generated_count"], len(calls)) == (2, 1, 1)


def test_动手之前说清楚(dubbed) -> None:
    ids, calls = dubbed
    scope = SimpleNamespace(workspace_id=ids.ws, id="wf:1", name="译配")
    with unit_of_work() as db:
        with pytest.raises(WorkflowDomainError) as refused:
            dub_lipsync(db, scope, _config(ids, consent=""))
        assert refused.value.key == "wfErr_talkingNeedsConsent"
        db.get(Clip, ids.clip).speed = 1.5
        db.commit()
        with pytest.raises(WorkflowDomainError) as refused:
            dub_lipsync(db, scope, _config(ids))
        assert refused.value.key == "wfErr_dubLipsyncSpeed"
        db.get(Clip, ids.clip).speed = 1.0
        for clip in db.query(Clip).filter(Clip.track_id == ids.dub):
            db.delete(clip)
        db.commit()
        with pytest.raises(WorkflowDomainError) as refused:
            dub_lipsync(db, scope, _config(ids))
        assert refused.value.key == "wfErr_dubLipsyncNoSpeech"
    assert calls == []
