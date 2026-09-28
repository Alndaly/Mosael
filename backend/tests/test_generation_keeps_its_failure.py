"""生成记录**自己**存失败原因。

任务会被任务中心的「清空已结束」删掉(生成记录的 job_id 随之置空),生成记录不会 —— 它是创作历史。此前失败原因
只在任务上,清一次之后 AI 工作台的失败卡只剩一句泛泛的「生成失败」。

原因在任务**落「失败」那一刻**抄过来(generation.runner.record_failure,挂在 jobs.register_settle_listener 上),
所以执行体自己失败、用户取消、重启时接不回来这几条路都算数;存的是 key 加参数,读的时候按读的人的语言翻。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import GenerationJob, Job
from app.domain.generation.runner import GenerationRunError, _fail
from app.domain.jobs import create_job, reconcile_orphaned_jobs
from tests.util import fresh_client


def _generation(ws: str, *, status: str = "queued") -> tuple[str, str]:
    with SessionLocal() as db:
        job = create_job(db, workspace_id=ws, kind="ai_generation", created_by=None, payload={},
                         message="jobMsg_generationQueued")
        job.status = status
        generation = GenerationJob(workspace_id=ws, job_id=job.id, provider="openai", model="gpt-image-1",
                                   kind="image", request={"prompt": "一只猫"})
        db.add(generation)
        db.commit()
        return generation.id, job.id


def _listed(client, ws: str, generation_id: str, language: str) -> dict:
    rows = client.get(f"/api/generation/jobs?workspace_id={ws}", headers={"Accept-Language": language}).json()
    return next(row for row in rows if row["id"] == generation_id)


def test_执行体失败_原因记在生成记录上_清掉任务之后还在_按读的人的语言翻() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    generation_id, job_id = _generation(ws)
    with SessionLocal() as db:
        _fail(db, db.get(Job, job_id), GenerationRunError("genErr_noApiKey", provider="openai"))

    assert client.delete(f"/api/jobs/finished?workspace_id={ws}").json() == {"removed": 1}
    english = _listed(client, ws, generation_id, "en")
    assert english["job_id"] is None
    assert english["error"] == "Provider openai doesn't have your API key yet. Add it in Settings first."
    assert _listed(client, ws, generation_id, "zh")["error"] == "供应商 openai 还没有配置你的密钥,请先在设置里填写"
    # key 与参数只为翻译服务,不出现在响应里。
    assert "error_key" not in english and "error_params" not in english


def test_用户取消_也记下() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    generation_id, job_id = _generation(ws)
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
    assert _listed(client, ws, generation_id, "en")["error"] == "Cancelled"


def test_重启时接不回来_也记下() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    generation_id, _job_id = _generation(ws, status="running")
    with SessionLocal() as db:
        reconcile_orphaned_jobs(db)
    assert _listed(client, ws, generation_id, "en")["error"] == (
        "The backend restarted and interrupted this task; please start it again"
    )


def test_成功的不记() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    generation_id, job_id = _generation(ws)
    with SessionLocal() as db:
        from app.domain.jobs import finish_job

        job = db.get(Job, job_id)
        finish_job(db, job, status="succeeded")
        db.commit()
    assert _listed(client, ws, generation_id, "en")["error"] is None
