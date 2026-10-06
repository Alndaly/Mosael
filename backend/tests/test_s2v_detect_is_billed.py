"""百炼说话照片之前的人像预检(wan2.2-s2v-detect)按张计费,账上要有它。

付费实测(2026-10-06):数字人出镜、稿子口播一共调了 4 次预检。文档页写的是「wan2.2-s2v-detect 0.004元/张」「无论检测
是否通过,只要请求成功就计费」(https://help.aliyun.com/zh/model-studio/wan-s2v-detect-api),而应用的账上一笔都没有:
预检在适配器里同步调完就算了,运行器只记生成那一条;预检没过时生成那一条还是「失败、没扣费」。

修好之后:适配器调完预检就报一笔「顺带的调用」(contracts.generation.report_side_call),运行器当场单独记账,和生成成不成
无关;价目表里有它的官方价,预填跟着 wan2.2-s2v 一起补上(它不在连接的模型目录里),老库由迁移补。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.ai.providers import register_generation_adapter_source
from app.ai.providers.adapters.alibaba.dashscope import digital_human
from app.ai.providers.contracts.generation import (
    GenerationAdapter,
    GenerationAdapterContext,
    GenerationAdapterError,
    GenerationRequest,
    GenerationResult,
    RemoteTaskWatch,
    report_side_call,
    watching_remote_tasks,
)
from app.core.db import SessionLocal
from app.db.models import Job, ProviderPricingRule, ProviderUsageEvent
from app.domain.billing import price_reference
from app.domain.billing.usage import create_pricing_rule
from tests.util import add_provider, fresh_client


class _Response:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _DetectClient:
    def __init__(self, check_pass: bool) -> None:
        self.check_pass = check_pass

    def build_request(self, method: str, path: str, **kwargs: Any):
        return type("Req", (), {"headers": {}})()

    def send(self, request) -> _Response:
        return _Response({"output": {"check_pass": self.check_pass}, "usage": {"image_count": 1}, "request_id": "r"})


def _capture() -> tuple[RemoteTaskWatch, list[tuple[str, dict, dict]]]:
    calls: list[tuple[str, dict, dict]] = []
    watch = RemoteTaskWatch(remember=lambda _: None, is_cancelled=lambda: False, settled=lambda _: None,
                            side_call=lambda model, units, raw: calls.append((model, units, raw)))
    return watch, calls


@pytest.mark.parametrize("check_pass", [True, False], ids=["通过", "不通过"])
def test_预检请求成功就报一笔_通过不通过都一样(check_pass: bool) -> None:
    watch, calls = _capture()
    with watching_remote_tasks(watch):
        if check_pass:
            digital_human.check_portrait(_DetectClient(True), "oss://face.png")
        else:
            with pytest.raises(GenerationAdapterError):
                digital_human.check_portrait(_DetectClient(False), "oss://face.png")
    assert [(model, units) for model, units, _ in calls] == [("wan2.2-s2v-detect", {"requests": 1, "images": 1})]
    assert calls[0][2]["usage"] == {"image_count": 1}, "回包照存"


def test_价目表里有预检的官方价_按张() -> None:
    (entry,) = price_reference.lookup("alibaba", "wan2.2-s2v-detect", region="cn")
    assert (entry.capability, entry.billing_unit, entry.amount, entry.currency) == ("video", "image", "0.004", "CNY")
    assert entry.source == "https://help.aliyun.com/zh/model-studio/wan-s2v-detect-api"


# ---------- 运行器:顺带的调用单独记一笔 ----------


class _Talking(GenerationAdapter):
    """先调预检(报一笔),再按 `detect_pass` 决定是生成成功还是当场拒掉。"""

    vendor_id = "fake-s2v"
    media_kind = "video"
    detect_pass = True

    def requires_credentials(self) -> bool:
        return False

    def generate(self, request: GenerationRequest, context: GenerationAdapterContext, output_dir: Path) -> GenerationResult:
        report_side_call("wan2.2-s2v-detect", {"requests": 1, "images": 1}, {"output": {"check_pass": self.detect_pass}})
        if not self.detect_pass:
            raise GenerationAdapterError("providerErr_noUsableFace", vendor="DashScope", detail="no face")
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "generated.mp4"
        target.write_bytes(b"mp4")
        return GenerationResult(output_paths=[target], usage={"videos": 1, "video_seconds": 2.0, "resolution": "480P"},
                                raw_usage={"usage": {"duration": 2.0}})


_ADAPTER = _Talking()
register_generation_adapter_source(lambda vendor, kind: _ADAPTER if (vendor, kind) == ("fake-s2v", "video") else None)


def _run(detect_pass: bool) -> list[ProviderUsageEvent]:
    _ADAPTER.detect_pass = detect_pass
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        profile = add_provider(db, name="百炼", vendor="fake-s2v", base_url="", api_key="k", model="wan2.2-s2v",
                               capability_ids=["video"], make_default=False)
        create_pricing_rule(db, provider="fake-s2v", capability="video", model="wan2.2-s2v-detect", billing_unit="image",
                            unit_amount_micros=4000, currency="CNY")
        create_pricing_rule(db, provider="fake-s2v", capability="video", model="wan2.2-s2v", billing_unit="video_second",
                            unit_amount_micros=500_000, currency="CNY")
        db.commit()
        profile_id = profile.id
    response = client.post("/api/generation/jobs", json={
        "workspace_id": workspace, "provider_profile_id": profile_id, "provider": "fake-s2v", "model": "wan2.2-s2v",
        "kind": "video", "prompt": "主播说开场", "parameters": {},
    })
    assert response.status_code == 200, response.text
    job_id = response.json()["job"]["id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            if db.get(Job, job_id).status in ("succeeded", "failed"):
                events = db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.job_id == job_id)
                                    .order_by(ProviderUsageEvent.created_at)).all()
                if len(events) == 2:
                    db.expunge_all()
                    return events
        time.sleep(0.05)
    raise AssertionError("两笔账没记齐")


def test_预检单独记一笔_按官方价() -> None:
    events = {event.model: event for event in _run(detect_pass=True)}
    detect = events["wan2.2-s2v-detect"]
    assert (detect.status, detect.cost_micros, detect.currency, detect.cost_confidence) == ("succeeded", 4000, "CNY", "estimated")
    assert detect.operation == "generation_side_call" and detect.units["images"] == 1
    assert events["wan2.2-s2v"].cost_micros == 1_000_000, "生成那一条照旧按秒记"


def test_预检没过_生成没扣费_预检那一笔照记() -> None:
    events = {event.model: event for event in _run(detect_pass=False)}
    assert (events["wan2.2-s2v"].status, events["wan2.2-s2v"].cost_micros) == ("failed", 0)
    assert (events["wan2.2-s2v-detect"].cost_micros, events["wan2.2-s2v-detect"].currency) == (4000, "CNY")


# ---------- 预填与老库 ----------


def _alibaba(model: str) -> str:
    fresh_client()
    with SessionLocal() as db:
        profile = add_provider(db, name="百炼", vendor="alibaba", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                               api_key="k", model=model, capability_ids=["video"], make_default=False)
        db.commit()
        return profile.id


def _detect_rules(profile_id: str) -> list[tuple[str, str, int, str]]:
    with SessionLocal() as db:
        return [(rule.capability, rule.billing_unit, rule.unit_amount_micros, rule.currency) for rule in db.scalars(
            select(ProviderPricingRule).where(ProviderPricingRule.provider_profile_id == profile_id,
                                              ProviderPricingRule.model == "wan2.2-s2v-detect"))]


def test_预填跟着说话照片一起补上预检的价_它不在模型目录里() -> None:
    from app.db.models import ProviderProfile
    from app.domain.billing.pricing_prefill import prefill_profile_pricing

    for model, expected in (("wan2.2-s2v", [("video", "image", 4000, "CNY")]), ("qwen-plus", [])):
        profile_id = _alibaba(model)
        with SessionLocal() as db:
            profile = db.get(ProviderProfile, profile_id)
            prefill_profile_pricing(db, profile, base_url=profile.base_url, catalog=[])
            db.commit()
        assert _detect_rules(profile_id) == expected, model


def test_老库由迁移补上预检的价_只给配了说话照片的连接_跑两次也只有一条() -> None:
    from app.db.migrations import _migrate_existing_libraries_get_the_s2v_detect_price

    with_s2v = _alibaba("wan2.2-s2v")
    with SessionLocal() as db:
        from app.db.models import ProviderProfile
        from tests.util import add_provider as _add

        other = _add(db, name="另一条", vendor="alibaba", base_url="", api_key="k", model="qwen-plus",
                     capability_ids=["chat"], make_default=False)
        db.commit()
        other_id = other.id
        assert db.get(ProviderProfile, with_s2v) is not None
    _migrate_existing_libraries_get_the_s2v_detect_price()
    _migrate_existing_libraries_get_the_s2v_detect_price()
    assert _detect_rules(with_s2v) == [("video", "image", 4000, "CNY")]
    assert _detect_rules(other_id) == []
