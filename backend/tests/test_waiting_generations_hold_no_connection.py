"""在等远端的生成任务不占着数据库连接。

连接池 5 + 10 = 15 条,任务派发上限 16。此前每个在等远端的生成每轮轮询都 `db.refresh(job)` 问一句「被取消了吗」:
在运行器的长会话上开一个读事务、之后再不提交,于是整个等待期(几分钟到六小时)都攥着一条连接。十五个视频同时在等
(画板一排格子、智能体一次开十个镜头、团队里几个人同时生成),整个后端的请求等满 30 秒后报 500。同步的付费调用
(一次 POST 两三分钟)同样攥着:调适配器之前那个读事务没结束。

现在:调适配器之前结束读事务;等待中读写任务行(取消、回执、断线提示)各开各的短会话。
不调真实接口:假适配器 + 真的 `poll_until_ready`。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy

from app.ai.providers.adapters.shared.polling import poll_until_ready
from app.ai.providers.contracts.generation import GenerationResult
from app.core.db import SessionLocal, engine
from app.db.models import GenerationJob, Job

WAITING = 15


class _Answer:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def _png(path: Path) -> Path:
    from PIL import Image

    Image.new("RGB", (8, 8), "red").save(path)
    return path


def _queue(kind: str, count: int, *, with_reference: bool = False) -> list[str]:
    """排 `count` 条生成。`with_reference`:每条挂一张参考图 —— 运行器要先去库里查素材(开一个读事务),
    图生图 / 图生视频都走这一段,而没挂素材的请求压根不查库,测不出读事务有没有结束。"""
    from app.core.config import settings
    from tests.util import fresh_client, insert_asset

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    sources: list[dict] = []
    if with_reference:
        key = "media/test-references/ref.png"
        target = settings.data_dir / key
        target.parent.mkdir(parents=True, exist_ok=True)
        _png(target)
        reference = insert_asset(workspace, kind="image", name="ref.png", file_key=key)
        sources = [{"role": "reference_image", "asset_id": reference}]
    ids = []
    with SessionLocal() as db:
        for index in range(count):
            job = Job(workspace_id=workspace, kind="ai_generation", status="queued", payload={})
            db.add(job)
            db.flush()
            generation = GenerationJob(workspace_id=workspace, job_id=job.id, kind=kind, provider="test", model="m",
                                       request={"prompt": f"p{index}", "parameters": {}, "source_assets": sources})
            db.add(generation)
            db.flush()
            ids.append(generation.id)
        db.commit()
    return ids


def _least_pinned(samples: int = 12) -> int:
    """采几次样,取最少的那次:等待中的短会话偶尔会被采到「正借着」,一直借着的才是被钉住的。"""
    seen = []
    for _ in range(samples):
        seen.append(engine.pool.checkedout())
        time.sleep(0.1)
    return min(seen)


def _a_plain_request_gets_a_connection() -> None:
    with engine.connect() as connection:
        connection.execute(sqlalchemy.text("select 1"))


@pytest.fixture
def short_pool_timeout(monkeypatch):
    #: 生产里拿不到连接要等 30 秒才报错;测试里等 3 秒就够说明问题。
    monkeypatch.setattr(engine.pool, "_timeout", 3.0)


def test_十五个在等远端的生成不占连接(monkeypatch, short_pool_timeout) -> None:
    from app.domain.generation import runner
    from app.domain.jobs import wait_for_idle_jobs

    release = threading.Event()
    polling: set[str] = set()

    class Remote:
        def get(self, path: str) -> _Answer:
            polling.add(path)
            return _Answer({"status": "succeeded" if release.is_set() else "running"})

    def generate(request, context, output_dir):
        poll_until_ready(Remote(), f"/tasks/{request.prompt}", lambda p: "u" if p["status"] == "succeeded" else None,
                         interval=0.2)
        return GenerationResult(output_paths=[_png(output_dir / "o.png")])

    adapter = SimpleNamespace(requires_credentials=lambda: False, validate_request=lambda r: None,
                              supports_progress_callbacks=False, supports_resume=True, generate=generate,
                              reported_usage=lambda raw: runner.ReportedUsage())
    monkeypatch.setattr("app.domain.providers.selection.resolve_connection", lambda *a, **kw: None)
    monkeypatch.setattr(runner, "get_generation_adapter", lambda *a: adapter)

    ids = _queue("image", WAITING)
    baseline = engine.pool.checkedout()
    try:
        for generation_id in ids:
            runner.start_generation_thread(generation_id)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and len(polling) < WAITING:
            time.sleep(0.05)
        assert len(polling) == WAITING, "十五个生成都该进到等远端那一段"
        pinned = _least_pinned() - baseline
        assert pinned <= 1, f"{pinned} 条连接被等远端的生成攥着"
        _a_plain_request_gets_a_connection()
    finally:
        release.set()
        wait_for_idle_jobs(timeout=30)


def test_同步付费调用跑着的时候不占连接(monkeypatch, short_pool_timeout) -> None:
    """同步生图一次 POST 两三分钟:调适配器之前的读事务要结束,不然这段时间连接一直被它攥着。"""
    from app.domain.generation import runner
    from app.domain.jobs import wait_for_idle_jobs

    release = threading.Event()
    inside = threading.Semaphore(0)

    def generate(request, context, output_dir):
        inside.release()
        release.wait(20)
        return GenerationResult(output_paths=[_png(output_dir / "o.png")])

    adapter = SimpleNamespace(requires_credentials=lambda: False, validate_request=lambda r: None,
                              supports_progress_callbacks=False, supports_resume=False, generate=generate,
                              reported_usage=lambda raw: runner.ReportedUsage())
    monkeypatch.setattr("app.domain.providers.selection.resolve_connection", lambda *a, **kw: None)
    monkeypatch.setattr(runner, "get_generation_adapter", lambda *a: adapter)

    ids = _queue("image", WAITING, with_reference=True)
    baseline = engine.pool.checkedout()
    try:
        for generation_id in ids:
            runner.start_generation_thread(generation_id)
        for _ in ids:
            assert inside.acquire(timeout=20), "生成没进到适配器"
        pinned = _least_pinned() - baseline
        assert pinned <= 1, f"{pinned} 条连接被跑着的同步调用攥着"
        _a_plain_request_gets_a_connection()
    finally:
        release.set()
        wait_for_idle_jobs(timeout=30)
