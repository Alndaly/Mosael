"""成片已经交回、正在登记进素材库时点了停止:成片在库里,这一次生成的账也要在。

登记素材是逐份提交的(长视频要几秒到十几秒)。此前全部登记完之后 `finish_job("succeeded")` 发现任务已被取消,就直接提交
返回 —— 素材库里多了两份成片,服务商也早扣了钱,花费里却一笔都没有。进度停在 95% 时用户点了停止、或者工作流 fail-fast
把同一批的生成连带取消,都会走到这里。
不调真实接口:假适配器。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from app.ai.providers.contracts.generation import GenerationResult, ReportedUsage
from app.core.db import SessionLocal
from app.db.models import Asset, GeneratedAsset, GenerationJob, Job, ProviderUsageEvent


def _png(path: Path) -> Path:
    from PIL import Image

    Image.new("RGB", (8, 8), "red").save(path)
    return path


def test_登记素材时被停下_成片在库_账也在(monkeypatch) -> None:
    from tests.util import fresh_client
    from app.domain import jobs
    from app.domain.generation import runner

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        job = Job(workspace_id=workspace, kind="ai_generation", status="queued", payload={})
        db.add(job)
        db.flush()
        generation = GenerationJob(workspace_id=workspace, job_id=job.id, kind="image", provider="test", model="m",
                                   request={"prompt": "猫", "parameters": {"num_images": 2}})
        db.add(generation)
        db.commit()
        job_id, generation_id = job.id, generation.id

    monkeypatch.setattr("app.domain.providers.selection.resolve_connection", lambda *a, **kw: None)

    def generate(request, context, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        return GenerationResult(output_paths=[_png(output_dir / "a.png"), _png(output_dir / "b.png")],
                                usage={"images": 2}, raw_usage={"usage": {"images": 2}})

    adapter = SimpleNamespace(requires_credentials=lambda: False, validate_request=lambda r: None,
                              supports_progress_callbacks=False, supports_resume=False, generate=generate,
                              reported_usage=lambda raw: ReportedUsage())
    monkeypatch.setattr(runner, "get_generation_adapter", lambda *a: adapter)

    registered = runner.register_file_asset
    count = {"n": 0}

    def register(db, **fields):
        count["n"] += 1
        if count["n"] == 2:
            #: 登记第二份时,用户在任务中心点了取消(另一个会话)
            with SessionLocal() as other:
                jobs.cancel_job(other, other.get(Job, job_id))
                other.commit()
        return registered(db, **fields)

    monkeypatch.setattr(runner, "register_file_asset", register)
    runner._run_generation(generation_id)

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert jobs.was_cancelled(job)
        assert len(db.scalars(select(GeneratedAsset).where(GeneratedAsset.job_id == job_id)).all()) == 2
        assert len(db.scalars(select(Asset).where(Asset.workspace_id == workspace, Asset.source == "generated")).all()) == 2
        events = db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job_id)).all()
    assert [event.status for event in events] == ["succeeded"], "成片进了库、钱扣了,账上要有这一笔"
    assert events[0].units.get("images") == 2
    assert events[0].raw_usage.get("cancelled_locally") is True
