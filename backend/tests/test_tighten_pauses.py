"""「压缩停顿」:句间过长的静音压到上限,话不动;产出新素材,来源和克隆音色的出处都跟着走(ADR 0092 最后一段硬切)。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Workflow
from app.domain.assets.importer import register_file_asset
from app.domain.workflows.engine import execute_graph
from app.domain.workflows.errors import WorkflowDomainError
from app.media.paths import resolve_key
from app.media.pauses import Span, kept_spans, parse_silences
from app.media.probe import probe_media
from tests.util import fresh_client


def test_读静音_片尾那一处没有终点就到片尾() -> None:
    log = "\n".join([
        "[silencedetect @ 0x1] silence_start: 0",
        "[silencedetect @ 0x1] silence_end: 0.6 | silence_duration: 0.6",
        "[silencedetect @ 0x1] silence_start: 2.787",
        "[silencedetect @ 0x1] silence_end: 4.002 | silence_duration: 1.215",
        "[silencedetect @ 0x1] silence_start: 9.1",
    ])
    assert parse_silences(log, duration=9.548) == [Span(0, 0.6), Span(2.787, 4.002), Span(9.1, 9.548)]


def test_长停顿只剪中间那截_前后各留一半_短的不动() -> None:
    kept = kept_spans(10.0, [Span(2.0, 2.4), Span(5.0, 6.2)], max_pause=0.6)
    assert kept == [Span(0.0, pytest.approx(5.3)), Span(pytest.approx(5.9), 10.0)]
    assert sum(span.length for span in kept) == pytest.approx(10.0 - 0.6)


def test_片头片尾的静音也只留上限那么长() -> None:
    kept = kept_spans(10.0, [Span(0.0, 1.5), Span(8.0, 10.0)], max_pause=0.6)
    assert kept == [Span(0.0, pytest.approx(0.3)), Span(pytest.approx(1.2), pytest.approx(8.3)), Span(pytest.approx(9.7), 10.0)]
    assert sum(span.length for span in kept) == pytest.approx(6.5 + 0.6 + 0.6)


def test_没有长停顿就是整段() -> None:
    assert kept_spans(4.0, [Span(1.0, 1.5)], max_pause=0.6) == [Span(0.0, 4.0)]


def _speech_with_pause(path: Path) -> None:
    """1 秒「话」(正弦)、1.5 秒静音、1 秒「话」。"""
    tone = "sine=frequency=440:sample_rate=24000:duration=1"
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", tone,
                    "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=1.5", "-f", "lavfi", "-i", tone,
                    "-filter_complex", "[0][1][2]concat=n=3:v=0:a=1", "-ac", "1", str(path)], check=True)


def _run(asset_id: str, wf_id: str, max_pause: float) -> dict:
    graph = {"nodes": [{"id": "start", "type": "start", "config": {}},
                       {"id": "tight", "type": "tighten_pauses", "config": {"asset_id": asset_id, "max_pause": max_pause}}],
             "edges": [{"id": "e", "source": "start", "target": "tight"}]}
    context, _ = execute_graph(graph, wf_id=wf_id, params={})
    return context["tight"]


def test_真压一遍_停顿压到上限_新素材记着来源和音色(tmp_path: Path) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    source = tmp_path / "voice.wav"
    _speech_with_pause(source)
    with SessionLocal() as db:
        voice = register_file_asset(db, workspace_id=ws, project_id=None, source_path=source, name="配音", source="tts",
                                    ai_generated=True, voices=["cloned-voice"])
        workflow = Workflow(workspace_id=ws, name="压", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        voice_id, wf_id = voice.id, workflow.id

    made = _run(voice_id, wf_id, 0.5)
    assert made["source_asset_id"] == voice_id
    assert made["removed_seconds"] == pytest.approx(1.0, abs=0.05)
    assert made["duration"] == pytest.approx(2.5, abs=0.05)
    with SessionLocal() as db:
        tight = db.get(Asset, made["asset_id"])
        assert tight.kind == "audio"
        assert tight.derived_from == [{"asset_id": voice_id, "op": "tighten"}]
        assert tight.ai_generated, "合成的配音压完还是合成的"
        assert tight.voices == ["cloned-voice"], "嗓子从出处继承,数字人的授权检查按它查"
        assert probe_media(resolve_key(tight.file_key))["duration"] == pytest.approx(2.5, abs=0.05)


def test_视频不收_上限越界在建任务前就拒(tmp_path: Path) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    video = tmp_path / "shot.mp4"
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=24:duration=1",
                    "-pix_fmt", "yuv420p", str(video)], check=True)
    audio = tmp_path / "voice.wav"
    _speech_with_pause(audio)
    with SessionLocal() as db:
        video_id = register_file_asset(db, workspace_id=ws, project_id=None, source_path=video, name="片子").id
        audio_id = register_file_asset(db, workspace_id=ws, project_id=None, source_path=audio, name="配音").id
        workflow = Workflow(workspace_id=ws, name="压", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        wf_id = workflow.id
    for asset_id, max_pause, key in ((video_id, 0.6, "pauseErr_audioOnly"), (audio_id, 5.0, "pauseErr_maxPauseOutOfRange")):
        with pytest.raises(WorkflowDomainError) as caught:
            _run(asset_id, wf_id, max_pause)
        assert caught.value.key == key
