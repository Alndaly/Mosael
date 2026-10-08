"""`migrate-cancelled-jobs-get-their-own-status`:老库里记成 `failed` + `jobErr_cancelled` 的任务改成 `cancelled`(ADR 0049)。

喂它一份老形状:一条被取消的任务(带「已取消」的 error 和 key)、一条真失败的、一条成功的;三条定时任务的运行记录 —— 一条连着
被取消的任务、一条连着真失败的、一条连着成功的;一条生成记录抄着「已停止」的 key。看它只改被取消的那条任务和连着它的那条
运行记录,生成记录不动;再跑一次什么都不变。
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_cancelled_jobs_get_their_own_status as migrate
from app.db.models import GenerationJob, Job, ScheduledTask, ScheduledTaskRun
from tests.util import fresh_client


def _legacy() -> dict[str, str]:
    workspace = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        task = ScheduledTask(workspace_id=workspace, name="每天", kind="render", trigger_type="manual", payload={})
        db.add(task)
        db.flush()
        ids = {}
        for name in ("stopped", "broken", "done"):
            job = Job(workspace_id=workspace, kind="ai_generation", status="queued", payload={})
            db.add(job)
            db.flush()
            ids[name] = job.id
            run = ScheduledTaskRun(scheduled_task_id=task.id, job_id=job.id, status="queued")
            db.add(run)
            db.flush()
            ids[f"run_{name}"] = run.id
        generation = GenerationJob(workspace_id=workspace, job_id=ids["stopped"], kind="image", provider="p", model="m",
                                   request={}, error="已取消", error_key="jobErr_cancelled")
        db.add(generation)
        db.commit()
        ids["generation"] = generation.id
    #: 老形状直接写进库(新代码写不出这个样子)。
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE jobs SET status = 'failed', error = '已取消', error_key = 'jobErr_cancelled', error_params = '{}', "
            "message = '已取消', message_key = 'jobMsg_cancelled' WHERE id = :id"), {"id": ids["stopped"]})
        conn.execute(text(
            "UPDATE jobs SET status = 'failed', error = 'ffmpeg exited 1', error_key = '' WHERE id = :id"), {"id": ids["broken"]})
        conn.execute(text("UPDATE jobs SET status = 'succeeded' WHERE id = :id"), {"id": ids["done"]})
        for name, status, error in (("stopped", "failed", "已取消"), ("broken", "failed", "ffmpeg exited 1"),
                                    ("done", "succeeded", None)):
            conn.execute(text("UPDATE scheduled_task_runs SET status = :status, error = :error WHERE id = :id"),
                         {"status": status, "error": error, "id": ids[f"run_{name}"]})
    return ids


def _shape(ids: dict[str, str]) -> dict[str, tuple]:
    with SessionLocal() as db:
        shape = {}
        for name in ("stopped", "broken", "done"):
            job = db.get(Job, ids[name])
            run = db.get(ScheduledTaskRun, ids[f"run_{name}"])
            shape[name] = (job.status, job.error, job.error_key, job.message_key, run.status, run.error)
        generation = db.get(GenerationJob, ids["generation"])
        shape["generation"] = (generation.error, generation.error_key)
        return shape


def test_被取消的任务和它的运行记录改成cancelled_别的不动_再跑一次什么都不变() -> None:
    ids = _legacy()

    migrate()

    after = _shape(ids)
    assert after["stopped"] == ("cancelled", None, "", "jobMsg_cancelled", "cancelled", None)
    assert after["broken"] == ("failed", "ffmpeg exited 1", "", "", "failed", "ffmpeg exited 1"), "真失败的不动"
    assert after["done"][0] == "succeeded" and after["done"][4] == "succeeded"
    assert after["generation"] == ("已取消", "jobErr_cancelled"), "生成记录靠自己抄下的 key 说「已停止」,不动"

    migrate()
    assert _shape(ids) == after

