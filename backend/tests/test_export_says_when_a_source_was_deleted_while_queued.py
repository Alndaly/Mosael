"""导出排队期间素材被删了:失败原因说「素材在排队期间被删除」,不说「文件可能损坏或未录制完整」(MED-8)。

计划在建任务时就定死了。两个导出名额都占着时新的导出排队,这期间删掉它用到的素材,轮到它时 ffmpeg 打不开文件 ——
此前失败原因是「无法读取素材『片头.mp4』—— 文件可能损坏或未录制完整」,用户去检查一个其实已经删掉的文件。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import Job
from app.domain import render
from tests.test_export_flow import make_test_video
from tests.util import fresh_client

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


def _sequence_with(client, workspace: str, tmp_path: Path) -> tuple[str, str]:
    source = tmp_path / "src.mp4"
    make_test_video(source, 1.5)
    project = client.post("/api/projects", json={"workspace_id": workspace, "name": "P"}).json()["id"]
    asset = client.post("/api/assets/import", data={"workspace_id": workspace, "project_id": project},
                        files={"file": ("片头.mp4", source.read_bytes(), "video/mp4")}).json()
    sequence = client.post("/api/sequences", json={
        "workspace_id": workspace, "project_id": project, "name": "Main", "width": 320, "height": 180,
    }).json()
    track = next(one for one in sequence["tracks"] if one["kind"] == "video")
    added = client.post(f"/api/sequences/{sequence['id']}/clips", json={
        "track_id": track["id"], "asset_id": asset["id"], "timeline_start": 0, "src_in": 0, "src_out": 1.0,
    })
    assert added.status_code < 300, added.text
    return sequence["id"], asset["id"]


def _queued_job(workspace: str) -> str:
    with SessionLocal() as db:
        job = Job(workspace_id=workspace, kind="render", status="queued")
        db.add(job)
        db.commit()
        return job.id


def test_排队时素材被删了_说清是删了_不开始编码(monkeypatch, tmp_path: Path) -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    sequence_id, asset_id = _sequence_with(client, workspace, tmp_path)
    with SessionLocal() as db:
        plan = render.build_plan_for_sequence(db, sequence_id, None)  # 建任务那一刻定下的计划
    job_id = _queued_job(workspace)
    assert client.delete(f"/api/assets/{asset_id}").status_code == 204  # 排队期间删掉
    encoded: list = []
    monkeypatch.setattr(render, "execute_render", lambda *a, **kw: encoded.append(1))

    render._run_export(job_id, plan)

    assert encoded == [], "素材已经删了还去编码"
    with SessionLocal() as db:
        job = db.get(Job, job_id)
    assert job.status == "failed"
    assert "片头.mp4" in job.error and "排队期间被删除" in job.error, job.error
    assert "损坏" not in job.error


def test_素材都在_照常编码(monkeypatch, tmp_path: Path) -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    sequence_id, _ = _sequence_with(client, workspace, tmp_path)
    with SessionLocal() as db:
        plan = render.build_plan_for_sequence(db, sequence_id, None)
    job_id = _queued_job(workspace)
    encoded: list = []

    def encode(plan, resolve_key, output_path, on_progress, on_child, on_phase):
        encoded.append(1)
        raise render.RenderExecutionError("stop here", stderr_tail="")

    monkeypatch.setattr(render, "execute_render", encode)
    render._run_export(job_id, plan)

    assert encoded == [1]
