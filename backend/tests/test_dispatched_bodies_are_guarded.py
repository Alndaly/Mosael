"""**每个派发出去的执行体都有兜底**,由总线套,不靠执行体自己记得。

`run_job_guarded` 的来历写在它自己的说明里:执行体在它自己的 try 之前抛了(连接池等满、库被锁、解密失败……),线程无声地死掉,
任务停在 queued / running,直到下次重启才被判「重启中断」—— 界面上那一项一直转圈。此前要每个执行体自己记得套它,
生成、工作流、字幕配音、画板、从链接导入、资产库画图这七个没套。现在 `dispatch_job` 替所有执行体套一次。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.core.i18n import render_message
from app.core.unit_of_work import unit_of_work
from app.db.models import GenerationJob, Job
from app.domain.jobs import CANCELLED_ERROR_KEY, JobCancelled, create_job, dispatch_job, wait_for_idle_jobs
from tests.util import fresh_client


def _workspace() -> str:
    client = fresh_client()
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_a_body_that_crashes_before_its_own_try_still_settles_its_job() -> None:
    ws = _workspace()

    def crashes() -> None:
        raise RuntimeError("keychain unavailable")

    with unit_of_work() as db:
        job = create_job(db, workspace_id=ws, kind="subtitle_dub", payload={}, created_by=None)
        job_id = job.id
        dispatch_job(db, job, crashes)
    assert wait_for_idle_jobs(timeout=30)

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "failed", "执行体在自己的 try 之前崩了,任务停在了进行中"
        assert job.error == "keychain unavailable"
        # 那一句按读的人的语言说「字幕配音 失败」,种类的名字也跟着翻(文案片段,不是写死的中文)。
        assert job.message_key == "jobMsg_genericFailed"
        assert render_message(job.message_key, "en", job.message_params) == "Subtitle dub failed"


def test_the_generation_runner_is_covered_too(monkeypatch) -> None:
    """实测过的那一条:生成的执行体在解析适配器时抛了,任务曾经一直停在 running。"""
    from app.domain.generation import runner

    ws = _workspace()

    def boom(*_args, **_kwargs):
        raise RuntimeError("plugin manifest unreadable")

    monkeypatch.setattr(runner, "get_generation_adapter", boom)
    with unit_of_work() as db:
        job = create_job(db, workspace_id=ws, kind="ai_generation", payload={}, created_by=None)
        generation = GenerationJob(workspace_id=ws, job_id=job.id, provider="openai", model="gpt-image-1",
                                   kind="image", request={"prompt": "x"})
        db.add(generation)
        db.flush()
        job_id, generation_id = job.id, generation.id
        dispatch_job(db, job, lambda: runner._run_generation(generation_id))
    assert wait_for_idle_jobs(timeout=30)

    with SessionLocal() as db:
        assert db.get(Job, job_id).status == "failed"


def test_a_body_that_finds_itself_unwanted_is_recorded_as_cancelled() -> None:
    """执行体自己发现没人要了(取消开关拉下了、取消那一侧却没提交成):收成「已取消」,不是「出错」,也不停在 running。"""
    ws = _workspace()

    def unwanted() -> None:
        raise JobCancelled(CANCELLED_ERROR_KEY)

    with unit_of_work() as db:
        job = create_job(db, workspace_id=ws, kind="trim", payload={}, created_by=None)
        job_id = job.id
        dispatch_job(db, job, unwanted)
    assert wait_for_idle_jobs(timeout=30)

    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert (job.status, job.error_key, job.message_key) == ("failed", CANCELLED_ERROR_KEY, "jobMsg_cancelled")
