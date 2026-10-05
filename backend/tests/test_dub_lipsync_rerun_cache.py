"""「视频译配 · 改口型」整图重跑:译文、音色、时间都没变的块不再买一次 —— 哪怕配音重新合成出的字节不一样。

此前块的键里有这一块配音混音的字节摘要。整图重跑时翻译、合成都会重来一遍,同一句话同一把嗓子合成出来的
字节每次都可能差一点,于是一块都认不出来,每块再买一次。这里跑**模板本身那张图**(真的引擎、真的字幕配音、
真的切块和 ffmpeg),合成换成「每次念出来的字节都不一样」的桩,改口型换成交回那一块原片的桩。
"""

from __future__ import annotations

import itertools
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, Job, Workflow
from app.domain.assets.importer import register_file_asset
from app.domain.jobs import create_job
from app.domain.workflows.engine import execute_graph
from app.domain.workflows.executors import dub_lipsync as module
from app.domain.workflows.templates import translated_dub_graph
from tests.util import fresh_client

#: 30 秒原片,每 6 秒一句;模型一次收 2–10 秒 —— 切成好几块,每块一两句。
SEGMENTS = [(1.0, 4.0, "a"), (7.0, 10.0, "b"), (13.0, 16.0, "c"), (19.0, 22.0, "d"), (25.0, 28.0, "e")]


def _media(key: str, args: list[str]):
    path = settings.data_dir / key
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args, str(path)], check=True)
    return path


@pytest.fixture
def pipeline(monkeypatch):
    from app.domain import render, translate as translate_domain
    from app.domain.assets import separation
    from app.domain.voices import transcription, voices

    translations: dict[str, str] = {}
    generations: list = []
    tone = itertools.count(300, 37)

    def fake_transcribe(db, asset_id, *, created_by=None, language="", engine=""):
        from app.db.models import Transcript, TranscriptSegment

        asset = db.get(Asset, asset_id)
        transcript = Transcript(workspace_id=asset.workspace_id, asset_id=asset_id, language="ja")
        db.add(transcript)
        db.flush()
        for start, end, text in SEGMENTS:
            db.add(TranscriptSegment(transcript_id=transcript.id, start_time=start, end_time=end, text=text))
        job = create_job(db, workspace_id=asset.workspace_id, kind="transcribe", payload={}, created_by=created_by)
        job.status = "succeeded"
        job.result = {"transcript_id": transcript.id, "segments": len(SEGMENTS)}
        db.commit()
        return job

    def fake_translate_many(db, texts, target_lang, **_kw):
        return [translations.get(text, f"[{target_lang}]{text}") for text in texts]

    def fake_synthesis(db, *, text, project_id, created_by, **_kw):
        """每次合成都换一个音高:同一句话、同一把嗓子,字节每次都不一样(真实的合成也是这样)。"""
        workspace_id = db.scalars(select(Asset)).first().workspace_id
        path = _media(f"tts-{next(tone)}.wav", ["-f", "lavfi", "-i", f"sine=frequency={next(tone)}:duration=2.5", "-ar", "24000"])
        asset = register_file_asset(db, workspace_id=workspace_id, project_id=project_id, source_path=path,
                                    name=text[:20], source="tts")
        job = create_job(db, workspace_id=workspace_id, kind="tts", payload={}, created_by=created_by)
        job.status = "succeeded"
        job.result = {"asset_id": asset.id}
        db.commit()
        return job

    def fake_export(db, sequence_id, options=None, *, created_by=None):
        job = create_job(db, workspace_id=db.scalars(select(Asset)).first().workspace_id, kind="render", payload={},
                         created_by=created_by)
        job.status = "succeeded"
        job.result = {"asset_id": "exported"}
        db.commit()
        return job

    def fake_separate(db, asset, **_kw):
        background = Asset(workspace_id=asset.workspace_id, project_id=asset.project_id, kind="audio", source="separated",
                           name=f"{asset.name} · 背景音", media_info={"duration": asset.media_info.get("duration", 0)},
                           file_key=asset.file_key)
        db.add(background)
        db.flush()
        return SimpleNamespace(background=background)

    model = {"id": "p:video:videoretalk", "provider": "p", "provider_profile_id": "p", "model": "videoretalk",
             "capabilities": {"source_duration_seconds": {"source_video": [2, 10]}}}

    def generation(db, **request):
        generations.append(request)
        job = Job(workspace_id=request["workspace_id"], kind="generation", status="succeeded", created_by=None,
                  result={"asset_ids": [request["source_assets"][0]["asset_id"]]})
        db.add(job)
        db.flush()
        return SimpleNamespace(id=job.id), job

    monkeypatch.setattr(transcription, "start_transcription", fake_transcribe)
    monkeypatch.setattr(translate_domain, "translate_many", fake_translate_many)
    monkeypatch.setattr(voices, "start_synthesis", fake_synthesis)
    monkeypatch.setattr(render, "start_export", fake_export)
    monkeypatch.setattr(separation, "available", lambda *_a, **_k: True)
    monkeypatch.setattr(separation, "separate_asset", fake_separate)
    monkeypatch.setattr(module, "_pick_model", lambda db, choice, mode: model)
    monkeypatch.setattr("app.domain.generation.create_generation_job", generation)
    monkeypatch.setattr("app.domain.generation.runner.start_generation_thread", lambda generation_id: None)

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "译配"}).json()["id"]
    source = _media("src.mp4", ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=30", "-f", "lavfi", "-i",
                                "sine=duration=30", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p"])
    with SessionLocal() as db:
        video = register_file_asset(db, workspace_id=workspace, project_id=None, source_path=source, name="原片")
        workflow = Workflow(workspace_id=workspace, name="译配改口型", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.commit()
        video_id, workflow_id = video.id, workflow.id

    graph = translated_dub_graph(voice_id="", lipsync=True)
    for node in graph["nodes"]:
        if node["id"] == "source_video":
            node["config"]["asset_id"] = video_id
        if node["id"] == "lip_sync":
            node["config"]["consent"] = "yes"
        if node["id"] == "dubbing":
            node["config"].update(engine="builtin:volcano", voice="voice-a")

    def run() -> dict:
        context, cancelled = execute_graph(graph, wf_id=workflow_id)
        assert not cancelled and "__error__" not in context, context.get("__error__")
        return context["lip_sync"]

    return SimpleNamespace(run=run, generations=generations, translations=translations)


def test_整图重跑_配音字节变了也认得出_只有改了译文的那块重买(pipeline) -> None:
    first = pipeline.run()
    assert first["generated_count"] == len(pipeline.generations) > 1

    second = pipeline.run()
    assert (second["generated_count"], second["reused_count"]) == (0, first["generated_count"]), \
        "翻译、配音重新跑了一遍,合成出的字节都不一样;译文、音色、时间没变 —— 一块都不再买"

    pipeline.translations["c"] = "[en]c, slightly reworded"
    third = pipeline.run()
    assert (third["generated_count"], third["reused_count"]) == (1, first["generated_count"] - 1), \
        "只有改了措辞的那一句所在的那块重买"


def test_切出来的块和改好口型的块是零件_接回的整段进素材库(pipeline) -> None:
    """每一块都是这道工序的零件(中间产物,见 assets/intermediates):素材库不列;接回原片长度的那一段才是交出去的。"""
    out = pipeline.run()
    with SessionLocal() as db:
        final = db.get(Asset, out["asset_id"])
        pieces = {one["asset_id"] for request in pipeline.generations for one in request["source_assets"]}
        assert final.intermediate == ""
        assert pieces and {db.get(Asset, one).intermediate for one in pieces} == {"lipsync_chunk"}
