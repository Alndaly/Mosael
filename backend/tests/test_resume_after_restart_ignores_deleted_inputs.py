"""重启后接着取一个已经提交(付过钱)的远端任务,不因为输入素材被删了而放弃(ADR 0019 修订)。

此前接着取和第一次提交走同一段:重新解析素材、重新校验请求。用户提交图生视频之后把首帧从素材库删了(或者它是一张
中间产物),期间后端重启(开发时的 --reload、升级、崩溃)—— 接着取在问远端之前就失败「首帧素材不存在」,远端照扣,
成片没人去取,账一笔都不记。接着取只需要轮询路径和模型:素材在提交那一刻就交出去了。
不调真实接口:假适配器。
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from app.ai.providers.contracts.generation import GenerationResult, metering_from_request
from app.core.db import SessionLocal
from app.db.models import GenerationJob, Job, ProviderUsageEvent


def _png(path: Path) -> Path:
    from PIL import Image

    Image.new("RGB", (8, 8), "red").save(path)
    return path


def _wait_settled(job_id: str, timeout: float = 10.0) -> Job:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job.status not in ("queued", "running"):
                return job
        time.sleep(0.05)
    raise AssertionError("接着取的任务没有落终态")


def test_重启接着取_首帧素材删了也照样去问远端(monkeypatch, tmp_path) -> None:
    from tests.util import fresh_client
    from app.domain import jobs
    from app.domain.generation import runner

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        job = Job(workspace_id=workspace, kind="ai_generation", status="running",
                  payload={"remote_task": {"poll_path": "/tasks/cgt-paid"}})
        db.add(job)
        db.flush()
        db.add(GenerationJob(
            workspace_id=workspace, job_id=job.id, kind="video", provider="test", model="m",
            #: 提交时交了一张首帧;提交之后用户把它从素材库删了
            request={"prompt": "猫", "parameters": {"duration_seconds": 5},
                     "source_assets": [{"role": "first_frame", "asset_id": "deleted-asset"}]},
        ))
        db.commit()
        job_id = job.id

    monkeypatch.setattr("app.domain.providers.selection.resolve_connection", lambda *a, **kw: None)
    resumed: list[str] = []
    said: list[str] = []

    def resume(poll_path, request, context, output_dir):
        resumed.append(poll_path)
        #: 接着取的时候任务上那句话:「后端重启过,正在接着取回」,不是被换成笼统的「生成中」
        with SessionLocal() as db:
            said.append(db.get(Job, job_id).message_key)
        return GenerationResult(output_paths=[_png(output_dir / "o.png")], usage=metering_from_request(request))

    def validate(request):
        raise AssertionError("接着取不该再校验请求:素材早就交出去了")

    adapter = SimpleNamespace(requires_credentials=lambda: False, validate_request=validate,
                              supports_progress_callbacks=False, supports_resume=True,
                              resume=resume, generate=None, reported_usage=lambda raw: runner.ReportedUsage())
    monkeypatch.setattr(runner, "get_generation_adapter", lambda *a: adapter)

    with SessionLocal() as db:
        jobs.reconcile_orphaned_jobs(db)
        db.commit()  # 测试是入口:重启收尾不提交,接着取在提交之后才开始(见 domain/restart.settle_previous_run)
    job = _wait_settled(job_id)

    assert resumed == ["/tasks/cgt-paid"], "付过钱的远端任务没人去问"
    assert said == ["jobMsg_generationResuming"]
    assert job.status == "succeeded", job.error
    with SessionLocal() as db:
        events = list(db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job_id)))
    assert [event.status for event in events] == ["succeeded"]
    #: 计量里交进去几张图照提交时的那一份数,而不是接着取时那个空的请求
    assert events[0].units.get("source_images") == 1
