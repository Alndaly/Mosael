"""译配、口播整理的转写失败了,不留下一个空的「· 译配版」/「· 智能整理」项目。

此前项目和转写并行建:转写一失败(片子没有音轨、识别不出一个字),项目已经建好、原片已经铺上去,留下一个
没人要的半成品,用户每失败一次项目列表里就多一个。现在项目在转写成功之后才建。跑**模板本身那张图**(真的引擎),
转写换成「失败了」的桩。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Asset, Project, Workflow
from app.domain.jobs import create_job
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.engine import execute_graph
from app.domain.workflows.templates import transcript_video_cleanup_graph, translated_dub_graph
from app.domain.workflows.templates_models import ModelChoice
from tests.util import fresh_client


@pytest.fixture
def failing_transcription(monkeypatch):
    from app.domain.assets import denoise
    from app.domain.voices import transcription

    def fake_transcribe(db, asset_id, *, created_by=None, language="", engine=""):
        asset = db.get(Asset, asset_id)
        job = create_job(db, workspace_id=asset.workspace_id, kind="transcribe", payload={}, created_by=created_by)
        job.status = "failed"
        job.error = "转写结果为空"
        db.commit()
        return job

    def fake_denoise(db, *, asset, created_by=None, engine="", strength=""):
        job = create_job(db, workspace_id=asset.workspace_id, kind="denoise", payload={}, created_by=created_by)
        job.status = "succeeded"
        job.result = {"asset_id": asset.id, "engine": "builtin:rnnoise"}
        db.commit()
        return job

    monkeypatch.setattr(transcription, "start_transcription", fake_transcribe)
    monkeypatch.setattr(denoise, "start_denoise_job", fake_denoise)

    workspace = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        video = Asset(workspace_id=workspace, kind="video", source="import", name="讲话.mp4",
                      media_info={"duration": 10.0, "width": 1920, "height": 1080, "fps": 30})
        workflow = Workflow(workspace_id=workspace, name="W", graph={"nodes": [], "edges": []})
        db.add_all([video, workflow])
        db.commit()
        return video.id, workflow.id


@pytest.mark.parametrize("make", [
    lambda: translated_dub_graph(voice_id="v1"),
    lambda: transcript_video_cleanup_graph(chat=ModelChoice(profile_id="p", provider="x", model="m"), locale="zh"),
], ids=["译配", "口播整理"])
def test_转写失败_不留下空项目(failing_transcription, make) -> None:
    video_id, workflow_id = failing_transcription
    graph = make()
    next(node for node in graph["nodes"] if node["id"] == "source_video")["config"]["asset_id"] = video_id
    with pytest.raises(WorkflowDomainError, match="转写结果为空"):
        execute_graph(graph, wf_id=workflow_id)
    with SessionLocal() as db:
        assert db.scalars(select(Project)).all() == [], "项目在转写成功之后才建"
