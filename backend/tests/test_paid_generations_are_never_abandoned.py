"""付过钱的远端生成,只有两种结束方式:远端给出终态,或者用户取消。

付过账的那一次(「从主题到完整视频」,Seedance 2.0,并发 3):

- 三条视频提交出去,各自在 5 分 40 秒到 7 分钟后生成成功、扣了费;
- 我们在第 300 秒把三条都判成「Generation timed out」—— 远端任务号只在适配器的局部变量里,
  判完就再也找不回来;
- 工作流等子任务那一层还有自己的 15 分钟上限,同样只是"我们等烦了";
- 后端一重启,正在生成的任务一律判"中断,请重新发起" —— 照做就是再付一次。

这里钉住修好之后的几条:回执在开始等的那一刻落库;重启后接着取而不是判失败;取回不再提交;
取消会让等待停下;每一家走异步任务的适配器都能取回;等子任务没有自己的超时。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import inspect
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.ai.providers.contracts.generation import (
    GenerationAdapterError,
    RemoteTaskWatch,
    poll_until_ready,
    watching_remote_tasks,
)
from app.core.db import SessionLocal
from app.db.models import GenerationJob, Job

APP = Path(__file__).resolve().parent.parent / "app"


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _PollClient:
    def __init__(self, answers: list[dict[str, Any]]) -> None:
        self.answers = answers
        self.paths: list[str] = []

    def get(self, path: str) -> _Response:
        self.paths.append(path)
        return _Response(self.answers.pop(0) if self.answers else {"status": "running"})


def test_开始等之前先报回执() -> None:
    """回执是远端任务号**唯一一次**离开适配器局部变量的机会。"""
    remembered: list[str] = []
    client = _PollClient([{"status": "succeeded", "url": "u"}])
    with watching_remote_tasks(RemoteTaskWatch(remember=remembered.append, is_cancelled=lambda: False)):
        poll_until_ready(client, "/tasks/cgt-1", lambda p: p.get("url"), interval=0)
    assert remembered == ["/tasks/cgt-1"]


def test_取消了就不再替它等() -> None:
    client = _PollClient([])
    with watching_remote_tasks(RemoteTaskWatch(remember=lambda _: None, is_cancelled=lambda: True)):
        with pytest.raises(GenerationAdapterError, match="已取消"):
            poll_until_ready(client, "/tasks/cgt-1", lambda p: None, interval=0)
    assert client.paths == [], "取消之后还在轮询"


def test_超时也把远端任务号说出来() -> None:
    """走到上限时它多半仍在花钱 —— 任务号是唯一能让人去供应商后台找回它的线索。"""
    with pytest.raises(GenerationAdapterError, match="cgt-9"):
        poll_until_ready(_PollClient([]), "/tasks/cgt-9", lambda p: None, interval=0, timeout=0)


def test_上限防的是永远不回话_不是等烦了() -> None:
    from app.ai.providers.contracts.generation import POLL_TIMEOUT_SECONDS

    assert POLL_TIMEOUT_SECONDS >= 3600, "Seedance 并发三条要 6–7 分钟;几百秒的上限就是在丢钱"


def test_每一家走异步任务的适配器都能取回() -> None:
    """**棘轮。** 调了 poll_until_ready 的适配器就留下了远端回执;不能取回的话,重启时那条
    付过钱的任务只能判失败。新加一家时这条会提醒它把"提交之后"那一半拆成 resume。"""
    offenders = sorted(
        str(path.relative_to(APP))
        for path in (APP / "ai/providers/adapters").rglob("*.py")
        if "poll_until_ready(" in path.read_text(encoding="utf-8")
        and "supports_resume = True" not in path.read_text(encoding="utf-8")
    )
    assert not offenders, f"这些适配器会留下远端任务,却不能接着取:{offenders}"


def test_等子任务没有自己的超时() -> None:
    from app.domain.workflows.executors.common import wait_for_job

    assert list(inspect.signature(wait_for_job).parameters) == ["job_id"], (
        "放弃等待不会让子任务停下 —— 它照样在花钱,只是做完之后没人要了"
    )


# ---------------------------------------------------------------------------
# 运行器:落回执、取回、重启
# ---------------------------------------------------------------------------
def _generation_job(status: str = "running", payload: dict[str, Any] | None = None) -> tuple[str, str]:
    from tests.util import fresh_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        job = Job(workspace_id=ws, kind="ai_generation", status=status, payload=payload or {})
        db.add(job)
        db.flush()
        generation = GenerationJob(
            workspace_id=ws, job_id=job.id, kind="image", provider="test", model="m",
            request={"prompt": "一只猫", "parameters": {}},
        )
        db.add(generation)
        db.commit()
        return job.id, generation.id


def _png(path: Path) -> Path:
    from PIL import Image

    Image.new("RGB", (8, 8), "red").save(path)
    return path


def _adapter(**overrides: Any) -> SimpleNamespace:
    base = dict(
        requires_credentials=lambda: False, validate_request=lambda r: None,
        supports_progress_callbacks=False, supports_resume=True,
    )
    return SimpleNamespace(**{**base, **overrides})


@pytest.fixture
def quiet_runner(monkeypatch):
    from app.domain.generation import runner

    monkeypatch.setattr("app.domain.providers.resolve_connection", lambda *a, **kw: None)
    monkeypatch.setattr(runner, "_record_generation_usage", lambda *a, **kw: None)
    return runner


def test_等到一半失败了_回执也已经落库(quiet_runner, monkeypatch) -> None:
    runner = quiet_runner
    job_id, generation_id = _generation_job()

    def generate(request, context, output_dir):
        def fail(_payload):
            raise GenerationAdapterError("provider says no")

        return poll_until_ready(_PollClient([{}]), "/tasks/cgt-abc", fail, interval=0)

    monkeypatch.setattr(runner, "get_generation_adapter", lambda *a: _adapter(generate=generate))
    runner._run_generation(generation_id)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert runner.remote_poll_path(job) == "/tasks/cgt-abc"


def test_取回时不再提交_成片照常入库(quiet_runner, monkeypatch, tmp_path) -> None:
    runner = quiet_runner
    job_id, _ = _generation_job(payload={"remote_task": {"poll_path": "/tasks/cgt-abc"}})
    resumed: list[str] = []

    def resume(poll_path, request, context, output_dir):
        resumed.append(poll_path)
        return SimpleNamespace(output_paths=[_png(tmp_path / "out.png")], usage={}, raw_usage={})

    def generate(*args, **kwargs):
        raise AssertionError("取回时又提交了一次 —— 那是再付一次钱")

    monkeypatch.setattr(runner, "get_generation_adapter", lambda *a: _adapter(generate=generate, resume=resume))
    assert runner.resume_generation(job_id) is True
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            if db.get(Job, job_id).status != "running":
                break
        time.sleep(0.05)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "succeeded", job.error
        assert resumed == ["/tasks/cgt-abc"]
        assert (job.result or {}).get("asset_ids"), "取回的成片要进素材库"


def test_重启时_有回执的接着取_没回执的才判失败(quiet_runner, monkeypatch) -> None:
    """此前一律判"中断,请重新发起"——远端还在生成、还在扣费,照做就是再付一次。"""
    from app.domain import jobs

    runner = quiet_runner
    submitted, _ = _generation_job(payload={"remote_task": {"poll_path": "/tasks/cgt-abc"}})
    with SessionLocal() as db:
        ws = db.get(Job, submitted).workspace_id
        never = Job(workspace_id=ws, kind="ai_generation", status="running", payload={})
        db.add(never)
        db.add(GenerationJob(workspace_id=ws, job_id=never.id, kind="image", provider="test", model="m", request={}))
        db.commit()
        never_id = never.id

    monkeypatch.setattr(runner, "get_generation_adapter", lambda *a: _adapter(generate=None))
    resumed: list[str] = []
    monkeypatch.setitem(
        jobs._RESUMERS, "ai_generation",
        jobs._Resumer(can_resume=runner.can_resume, resume=lambda job_id: resumed.append(job_id) or True),
    )
    with SessionLocal() as db:
        jobs.reconcile_orphaned_jobs(db)
    with SessionLocal() as db:
        assert db.get(Job, submitted).status == "running", "付过钱的那一条不能判失败"
        assert db.get(Job, never_id).status == "failed", "还没提交的,没有东西可取,照旧判中断"
    assert resumed == [submitted]


def test_方舟取回只查询不提交(monkeypatch, tmp_path) -> None:
    """用真实的适配器:取回走的是 GET 轮询 + 下载,一个 POST 都不能有。"""
    from app.ai.providers.adapters.bytedance.ark import video as ark
    from app.ai.providers.contracts.generation import GenerationAdapterContext, GenerationRequest

    calls: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc: Any) -> None:
            return None

        def post(self, path: str, **kwargs: Any):
            calls.append(("POST", path))
            raise AssertionError("取回时又提交了一次")

        def get(self, path: str):
            calls.append(("GET", path))
            return _Response({"status": "succeeded", "content": {"video_url": "https://tos/x.mp4"}})

    monkeypatch.setattr(ark, "RetryingClient", FakeClient)
    monkeypatch.setattr(ark, "download_to_path", lambda url, target, **kw: target.write_bytes(b"mp4"))
    result = ark.SeedanceAdapter().resume(
        f"{ark.TASKS_PATH}/cgt-1",
        GenerationRequest(kind="video", model="doubao-seedance-2-0-260128", prompt="p", parameters={}),
        GenerationAdapterContext(connection_id=None, vendor_id="bytedance", api_key="k", base_url="", options={}),
        tmp_path,
    )
    assert calls == [("GET", f"{ark.TASKS_PATH}/cgt-1")]
    assert result.output_paths[0].read_bytes() == b"mp4"
