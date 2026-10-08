"""定时任务归主人管,触发密钥只存哈希(体检 UM-02 / SEC-1 / SEC-2)。

此前两条连在一起:
- 列表接口把 `payload.webhook_secret` 原样发给工作区里每个人 —— 只读成员拿着它不用登录就能触发、取消以主人身份跑的运行;
- 改、删、重置密钥、立即运行只查 editor —— 同事能把别人的任务改绑到自己的工作流,再「立即运行」,用别人的钥匙和额度跑。

现在:密钥原文只在生成它的那一次响应里出现一次(库里是 `sha256:` 哈希);管一个任务只有它的主人(ADR 0008 §3.9 同一条)。
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_webhook_secrets_are_hashed
from app.db.models import ScheduledTask
from tests.util import fresh_client, second_client


def _team(role: str):
    owner = fresh_client("owner")
    ws = owner.post("/api/workspaces", json={"name": "W"}).json()["id"]
    mate = second_client("mate")
    assert owner.post(f"/api/workspaces/{ws}/invitations", json={"username": "mate", "role": role}).status_code == 200
    invitation = mate.get("/api/invitations").json()["invitations"][0]["id"]
    assert mate.post(f"/api/invitations/{invitation}/accept").status_code == 200
    workflow = owner.post("/api/workflows", json={"workspace_id": ws, "name": "钩子流", "graph": {
        "nodes": [{"id": "start", "type": "start", "config": {"params": {}}}], "edges": []}}).json()
    return owner, mate, ws, workflow


def _webhook(client, ws: str, workflow: dict) -> dict:
    created = client.post("/api/scheduled-tasks", json={
        "workspace_id": ws, "name": "钩子任务", "kind": "workflow", "trigger_type": "webhook",
        "schedule": {}, "payload": {"workflow_id": workflow["id"], "params": {}},
    })
    assert created.status_code == 200, created.text
    return created.json()


def test_密钥原文只在生成的那一次出现_列表里谁都看不到_库里只存哈希() -> None:
    owner, viewer, ws, workflow = _team("viewer")
    task = _webhook(owner, ws, workflow)
    secret = task["webhook_secret"]
    assert secret and task["webhook_secret_set_at"]
    assert "webhook_secret" not in task["payload"]

    for client in (owner, viewer):
        listed = next(one for one in client.get(f"/api/scheduled-tasks?workspace_id={ws}").json() if one["id"] == task["id"])
        assert listed["webhook_secret"] is None
        assert secret not in str(listed)

    with SessionLocal() as db:
        row = db.get(ScheduledTask, task["id"])
        assert row.webhook_secret_hash and row.webhook_secret_hash.startswith("sha256:")
        assert secret not in str(row.payload) and secret not in row.webhook_secret_hash

    hook = f"/api/hooks/scheduled-tasks/{task['id']}"
    assert owner.post(f"{hook}?secret=wrong").status_code == 403
    assert owner.post(f"{hook}?secret={secret}").status_code == 200


def test_管任务只有主人_同事是编辑也不行() -> None:
    owner, mate, ws, workflow = _team("editor")
    task = _webhook(owner, ws, workflow)
    mine = mate.post("/api/workflows", json={"workspace_id": ws, "name": "同事的流", "graph": {
        "nodes": [{"id": "start", "type": "start", "config": {"params": {}}}], "edges": []}}).json()
    url = f"/api/scheduled-tasks/{task['id']}"

    attempts = {
        "改绑到自己的工作流": mate.patch(url, json={"payload": {"workflow_id": mine["id"], "params": {}}}),
        "停用": mate.patch(url, json={"enabled": False}),
        "重置密钥": mate.post(f"{url}/webhook-secret"),
        "立即运行": mate.post(f"{url}/run"),
        "删除": mate.delete(url),
    }
    for what, response in attempts.items():
        assert response.status_code == 403, f"{what}: {response.status_code} {response.text}"
    assert "只有主人" in mate.patch(url, json={"enabled": False}, headers={"Accept-Language": "zh-CN"}).json()["detail"]

    with SessionLocal() as db:
        row = db.get(ScheduledTask, task["id"])
        assert row.payload["workflow_id"] == workflow["id"] and row.enabled

    # 同事照样看得见它、看得见它跑得怎样;主人自己什么都能做。
    assert any(one["id"] == task["id"] and not one["is_mine"] for one in mate.get(f"/api/scheduled-tasks?workspace_id={ws}").json())
    assert mate.get(f"{url}/runs").status_code == 200
    assert owner.post(f"{url}/run").status_code == 200
    assert owner.patch(url, json={"enabled": False}).status_code == 200
    assert owner.delete(url).status_code == 204


def test_重置和改回webhook都换一把新的_旧地址不会复活() -> None:
    owner, _, ws, workflow = _team("editor")
    task = _webhook(owner, ws, workflow)
    first = task["webhook_secret"]
    url = f"/api/scheduled-tasks/{task['id']}"
    hook = f"/api/hooks/scheduled-tasks/{task['id']}"

    rotated = owner.post(f"{url}/webhook-secret").json()
    second = rotated["webhook_secret"]
    assert second and second != first and rotated["webhook_secret_set_at"]
    assert owner.post(f"{hook}?secret={first}").status_code == 403

    manual = owner.patch(url, json={"trigger_type": "manual"}).json()
    assert manual["webhook_secret"] is None and manual["webhook_secret_set_at"] is None
    back = owner.patch(url, json={"trigger_type": "webhook"}).json()
    third = back["webhook_secret"]
    assert third and third not in (first, second)
    assert owner.post(f"{hook}?secret={second}").status_code == 403
    assert owner.post(f"{hook}?secret={third}").status_code == 200


def test_客户端带来的密钥一律不收() -> None:
    owner, _, ws, workflow = _team("editor")
    chosen = "i-picked-this-myself"
    created = owner.post("/api/scheduled-tasks", json={
        "workspace_id": ws, "name": "钩子任务", "kind": "workflow", "trigger_type": "webhook",
        "schedule": {}, "payload": {"workflow_id": workflow["id"], "params": {}, "webhook_secret": chosen},
    }).json()
    assert created["webhook_secret"] != chosen and "webhook_secret" not in created["payload"]
    assert owner.post(f"/api/hooks/scheduled-tasks/{created['id']}?secret={chosen}").status_code == 403


def test_老库里的明文密钥换成哈希_外部系统手上那串照样能用_提醒重置() -> None:
    owner, _, ws, workflow = _team("editor")
    task = _webhook(owner, ws, workflow)
    old = "an-old-plaintext-secret"
    # 造一行「改成只存哈希之前」的样子:明文在 payload 里,没有哈希列。
    with engine.begin() as conn:
        conn.execute(text("UPDATE scheduled_tasks SET webhook_secret_hash = NULL, webhook_secret_set_at = NULL, "
                          "payload = json_set(payload, '$.webhook_secret', :old) WHERE id = :id"), {"old": old, "id": task["id"]})
        conn.execute(text("ALTER TABLE scheduled_tasks DROP COLUMN webhook_secret_hash"))
        conn.execute(text("ALTER TABLE scheduled_tasks DROP COLUMN webhook_secret_set_at"))
    engine.dispose()
    assert "webhook_secret_hash" not in {column["name"] for column in inspect(engine).get_columns("scheduled_tasks")}

    _migrate_webhook_secrets_are_hashed()
    _migrate_webhook_secrets_are_hashed()  # 每次启动都会跑:再跑一次什么都不变
    engine.dispose()

    listed = next(one for one in owner.get(f"/api/scheduled-tasks?workspace_id={ws}").json() if one["id"] == task["id"])
    assert "webhook_secret" not in listed["payload"] and listed["payload"]["workflow_id"] == workflow["id"]
    assert listed["webhook_secret_set_at"] is None, "曾经对所有人可见的那把:界面据此提醒重置"
    assert owner.post(f"/api/hooks/scheduled-tasks/{task['id']}?secret={old}").status_code == 200


def test_改删跑的路由都过主人这道闸() -> None:
    """形状:定时任务路由文件里每条带 `{task_id}` 的写入路由,都落到过 `manageable_task` 的用例上(看运行记录是读,不算)。"""
    import ast
    import inspect
    import pathlib

    from app.domain.scheduler import use_cases

    gated = {name for name in ("update", "delete", "rotate_secret", "run_now")
             if "manageable_task(" in inspect.getsource(getattr(use_cases, name))}
    assert gated == {"update", "delete", "rotate_secret", "run_now"}

    checked, bad = 0, []
    tree = ast.parse(pathlib.Path("app/api/routes/scheduler.py").read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for deco in fn.decorator_list:
            if not (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr in ("patch", "post", "put", "delete")):
                continue
            path = deco.args[0].value if deco.args and isinstance(deco.args[0], ast.Constant) else ""
            if "{task_id}" not in path:
                continue
            checked += 1
            calls = {n.func.attr for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and isinstance(n.func.value, ast.Name) and n.func.value.id == "scheduler"}
            if not calls & gated:
                bad.append(f"{fn.name} {path}")
    assert checked >= 4, "扫到的写入路由太少 —— 扫描本身坏了"
    assert not bad, "这些路由改了定时任务却没过主人那道闸:\n  " + "\n  ".join(bad)
