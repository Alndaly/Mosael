"""绑着的工作流被删了的定时任务,**不能再跑**。

真机反馈:工作流已经删了,任务页上也写着「绑定的工作流已删除」,可任务照样能启用、照样能点
「立即运行」—— 每点一次,运行记录里多一条 0.0 秒的「任务绑定的工作流不存在」。排程的任务更糟:
删工作流时任务仍是启用的,到点照样触发、照样失败,没有人去点它也一样。

不变式是「**启用着的任务一定跑得起来**」,由三处一起守:

  - 删工作流的那一刻,绑着它的任务同一个事务里停用(scheduler.stop_tasks_bound_to_workflow);
  - 建任务、打开开关、三个触发入口都先问一句跑不跑得起来(scheduler.ensure_runnable),
    跑不起来就当场拒绝,不开运行记录;
  - 库里已经留下的,由迁移 `disable-tasks-bound-to-deleted-workflows` 一次停掉。
"""

from __future__ import annotations

from datetime import timedelta

from app.core.db import SessionLocal
from app.db.models import Job, ScheduledTask, ScheduledTaskRun, Workflow, now
from app.workers.scheduler import tick
from tests.util import fresh_client

GRAPH = {"nodes": [{"id": "start", "type": "start", "config": {"params": {}}}], "edges": []}


def _workflow(client, ws: str, name: str = "流") -> str:
    return client.post("/api/workflows", json={"workspace_id": ws, "name": name, "graph": GRAPH}).json()["id"]


def _task(client, ws: str, workflow_id: str, trigger_type: str = "manual", **extra) -> dict:
    schedule = {"seconds": 3600} if trigger_type == "interval" else {}
    response = client.post("/api/scheduled-tasks", json={
        "workspace_id": ws, "name": "demo", "kind": "workflow", "trigger_type": trigger_type,
        "schedule": schedule, "payload": {"workflow_id": workflow_id, "params": {}}, **extra,
    })
    assert response.status_code == 200, response.text
    return response.json()


def _runs(task_id: str) -> int:
    with SessionLocal() as db:
        return db.query(ScheduledTaskRun).filter_by(scheduled_task_id=task_id).count()


def _orphan(client) -> tuple[str, dict]:
    """一个绑着的工作流已经被删掉的任务(经删除入口删,和真机上一样)。"""
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    workflow_id = _workflow(client, ws)
    task = _task(client, ws, workflow_id)
    assert client.delete(f"/api/workflows/{workflow_id}").status_code == 204
    return ws, task


class Test删工作流时任务当场停下:
    def test_绑着它的任务停用_排程也撤掉(self) -> None:
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        doomed = _workflow(client, ws, "要删的")
        kept = _workflow(client, ws, "留着的")
        hourly = _task(client, ws, doomed, trigger_type="interval")
        manual = _task(client, ws, doomed)
        other = _task(client, ws, kept, trigger_type="interval")
        assert hourly["next_run_at"] is not None

        assert client.delete(f"/api/workflows/{doomed}").status_code == 204

        tasks = {row["id"]: row for row in client.get(f"/api/scheduled-tasks?workspace_id={ws}").json()}
        assert tasks[hourly["id"]]["enabled"] is False and tasks[hourly["id"]]["next_run_at"] is None
        assert tasks[manual["id"]]["enabled"] is False
        # 任务本身留着(连同它指着的 id,界面据此说「绑定的工作流已删除」),删不删由人决定。
        assert tasks[manual["id"]]["payload"]["workflow_id"] == doomed
        # 绑着别的工作流的,不受牵连。
        assert tasks[other["id"]]["enabled"] is True and tasks[other["id"]]["next_run_at"] is not None


class Test跑不起来的任务打不开也跑不了:
    def test_打不开开关(self) -> None:
        client = fresh_client()
        _ws, task = _orphan(client)
        response = client.patch(f"/api/scheduled-tasks/{task['id']}", json={"enabled": True})
        assert response.status_code == 422 and "已删除" in response.text
        with SessionLocal() as db:
            assert db.get(ScheduledTask, task["id"]).enabled is False

    def test_拒绝的话跟着界面语言(self) -> None:
        client = fresh_client()
        _ws, task = _orphan(client)
        response = client.patch(
            f"/api/scheduled-tasks/{task['id']}", json={"enabled": True}, headers={"Accept-Language": "en"}
        )
        assert response.status_code == 422 and "was deleted" in response.text

    def test_立即运行当场拒绝_不开运行记录(self) -> None:
        client = fresh_client()
        _ws, task = _orphan(client)
        response = client.post(f"/api/scheduled-tasks/{task['id']}/run")
        assert response.status_code == 422 and "已删除" in response.text
        assert _runs(task["id"]) == 0
        with SessionLocal() as db:
            assert db.query(Job).filter(Job.kind == "workflow").count() == 0

    def test_webhook_也拒绝(self) -> None:
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        workflow_id = _workflow(client, ws)
        task = _task(client, ws, workflow_id, trigger_type="webhook")
        client.delete(f"/api/workflows/{workflow_id}")
        secret = task["payload"]["webhook_secret"]
        response = client.post(f"/api/hooks/scheduled-tasks/{task['id']}?secret={secret}")
        assert response.status_code == 409
        assert _runs(task["id"]) == 0

    def test_建不出一条绑着不存在工作流的启用任务(self) -> None:
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        response = client.post("/api/scheduled-tasks", json={
            "workspace_id": ws, "name": "x", "kind": "workflow", "trigger_type": "manual",
            "schedule": {}, "payload": {"workflow_id": "gone"},
        })
        assert response.status_code == 422 and "已删除" in response.text

    def test_改绑到在的工作流_同一次打开开关_可以(self) -> None:
        client = fresh_client()
        ws, task = _orphan(client)
        replacement = _workflow(client, ws, "新的")
        response = client.patch(
            f"/api/scheduled-tasks/{task['id']}",
            json={"enabled": True, "payload": {"workflow_id": replacement, "params": {}}},
        )
        assert response.status_code == 200, response.text
        assert response.json()["enabled"] is True

    def test_停用永远放行(self) -> None:
        """一个跑不起来的任务至少要关得掉 —— 哪怕它是在不变式成立之前就启用着的。"""
        client = fresh_client()
        _ws, task = _orphan(client)
        with SessionLocal() as db:
            db.get(ScheduledTask, task["id"]).enabled = True
            db.commit()
        response = client.patch(f"/api/scheduled-tasks/{task['id']}", json={"enabled": False})
        assert response.status_code == 200 and response.json()["enabled"] is False


def test_调度循环遇到跑不起来的任务_停掉它_不耽误别的() -> None:
    """万一有漏网的(不变式之外写进库的),一个任务的异常不能把这一轮后面所有到点的任务一起带走。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    healthy = _task(client, ws, _workflow(client, ws), trigger_type="interval")
    with SessionLocal() as db:
        broken = ScheduledTask(
            workspace_id=ws, name="坏的", kind="workflow", trigger_type="interval",
            schedule={"seconds": 3600}, enabled=True, payload={"workflow_id": "gone"},
            next_run_at=now() - timedelta(seconds=10),
        )
        db.add(broken)
        db.get(ScheduledTask, healthy["id"]).next_run_at = now() - timedelta(seconds=5)
        db.commit()
        broken_id = broken.id

    with SessionLocal() as db:
        created = tick(db)
    assert len(created) == 1
    assert _runs(healthy["id"]) == 1 and _runs(broken_id) == 0
    with SessionLocal() as db:
        broken = db.get(ScheduledTask, broken_id)
        assert broken.enabled is False and broken.next_run_at is None


def test_迁移停掉库里已有的孤儿任务_再跑一次什么都不做() -> None:
    from app.db.migrations import _disable_tasks_bound_to_deleted_workflows

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    other_ws = client.post("/api/workspaces", json={"name": "别人的"}).json()["id"]
    alive = _workflow(client, ws)
    foreign = _workflow(client, other_ws, "别人的流")
    with SessionLocal() as db:
        #: 直接写行,绕过建任务的检查 —— 模拟删除路径还不管定时任务时留下的数据。
        def seed(name: str, payload: dict, enabled: bool = True) -> str:
            task = ScheduledTask(
                workspace_id=ws, name=name, kind="workflow", trigger_type="interval",
                schedule={"seconds": 3600}, enabled=enabled, payload=payload,
                next_run_at=now() + timedelta(hours=1),
            )
            db.add(task)
            db.flush()
            return task.id

        orphan = seed("孤儿", {"workflow_id": "deleted-long-ago"})
        unbound = seed("没绑", {})
        cross = seed("别的工作区的", {"workflow_id": foreign})
        good = seed("好的", {"workflow_id": alive})
        already_off = seed("本来就停着", {"workflow_id": "deleted-long-ago"}, enabled=False)
        db.commit()

    _disable_tasks_bound_to_deleted_workflows()
    _disable_tasks_bound_to_deleted_workflows()

    with SessionLocal() as db:
        for task_id in (orphan, unbound, cross):
            task = db.get(ScheduledTask, task_id)
            assert task.enabled is False and task.next_run_at is None, task.name
        # 任务本身留着,只动开关:界面还要据这个 id 说「绑定的工作流已删除」。
        assert db.get(ScheduledTask, orphan).payload == {"workflow_id": "deleted-long-ago"}
        assert db.get(ScheduledTask, already_off).enabled is False
        kept = db.get(ScheduledTask, good)
        assert kept.enabled is True and kept.next_run_at is not None
        assert db.get(Workflow, alive) is not None
