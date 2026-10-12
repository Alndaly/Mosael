"""migrate-generation-result-deleted-backfill:老的生成记录补上「产出已被删除」。

`5b7cfd418` 给 `generation_jobs` 加了 `result_deleted_at`,却只 `ALTER TABLE ADD COLUMN` —— **一行都没回填**,
而它要治的正是已经发生过的那批:产出删了(`result_asset_id` 被 SET NULL)、任务行也被「清空已结束」删过
(`job_id` 被 SET NULL),记录上没结果、没失败,和「还在排队」长得一模一样。

钉住四件事:该填的填上、**填的是记录自己的 `updated_at` 而不是 `now()`**、不该动的一行都不动
(在排队的、已完成的、自己记着失败的)、再跑一次什么都不变。
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_generation_result_deleted_backfill as migrate
from app.db.models import GenerationJob, Job
from tests.util import fresh_client, insert_asset

#: 老形状的时间:这一条生成最后一次真的被写过的那一刻(登记产出),不是「刚刚」。
_WRITTEN_AT = "2026-07-23 09:25:57.921368"


def _legacy() -> dict[str, str]:
    """造一份老库的形状,四种行都有。返回 `{名字: 生成记录 id}`。"""
    workspace = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    #: 两份素材要在开会话**之前**建好:`insert_asset` 自己开一个会话并提交,而下面那个会话手上攥着写锁
    #: —— 同一个线程的另一个会话等不到它放手(SQLite 只有一把写锁)。
    kept = insert_asset(workspace, kind="image", name="还在的产出")
    doomed = insert_asset(workspace, kind="image", name="被删的产出")
    results = {"completed": kept, "deleted": doomed}
    with SessionLocal() as db:
        ids: dict[str, str] = {}
        for name in ("deleted", "queued", "completed", "failed_orphan"):
            job = Job(workspace_id=workspace, kind="ai_generation", status="queued", payload={})
            db.add(job)
            db.flush()
            #: 「产出被删」那条一开始确实指着产出:素材行删掉之后,外键(SET NULL)把这一栏清空。
            generation = GenerationJob(
                workspace_id=workspace, job_id=job.id, provider="test", model="m", kind="image", request={},
                result_asset_id=results.get(name),
            )
            db.add(generation)
            db.flush()
            ids[name] = generation.id
            ids[f"job_{name}"] = job.id
        db.commit()
    #: 老形状直接写进库(新代码写不出这个样子):产出素材删掉、三个任务行被旧版「清空已结束」删掉
    #: (两条外键都是 SET NULL,于是 result_asset_id / job_id 一起置空),时间戳定格在那一天。
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM assets WHERE id = :id"), {"id": doomed})
        for name in ("deleted", "completed", "failed_orphan"):
            conn.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": ids[f"job_{name}"]})
        conn.execute(
            text("UPDATE generation_jobs SET created_at = :at, updated_at = :at WHERE id = :id"),
            {"at": _WRITTEN_AT, "id": ids["deleted"]},
        )
        #: 失败原因只在任务行上的那种老形状:任务行一删,原因就没了。这样的一条**不能**被改写成
        #: 「产出已被删除」—— 它从来没有过产出。新形状的失败带 error,两种都放进来。
        conn.execute(
            text("UPDATE generation_jobs SET error = '连不上', error_key = 'aiErr_network' WHERE id = :id"),
            {"id": ids["failed_orphan"]},
        )
    with SessionLocal() as db:
        assert db.get(GenerationJob, ids["deleted"]).result_asset_id is None, "素材删了,引用照常被 SET NULL"
        assert db.get(GenerationJob, ids["deleted"]).job_id is None, "任务行删了,引用照常被 SET NULL"
    return ids


def _rows(ids: dict[str, str]) -> dict[str, tuple]:
    """库里原样的几列(不经 ORM 转换):时间戳比的就是写进去的那个字符串。"""
    with engine.begin() as conn:
        return {
            name: tuple(
                conn.execute(
                    text(
                        "SELECT result_asset_id, job_id, error, error_key, result_deleted_at, updated_at "
                        "FROM generation_jobs WHERE id = :id"
                    ),
                    {"id": ids[name]},
                ).one()
            )
            for name in ("deleted", "queued", "completed", "failed_orphan")
        }


def _marked() -> int:
    with engine.begin() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM generation_jobs WHERE result_deleted_at IS NOT NULL")
        ).scalar_one()


def test_产出和任务行都没了的那批补上被删时间_别的行不动_再跑一次什么都不变() -> None:
    ids = _legacy()
    before = _rows(ids)
    assert before["deleted"][4] is None and before["queued"][4] is None

    migrate()

    after = _rows(ids)
    #: 填的是记录自己的 updated_at(那一天),不是 now()。
    assert after["deleted"][4] == after["deleted"][5] == _WRITTEN_AT
    assert after["deleted"][:4] == before["deleted"][:4], "只添那一列,别的列一个字都不改"
    #: 在排队的(任务行还在,所以它不可能是「产出被删」)不动。
    assert after["queued"] == before["queued"], "还在排队的不许被碰"
    #: 已完成的(产出还在)不动。
    assert after["completed"] == before["completed"], "有产出的不许被碰"
    #: 自己记着失败的不动:它没有过产出,原因也还在。
    assert after["failed_orphan"] == before["failed_orphan"], "记录自己说失败的不许被改写"
    assert _marked() == 1

    migrate()

    assert _rows(ids) == after, "再跑一次:一行都不该再变"
    assert _marked() == 1


def test_没有被删产出那一段的库上什么都不做() -> None:
    """全是在排队的 / 已完成的:跑完一行记号都不该多出来。"""
    workspace = fresh_client().post("/api/workspaces", json={"name": "W2"}).json()["id"]
    kept = insert_asset(workspace, kind="image", name="产出")
    with SessionLocal() as db:
        job = Job(workspace_id=workspace, kind="ai_generation", status="queued", payload={})
        db.add(job)
        db.flush()
        db.add(GenerationJob(workspace_id=workspace, job_id=job.id, provider="test", model="m", kind="image",
                             request={}, result_asset_id=kept))
        db.commit()

    migrate()

    assert _marked() == 0
