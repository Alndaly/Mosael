"""本地取消不等于服务商不扣钱:远端任务已经交出去的,取消时先请服务商撤掉,撤不掉就把它等到终态、照实记账。

付费实测(2026-10-06,带货口播「每一拍动起来」):第 5 拍的免费配音连接超时,整条循环失败,同一拍正在生成的
Seedance 视频被连带取消 —— 账上记了一条 ¥0「not_billed」,而方舟上那个任务(cgt-20261006114833-llfwh)照样
做完、扣了约 ¥1.87。付费测试照这张账控费,就会一直以为那一段没花钱。

修好之后:撤得掉的(方舟排队中的任务)撤掉,记 0 才是真的没扣;撤不掉的接着取到终态,按回包里实际计费的 token
记;既撤不掉也接不着取的,按请求侧计量估一笔,写明远端任务没了结。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.ai.providers import register_generation_adapter_source
from app.ai.providers.adapters.bytedance.ark.video import SeedanceAdapter, extract_video_url
from app.ai.providers.adapters.shared.polling import poll_until_ready
from app.ai.providers.contracts.generation import GenerationAdapterContext, GenerationRequest, GenerationResult
from app.core.db import SessionLocal
from app.db.models import Job, ProviderUsageEvent, TaskEvent
from app.domain.billing.usage import create_pricing_rule
from tests.billing_samples import SEEDANCE_480P_WITH_AUDIO
from tests.util import add_provider, fresh_client


class _Response:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _StillRunning:
    """服务商那边一直在做:取消之前每次轮询都说 running。"""

    def get(self, _path: str) -> _Response:
        return _Response({"status": "running"})


class _Submitted(SeedanceAdapter):
    """提交出去之后一直在等;测试在等的时候取消任务。`cancel_ok` / `resumable` 决定取消之后服务商那边是什么情形。"""

    vendor_id = "fake-seedance-cancel"
    cancel_ok = False
    resumable = True
    calls: list[str] = []

    @property  # type: ignore[override]
    def supports_resume(self) -> bool:  # noqa: D401 — 按测试情形切换
        return self.resumable

    def requires_credentials(self) -> bool:
        return False

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        poll_until_ready(_StillRunning(), "/tasks/cgt-cancel", extract_video_url, interval=0.02)
        raise AssertionError("取消之后还在等")

    def cancel_remote(self, poll_path: str, request: GenerationRequest, context: GenerationAdapterContext) -> bool:
        self.calls.append(f"cancel {poll_path}")
        return self.cancel_ok

    def resume(self, poll_path: str, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        self.calls.append(f"resume {poll_path}")
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "generated.mp4"
        target.write_bytes(b"mp4")
        return GenerationResult(output_paths=[target], usage={"videos": 1, "video_seconds": 4.0, "resolution": "480p"},
                                raw_usage=SEEDANCE_480P_WITH_AUDIO["raw"])


_ADAPTER = _Submitted()
register_generation_adapter_source(lambda vendor, kind: _ADAPTER if (vendor, kind) == ("fake-seedance-cancel", "video") else None)


def _run_and_cancel(*, cancel_ok: bool, resumable: bool, rule: tuple[str, int, str]) -> tuple[ProviderUsageEvent, Job, list[str]]:
    _ADAPTER.cancel_ok, _ADAPTER.resumable, _ADAPTER.calls = cancel_ok, resumable, []
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    model = "doubao-seedance-2-0-260128"
    with SessionLocal() as db:
        profile = add_provider(db, name="Ark", vendor="fake-seedance-cancel", base_url="", api_key="k", model=model,
                               capability_ids=["video"], make_default=False)
        unit, micros, currency = rule
        create_pricing_rule(db, provider="fake-seedance-cancel", capability="video", model=model, billing_unit=unit,
                            unit_amount_micros=micros, currency=currency)
        db.commit()
        profile_id = profile.id
    response = client.post("/api/generation/jobs", json={
        "workspace_id": workspace, "provider_profile_id": profile_id, "provider": "fake-seedance-cancel", "model": model,
        "kind": "video", "prompt": "手串", "parameters": {"duration_seconds": 4, "resolution": "480p"},
    })
    assert response.status_code == 200, response.text
    job_id = response.json()["job"]["id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:  # 等远端任务交出去(回执落库)再取消
        with SessionLocal() as db:
            if (db.get(Job, job_id).payload or {}).get("remote_task"):
                break
        time.sleep(0.02)
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            usage = db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job_id)).first()
            if usage is not None:
                job = db.get(Job, job_id)
                events = [event.type for event in db.scalars(select(TaskEvent).where(TaskEvent.job_id == job_id))]
                db.expunge_all()
                return usage, job, events
        time.sleep(0.05)
    raise AssertionError("取消之后一直没记账")


def test_撤得掉的远端任务撤掉_记零才是真的没扣() -> None:
    usage, job, events = _run_and_cancel(cancel_ok=True, resumable=True, rule=("million_output_token", 46_000_000, "CNY"))
    assert job.status == "cancelled", (job.status, events)
    assert _ADAPTER.calls == ["cancel /tasks/cgt-cancel"], "撤掉了就不用再等它"
    assert (usage.status, usage.cost_micros, usage.cost_confidence) == ("failed", 0, "not_billed")
    assert "job.remote_cancelled" in events


def test_撤不掉的接着等到终态_按回包里实际计费的量记账() -> None:
    usage, job, _events = _run_and_cancel(cancel_ok=False, resumable=True, rule=("million_output_token", 46_000_000, "CNY"))
    assert job.status == "cancelled", "取消照旧是取消:成片不进任何地方"
    assert _ADAPTER.calls == ["cancel /tasks/cgt-cancel", "resume /tasks/cgt-cancel"]
    #: 和「下载失败也按回包记」同一份样本:110902 个 token × ¥46 / 百万。
    assert (usage.cost_micros, usage.currency, usage.cost_confidence) == (5_101_492, "CNY", "estimated")
    assert usage.units["output_tokens"] == 110_902
    assert usage.raw_usage.get("cancelled_locally") is True


def test_既撤不掉也接不着取_按请求侧估一笔_写明远端任务没了结() -> None:
    usage, _job, _events = _run_and_cancel(cancel_ok=False, resumable=False, rule=("video_second", 500_000, "CNY"))
    assert usage.cost_confidence == "estimated" and usage.cost_micros == 2_000_000, "4 秒 × ¥0.5,不再记成没扣费"
    assert usage.raw_usage["unsettled_remote_task"] == "/tasks/cgt-cancel"


# ---------- 方舟的撤销 ----------


class _ArkClient:
    def __init__(self, status: str, delete_status: int = 200) -> None:
        self.status = status
        self.delete_status = delete_status
        self.calls: list[tuple[str, str]] = []

    def __call__(self, **_kwargs: Any) -> _ArkClient:
        return self

    def __enter__(self) -> _ArkClient:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def get(self, path: str) -> _Response:
        self.calls.append(("GET", path))
        return _Response({"id": "cgt-1", "status": self.status})

    def delete(self, path: str) -> _Response:
        self.calls.append(("DELETE", path))
        return _Response({}, self.delete_status)


def _ark_cancel(monkeypatch, client: _ArkClient) -> bool:
    from app.ai.providers.adapters.bytedance.ark import video as ark

    monkeypatch.setattr(ark, "RetryingClient", client)
    return ark.SeedanceAdapter().cancel_remote(
        f"{ark.TASKS_PATH}/cgt-1",
        GenerationRequest(kind="video", model="doubao-seedance-2-0-260128", prompt="p", parameters={}),
        GenerationAdapterContext(connection_id=None, vendor_id="bytedance", api_key="k", base_url="", options={}),
    )


def test_方舟_排队中的任务发撤销(monkeypatch) -> None:
    client = _ArkClient("queued")
    assert _ark_cancel(monkeypatch, client) is True
    assert [method for method, _ in client.calls] == ["GET", "DELETE"]


def test_方舟_正在做或做完了的不发撤销_那个调用会删掉要读用量的任务记录(monkeypatch) -> None:
    for status in ("running", "succeeded"):
        client = _ArkClient(status)
        assert _ark_cancel(monkeypatch, client) is False
        assert [method for method, _ in client.calls] == ["GET"], status


def test_方舟_查完到撤之间开始做了_撤销被拒就算撤不掉(monkeypatch) -> None:
    assert _ark_cancel(monkeypatch, _ArkClient("queued", delete_status=400)) is False
