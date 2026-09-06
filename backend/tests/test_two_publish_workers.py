"""两个发布执行器同时跑的时候,不能互相拆台。

回收悬挂任务的判据有两条:

1. **「这个账号不在我当前在跑的集合里」** —— 只有**认领者**说了才算数。拿自己的集合去判
   别人的任务,结论必然是"孤儿":于是 B 的每一次轮询都会把 A 正在跑的任务标成失败,
   错误文案还写着「发布器中断,请到平台确认是否已发布」,而 A 跑得好好的。
2. **「多久没动静了」** —— 这条必须是全局的。执行器彻底死掉之后没人再来认领它的任务,
   只有这条能把它们收回来;限制成只有认领者能判,等于它们永远挂着。

另外,一个平台账号同时被两条任务驱动是不行的(登录态、上传队列都只有一份)。此前唯一的
守卫是调用方自报的 exclude_accounts —— 在多执行器下等于没有守卫:B 不知道 A 在跑哪个账号。
"""

from __future__ import annotations

from datetime import timedelta

from app.core.db import SessionLocal
from app.core.worker_key import WORKER_KEY_HEADER, current_worker_key
from app.db.models import PublishTask, now
from tests.test_publish_worker import setup_browser_task
from tests.util import fresh_client


def _client():
    client = fresh_client()
    client.headers[WORKER_KEY_HEADER] = current_worker_key() or ""
    return client


def _claim(client, worker: str, exclude: list[str] | None = None):
    body = {"exclude_accounts": exclude or [], "worker": worker}
    return client.post("/api/publish/worker/claim", json=body).json()["task"]


def _status(task_id: str) -> str:
    with SessionLocal() as db:
        return db.get(PublishTask, task_id).status


def test_另一个执行器的轮询不会把我的任务判成中断() -> None:
    client = _client()
    _, account, task = setup_browser_task(client)

    claimed = _claim(client, worker="worker-a")
    assert claimed and claimed["id"] == task["id"]
    assert _status(task["id"]) == "running"

    # B 上线,自己什么都没跑。它**不认识** A 的任务,不该去动它。
    _claim(client, worker="worker-b")
    assert _status(task["id"]) == "running", "B 的轮询把 A 正在跑的任务标成了失败"

    # 再来几轮也一样 —— 此前每一轮都会重新判一次。
    for _ in range(3):
        _claim(client, worker="worker-b")
    assert _status(task["id"]) == "running"


def test_认领者自己重启后仍然收得回自己的孤儿() -> None:
    """身份是**跨重启稳定**的,所以 A 重启后第一拍就能认出自己那些没跑完的
    —— 这是判据 1 存在的全部理由,不能因为加了归属就丢掉。"""
    client = _client()
    _, account, task = setup_browser_task(client)
    _claim(client, worker="worker-a")

    # A 重启:在跑的集合空了,但名字还是 worker-a。
    _claim(client, worker="worker-a", exclude=[])
    assert _status(task["id"]) == "failed"


def test_执行器彻底死掉的任务由超时兜底() -> None:
    """判据 2 是全局的:A 再也不上线了,它的任务只能靠"多久没动静"收回来。"""
    from app.domain.publish.worker import STALE_RUNNING_MINUTES

    client = _client()
    _, account, task = setup_browser_task(client)
    _claim(client, worker="worker-a")

    with SessionLocal() as db:
        row = db.get(PublishTask, task["id"])
        row.updated_at = now() - timedelta(minutes=STALE_RUNNING_MINUTES + 1)
        db.commit()

    _claim(client, worker="worker-b")
    assert _status(task["id"]) == "failed", "死掉的执行器留下的任务没人收"


def test_同一个账号不会被两个执行器同时认领() -> None:
    """一个平台账号只有一份登录态和一条上传队列。此前唯一的守卫是调用方自报的
    exclude_accounts —— B 不知道 A 在跑哪个账号,照样会认领同账号的下一条。"""
    client = _client()
    ws, account, first = setup_browser_task(client)
    asset_id = first["asset_id"]
    second = client.post(
        "/api/publish/tasks",
        json={
            "workspace_id": ws["id"],
            "account_id": account["id"],
            "asset_id": asset_id,
            "title": "同一个账号的第二条",
            "description": "",
            "tags": [],
        },
    ).json()

    assert _claim(client, worker="worker-a")["id"] == first["id"]
    # B 空手上线,同一个账号那条不该给它。
    assert _claim(client, worker="worker-b") is None
    assert _status(second["id"]) == "pending"


def test_不报身份的执行器行为不变() -> None:
    """单执行器部署(老执行器不带 worker 字段)照旧:认领、重启后自愈,一切不变。"""
    client = _client()
    _, account, task = setup_browser_task(client)
    got = client.post("/api/publish/worker/claim", json={"exclude_accounts": []}).json()["task"]
    assert got["id"] == task["id"]
    assert _status(task["id"]) == "running"
    # 空手再来一轮 = 老的"重启即自愈"路径。
    client.post("/api/publish/worker/claim", json={"exclude_accounts": []})
    assert _status(task["id"]) == "failed"
