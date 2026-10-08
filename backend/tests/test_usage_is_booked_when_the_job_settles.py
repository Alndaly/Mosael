"""任务落终态的那一刻,它的账已经在库里(D66 的修正)。

D66 第一版把账挪到调用方的事务**结束之后**另开事务写:任务落 succeeded 和账写进库之间多了一段窗口。落终态之后跑的收拾、
回执(after_commit)一律跑在这段窗口里;AI Studio 在任务落终态那一下去取记录的成本,碰上窗口就一直空着(那一条不再轮询);
CI 上「接着取回之后账在」那条测试(test_resume_after_restart_ignores_deleted_inputs)也碰上过。

现在账随调用方提交的那一刻一起落库(billing.usage「账随调用方提交的那一刻落库」):这里在**最早**能看见终态的地方 ——
落终态之后的收拾(jobs.register_settle_listener)和提交钩子(unit_of_work.after_commit)—— 去查账,不靠等。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import func, select

from app.ai.providers.contracts.generation import GenerationResult, metering_from_request
from app.core.db import SessionLocal
from app.core.unit_of_work import after_commit
from app.db.models import GenerationJob, Job, ProviderUsageEvent
from app.domain import jobs as jobs_bus
from app.domain.billing.usage import billable
from app.domain.generation import runner
from app.domain.jobs import finish_job
from tests.util import fresh_client


def _booked(job_id: str) -> list[str]:
    with SessionLocal() as db:
        return [event.status for event in db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job_id))]


def test_生成落成功之后的收拾里_账已经在(monkeypatch, tmp_path: Path) -> None:
    workspace = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        job = Job(workspace_id=workspace, kind="ai_generation", status="queued", payload={})
        db.add(job)
        db.flush()
        generation = GenerationJob(workspace_id=workspace, job_id=job.id, kind="image", provider="test", model="m",
                                   request={"prompt": "猫", "parameters": {}})
        db.add(generation)
        db.commit()
        job_id, generation_id = job.id, generation.id

    def generate(request, context, output_dir):
        from PIL import Image

        path = output_dir / "o.png"
        Image.new("RGB", (8, 8), "red").save(path)
        return GenerationResult(output_paths=[path], usage=metering_from_request(request))

    adapter = SimpleNamespace(requires_credentials=lambda: False, validate_request=lambda request: None,
                              supports_progress_callbacks=False, supports_resume=False, generate=generate,
                              reported_usage=lambda raw: runner.ReportedUsage())
    monkeypatch.setattr(runner, "get_generation_adapter", lambda *a: adapter)
    monkeypatch.setattr("app.domain.providers.selection.resolve_connection", lambda *a, **kw: None)
    seen: dict[str, list[str]] = {}

    def look(db, job):
        if job.id == job_id:
            seen[job.status] = [one.status for one in db.scalars(
                select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job.id))]

    monkeypatch.setitem(jobs_bus._SETTLE_LISTENERS, "look_at_the_bill", look)

    runner._run_generation(generation_id)

    assert seen == {"succeeded": ["succeeded"]}, "任务落了成功,账还没进库"
    assert _booked(job_id) == ["succeeded"]


def test_和任务终态一起提交的账_提交钩子里就看得见() -> None:
    """不管是哪个领域:账和调用方这一次提交的东西在同一个事务里,提交之后第一个看的人就看得见。"""
    workspace = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        job = Job(workspace_id=workspace, kind="render", status="running", payload={})
        db.add(job)
        db.commit()
        job_id = job.id

    seen: list[int] = []
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        with billable(db, user_id=None, capability="chat", operation="probe", workspace_id=workspace, job_id=job_id,
                      idempotency_key="probe:settles-with-the-job") as call:
            call.report_cost(900, "USD")
        finish_job(db, job, status="succeeded")

        def count() -> None:
            with SessionLocal() as other:
                seen.append(int(other.scalar(select(func.count()).select_from(ProviderUsageEvent)
                                             .where(ProviderUsageEvent.job_id == job_id)) or 0))

        after_commit(db, count)
        db.commit()

    assert seen == [1], "任务的终态提交了,账却还没在库里"
