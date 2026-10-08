"""任务中心的「清空已结束」= 把我的水位线挪到现在,不删任何东西(ADR 0050 D27、D28、D32)。

此前一点就把整个工作区所有人的已结束任务物理删掉:工作流的执行历史、运行产出全文、统计里的任务活动跟着没了,用量归不到人。
现在每人每个工作区一条水位线:面板只列还在跑的,和结束在水位线之后的;「显示已清掉的」列水位线之前的;别人的面板、
任务本身、统计都不动。
"""

from __future__ import annotations

from datetime import timedelta

from app.core.db import SessionLocal
from app.db.models import Job, JobCenterMark, ProviderUsageEvent, TaskEvent, WorkflowRunOutput, now
from app.domain.billing.usage import record_usage
from tests.util import fresh_client, second_client


def _join(owner, ws: str, username: str, role: str):
    member = second_client(username)
    assert owner.post(f"/api/workspaces/{ws}/invitations", json={"username": username, "role": role}).status_code == 200
    invitation = member.get("/api/invitations").json()["invitations"][0]["id"]
    assert member.post(f"/api/invitations/{invitation}/accept").status_code == 200
    return member


def _job(db, ws: str, *, status: str = "succeeded", kind: str = "render", parent: str | None = None, ago: int = 60) -> str:
    """一个任务,`ago` 秒之前结束(还在跑的就是那时起跑)。"""
    at = now() - timedelta(seconds=ago)
    job = Job(workspace_id=ws, kind=kind, status=status, message="x", parent_job_id=parent, created_at=at, updated_at=at)
    db.add(job)
    db.flush()
    db.add(TaskEvent(job_id=job.id, type="e", payload={}))
    return job.id


def _panel(client, ws: str, *, cleared: bool = False) -> tuple[list[str], str | None]:
    response = client.get(f"/api/jobs/center?workspace_id={ws}" + ("&cleared=true" if cleared else ""))
    assert response.status_code == 200, response.text
    body = response.json()
    return [job["id"] for job in body["jobs"]], body["cleared_at"]


def test_清空只挪我的水位线_别人的面板_任务本身_运行产出_用量都不动() -> None:
    owner = fresh_client("owner")
    ws = owner.post("/api/workspaces", json={"name": "W"}).json()["id"]
    mate = _join(owner, ws, "mate", "editor")
    with SessionLocal() as db:
        plain = _job(db, ws, ago=300)
        child = _job(db, ws, parent=plain, ago=300)
        run = _job(db, ws, kind="workflow", ago=200)
        db.add(WorkflowRunOutput(job_id=run, node_id="ask", output_key="text", value="一段很长的模型回复"))
        paid = _job(db, ws, kind="ai_generation", ago=100)
        record_usage(db, user_id=None, workspace_id=ws, capability="image", operation="generate", idempotency_key="paid",
                     job_id=paid, cost_micros=120000, cost_confidence="estimated")
        running = _job(db, ws, status="running", ago=400)
        db.commit()

    shown, cleared_at = _panel(owner, ws)
    assert set(shown) == {plain, run, paid, running} and cleared_at is None, "子任务收在父任务里,不上面板"
    assert child not in shown
    with SessionLocal() as db:
        events = db.query(TaskEvent).count()

    response = owner.post(f"/api/jobs/center/clear?workspace_id={ws}")
    assert response.status_code == 200, response.text
    assert response.json()["cleared_at"]

    shown, cleared_at = _panel(owner, ws)
    assert shown == [running], "还在跑的一直在,哪怕它比水位线早开始"
    assert cleared_at is not None
    assert set(_panel(mate, ws)[0]) == {plain, run, paid, running}, "别人的面板不受影响"
    assert _panel(mate, ws)[1] is None

    with SessionLocal() as db:
        assert {job.id for job in db.query(Job).filter(Job.workspace_id == ws)} == {plain, child, run, paid, running}
        assert db.query(TaskEvent).count() == events
        assert [row.value for row in db.query(WorkflowRunOutput).filter(WorkflowRunOutput.job_id == run)] == ["一段很长的模型回复"]
        assert {row.job_id for row in db.query(ProviderUsageEvent)} == {paid}
    #: 工作流页、定时任务页读的那份不看水位线
    assert {job["id"] for job in owner.get(f"/api/jobs?workspace_id={ws}&top_level=true").json()} == {plain, run, paid, running}


def test_显示已清掉的列水位线之前结束的_之后结束的回到面板上() -> None:
    owner = fresh_client("owner")
    ws = owner.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        old = _job(db, ws, ago=120)
        running = _job(db, ws, status="running", ago=120)
        db.commit()
    assert _panel(owner, ws, cleared=True) == ([], None), "没清过就没有「已清掉的」"

    owner.post(f"/api/jobs/center/clear?workspace_id={ws}")
    with SessionLocal() as db:
        #: 清空之后那个还在跑的结束了、又有一个新的结束了:它们结束在水位线之后,回到面板上
        job = db.get(Job, running)
        job.status = "succeeded"
        job.updated_at = now()
        later = _job(db, ws, ago=0)
        db.commit()

    shown, _ = _panel(owner, ws)
    assert set(shown) == {running, later}
    cleared, cleared_at = _panel(owner, ws, cleared=True)
    assert cleared == [old] and cleared_at is not None

    #: 再清一次,水位线往后挪,刚才那两条也收进「已清掉的」
    owner.post(f"/api/jobs/center/clear?workspace_id={ws}")
    assert _panel(owner, ws)[0] == []
    assert set(_panel(owner, ws, cleared=True)[0]) == {old, running, later}
    with SessionLocal() as db:
        assert db.query(JobCenterMark).count() == 1, "每人每个工作区一条,挪的是同一条"


def test_只读成员也能清自己的面板_不是工作区的人看不了也清不了() -> None:
    owner = fresh_client("owner")
    ws = owner.post("/api/workspaces", json={"name": "W"}).json()["id"]
    viewer = _join(owner, ws, "viewer", "viewer")
    stranger = second_client("stranger")
    with SessionLocal() as db:
        done = _job(db, ws)
        db.commit()

    assert viewer.post(f"/api/jobs/center/clear?workspace_id={ws}").status_code == 200, "只动自己的面板,不是写工作区"
    assert _panel(viewer, ws)[0] == []
    assert _panel(owner, ws)[0] == [done]

    assert stranger.get(f"/api/jobs/center?workspace_id={ws}").status_code in (403, 404)
    assert stranger.post(f"/api/jobs/center/clear?workspace_id={ws}").status_code in (403, 404)


def test_统计页的任务活动不看水位线() -> None:
    owner = fresh_client("owner")
    ws = owner.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        _job(db, ws, ago=60)
        _job(db, ws, status="failed", ago=60)
        db.commit()
    before = owner.get(f"/api/workspaces/{ws}/summary").json()
    owner.post(f"/api/jobs/center/clear?workspace_id={ws}")
    after = owner.get(f"/api/workspaces/{ws}/summary").json()
    assert (after["jobs_succeeded"], after["jobs_failed"]) == (before["jobs_succeeded"], before["jobs_failed"]) == (1, 1)
    assert after["daily"] == before["daily"]
