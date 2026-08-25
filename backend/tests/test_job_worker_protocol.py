"""通用 job worker 协议:执行模式接缝 + claim/report 语义。

发布器验证过的拉取模式推广给所有 external kind。这里守住的语义:

- in_process 是默认;publish 由自己的领域注册为 external。
- dispatch_job:in_process 立刻起线程,external 留在 queued 等认领。
- claim 只允许 external kind、按创建序、CAS 原子、认领即 running。
- report:running 推进度;终态(含用户取消)不给后到的回报复活。
- reconcile 只孤儿化 in_process kind。
"""

from __future__ import annotations

import threading

import pytest

from app.core.db import SessionLocal
from app.core.worker_key import WORKER_KEY_HEADER, current_worker_key
from app.db.models import Job
from app.domain import jobs as jobs_bus
from app.domain.jobs import (
    cancel_job,
    claim_next_job,
    create_job,
    dispatch_job,
    execution_mode,
    external_kinds,
    reconcile_orphaned_jobs,
    report_job,
)
from tests.util import add_provider, fresh_client


@pytest.fixture()
def external_demo(monkeypatch):
    """把 demo kind 临时注册为 external,不污染全局注册表。"""
    monkeypatch.setattr(jobs_bus, "_EXECUTION_MODES", {**jobs_bus._EXECUTION_MODES, "demo": "external"})


def _make_job(workspace_id: str, kind: str = "demo") -> str:
    with SessionLocal() as db:
        job = create_job(db, created_by=None, workspace_id=workspace_id, kind=kind, payload={"n": 1})
        db.commit()
        return job.id


def _workspace() -> str:
    client = fresh_client()
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


class TestExecutionModes:
    def test_in_process_is_the_default(self) -> None:
        assert execution_mode("render") == "in_process"
        assert execution_mode("never-heard-of-it") == "in_process"

    def test_publish_registers_itself_external(self) -> None:
        import app.domain.publish  # noqa: F401 — 注册发生在领域导入时

        assert execution_mode("publish") == "external"
        assert "publish" in external_kinds()

    def test_dispatch_runs_in_process_kinds_on_a_thread(self) -> None:
        workspace_id = _workspace()
        ran = threading.Event()
        with SessionLocal() as db:
            job = create_job(db, created_by=None, workspace_id=workspace_id, kind="demo", payload={})
            started = dispatch_job(db, job, ran.set)
        assert started is True
        assert ran.wait(timeout=5)

    def test_dispatch_leaves_external_kinds_queued(self, external_demo) -> None:
        workspace_id = _workspace()
        with SessionLocal() as db:
            job = create_job(db, created_by=None, workspace_id=workspace_id, kind="demo", payload={})
            started = dispatch_job(db, job, lambda: pytest.fail("external kind 不该起线程"))
            assert started is False
            db.refresh(job)
            assert job.status == "queued"
            assert job.message == "等待执行器认领"


class TestClaim:
    def test_claim_returns_oldest_and_flips_running(self, external_demo) -> None:
        workspace_id = _workspace()
        first = _make_job(workspace_id)
        second = _make_job(workspace_id)
        with SessionLocal() as db:
            job = claim_next_job(db, worker="w1")
            assert job is not None and job.id == first
            assert job.status == "running"
            assert claim_next_job(db, worker="w1").id == second
            assert claim_next_job(db, worker="w1") is None

    def test_claim_refuses_in_process_kinds(self) -> None:
        workspace_id = _workspace()
        _make_job(workspace_id, kind="demo")  # 未注册 → in_process
        with SessionLocal() as db:
            assert claim_next_job(db, kinds=["demo"]) is None

    def test_claim_filters_by_requested_kinds(self, external_demo) -> None:
        workspace_id = _workspace()
        _make_job(workspace_id, kind="demo")
        with SessionLocal() as db:
            assert claim_next_job(db, kinds=["publish"]) is None
            assert claim_next_job(db, kinds=["demo"]) is not None


class TestReport:
    def test_running_report_updates_progress(self, external_demo) -> None:
        workspace_id = _workspace()
        job_id = _make_job(workspace_id)
        with SessionLocal() as db:
            job = claim_next_job(db)
            report_job(db, job, status="running", progress=0.4, message="干活中")
            db.refresh(job)
            assert job.status == "running" and job.progress == 0.4 and job.message == "干活中"

    def test_success_report_finalizes_with_result(self, external_demo) -> None:
        workspace_id = _workspace()
        _make_job(workspace_id)
        with SessionLocal() as db:
            job = claim_next_job(db)
            report_job(db, job, status="succeeded", result={"asset_id": "a1"})
            db.refresh(job)
            assert job.status == "succeeded" and job.progress == 1.0
            assert job.result == {"asset_id": "a1"}

    def test_a_cancelled_job_is_not_resurrected_by_a_late_report(self, external_demo) -> None:
        """worker 是在为一个已经不存在的意图干活——与发布器同一条规则。"""
        workspace_id = _workspace()
        _make_job(workspace_id)
        with SessionLocal() as db:
            job = claim_next_job(db)
            cancel_job(db, job)
            report_job(db, job, status="succeeded", result={"asset_id": "a1"})
            db.refresh(job)
            assert job.status == "failed" and job.error == "已取消"
            assert job.result != {"asset_id": "a1"}

    def test_unknown_status_is_rejected(self, external_demo) -> None:
        workspace_id = _workspace()
        _make_job(workspace_id)
        with SessionLocal() as db:
            job = claim_next_job(db)
            with pytest.raises(ValueError):
                report_job(db, job, status="prepared")


class TestReconcile:
    def test_reconcile_spares_external_kinds(self, external_demo) -> None:
        workspace_id = _workspace()
        external_id = _make_job(workspace_id, kind="demo")
        orphan_id = _make_job(workspace_id, kind="render")
        with SessionLocal() as db:
            reconcile_orphaned_jobs(db)
            assert db.get(Job, external_id).status == "queued"
            orphan = db.get(Job, orphan_id)
            assert orphan.status == "failed" and "重启" in orphan.error


class TestHttpChannel:
    """路由层:worker key 门 + 请求/响应形状。"""

    def _headers(self) -> dict[str, str]:
        return {WORKER_KEY_HEADER: current_worker_key() or ""}

    def test_the_channel_requires_the_worker_key(self, external_demo) -> None:
        client = fresh_client()
        assert client.post("/api/jobs/worker/claim", json={}).status_code in (401, 403)

    def test_claim_report_roundtrip_over_http(self, external_demo) -> None:
        client = fresh_client()
        workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        job_id = _make_job(workspace_id)

        claimed = client.post(
            "/api/jobs/worker/claim", json={"worker": "w1", "kinds": ["demo"]}, headers=self._headers()
        ).json()
        assert claimed["job"]["id"] == job_id
        assert claimed["job"]["payload"] == {"n": 1}

        reported = client.patch(
            "/api/jobs/worker/report",
            json={"job_id": job_id, "status": "succeeded", "result": {"ok": True}},
            headers=self._headers(),
        ).json()
        assert reported["status"] == "succeeded"

        beat = client.post(
            "/api/jobs/worker/heartbeat", json={"worker": "w1", "kinds": ["demo"]}, headers=self._headers()
        ).json()
        assert beat["ok"] is True and "demo" in beat["external_kinds"]


class TestDispatchWiring:
    """transcribe / tts / ai_generation 翻成 external 后:任务只入队等认领,不起线程。"""

    def _external(self, monkeypatch, *kinds: str) -> None:
        monkeypatch.setattr(
            jobs_bus, "_EXECUTION_MODES", {**jobs_bus._EXECUTION_MODES, **{k: "external" for k in kinds}}
        )

    def test_transcribe_respects_external_mode(self, monkeypatch) -> None:
        from app.domain.voices.service import start_transcription
        from app.db.models import Asset

        self._external(monkeypatch, "transcribe")
        workspace_id = _workspace()
        with SessionLocal() as db:
            asset = Asset(workspace_id=workspace_id, name="a", kind="video", file_key="media/a.mp4")
            db.add(asset)
            db.commit()
            job = start_transcription(db, asset.id, created_by=None)
            db.refresh(job)
            assert job.status == "queued" and job.message == "等待执行器认领"
            assert claim_next_job(db, kinds=["transcribe"]).id == job.id

    def test_tts_respects_external_mode(self, monkeypatch) -> None:
        from app.domain.voices.voices import start_synthesis

        self._external(monkeypatch, "tts")
        workspace_id = _workspace()
        with SessionLocal() as db:
            job = start_synthesis(
            db,
            created_by=None, text="你好", project_id=None, workspace_id=workspace_id, engine="f5")
            db.refresh(job)
            assert job.status == "queued"
            assert claim_next_job(db, kinds=["tts"]).id == job.id

    def test_generation_respects_external_mode(self, monkeypatch) -> None:
        from app.domain.generation import create_generation_job
        from app.domain.generation.runner import start_generation_thread

        self._external(monkeypatch, "ai_generation")
        workspace_id = _workspace()
        # 生成任务现在按"用户配了哪条连接"校验(不再查内置目录表),所以先配一条阿里云的。
        with SessionLocal() as db:
            from app.db.models import ProviderProfile
            from app.domain import provider_models

            profile = add_provider(db, name="百炼", vendor="alibaba", base_url="", api_key="k")
            db.flush()
            provider_models.upsert(db, profile, "qwen-image", capability_ids=["image"])
            db.commit()
        with SessionLocal() as db:
            generation, job = create_generation_job(
            db,
            created_by=None,
                workspace_id=workspace_id,
                session_id=None,
                project_id=None,
                provider="alibaba",
                model="qwen-image",
                kind="image",
                prompt="p",
                negative_prompt="",
                parameters={},
                source_assets=[],
            )
            db.commit()
            generation_id, job_id = generation.id, job.id
        start_generation_thread(generation_id)
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            assert job.status == "queued" and job.message == "等待执行器认领"
            assert claim_next_job(db, kinds=["ai_generation"]).id == job_id
