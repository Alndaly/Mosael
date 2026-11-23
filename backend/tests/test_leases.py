"""认领 / 租约协议(`domain/leases`)本身:任务总线和浏览器动作都用它,这里不经 HTTP 直接测。

此前两份各写一套:令牌一处 `token_hex(24)`、一处 `uuid4().hex`,令牌比对一处常数时间、一处 `!=`,
过期判定一处锁行复核、一处查完就判(心跳刚续上的动作被误判失败)。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.db import SessionLocal
from app.db.models import Job, now
from app.domain import jobs as jobs_bus
from app.domain import leases
from app.domain.jobs import create_job, expire_worker_leases
from tests.util import fresh_client


@pytest.fixture()
def external_demo(monkeypatch):
    monkeypatch.setattr(jobs_bus, "_EXECUTION_MODES", {**jobs_bus._EXECUTION_MODES, "demo": "external"})


def _queued_job() -> str:
    workspace_id = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        job = create_job(db, created_by=None, workspace_id=workspace_id, kind="demo", payload={})
        db.commit()
        return job.id


def test_claim_is_a_cas_and_hands_out_one_token(external_demo) -> None:
    job_id = _queued_job()
    with SessionLocal() as db:
        first = leases.claim(db, Job, job_id, worker="w1", from_statuses=("queued",))
        second = leases.claim(db, Job, job_id, worker="w2", from_statuses=("queued",))
        db.commit()
        job = db.get(Job, job_id)
        assert first is not None and second is None
        assert (job.status, job.lease_worker, job.lease_token) == ("running", "w1", first)
        assert job.lease_expires_at > now()


def test_only_the_holder_renews(external_demo) -> None:
    job_id = _queued_job()
    with SessionLocal() as db:
        token = leases.claim(db, Job, job_id, worker="w1", from_statuses=("queued",))
        db.commit()
        assert leases.renew(db, Job, worker="w2", claims=[(job_id, token)]) == []
        assert leases.renew(db, Job, worker="w1", claims=[(job_id, "wrong")]) == []
        assert leases.renew(db, Job, worker="w1", claims=[(job_id, token)]) == [job_id]


def test_holds_compares_tokens_and_survives_any_input(external_demo) -> None:
    job_id = _queued_job()
    with SessionLocal() as db:
        token = leases.claim(db, Job, job_id, worker="w1", from_statuses=("queued",))
        db.commit()
        job = db.get(Job, job_id)
        assert leases.holds(job, token)
        assert not leases.holds(job, None)
        #: 回报方随便给的令牌:含非 ASCII 也只是「不对」,不是一个 500(compare_digest 收 str 会抛)。
        assert not leases.holds(job, "不是令牌")


def test_a_renewal_between_the_candidate_query_and_the_lock_wins(external_demo, monkeypatch) -> None:
    """查出候选之后、拿到写锁之前心跳续上了:锁住重读后发现没到点,不判失败。"""
    job_id = _queued_job()
    with SessionLocal() as db:
        leases.claim(db, Job, job_id, worker="w1", from_statuses=("queued",))
        db.get(Job, job_id).lease_expires_at = now() - timedelta(seconds=1)
        db.commit()

    real_lock = jobs_bus.lock_active_job

    def renew_first(db, job):
        with SessionLocal() as heartbeat:
            #: 心跳在「到点前一刻」续上:直接把到期时间推后(续约本身要求还没到点,这里没法用它造出这一拍)。
            heartbeat.get(Job, job_id).lease_expires_at = leases.expires_at()
            heartbeat.commit()
        return real_lock(db, job)

    monkeypatch.setattr(jobs_bus, "lock_active_job", renew_first)
    with SessionLocal() as db:
        assert expire_worker_leases(db) == 0
        assert db.get(Job, job_id).status == "running"


def test_an_expired_lease_is_settled(external_demo) -> None:
    job_id = _queued_job()
    with SessionLocal() as db:
        leases.claim(db, Job, job_id, worker="w1", from_statuses=("queued",))
        db.get(Job, job_id).lease_expires_at = now() - timedelta(seconds=1)
        db.commit()
        assert expire_worker_leases(db) == 1
        db.expire_all()
        assert db.get(Job, job_id).status == "failed"
