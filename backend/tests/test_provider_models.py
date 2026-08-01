"""模型作为一等实体。

此前档案的粒度是不一致的:有的是一条连接(一个端点多个模型),有的其实是一个模型 ——
用户被迫拿模型名当档案名,因为能力挂在档案上、而档案只有一个 default_model。

每条断言对应一个具体的坏结果:
  能力不下沉 → 同一端点的对话模型与生图模型只能二选一;
  能力为空不回落 → 回填来的老数据变成"什么都不能做";
  runtime_limits 带 None → 下游分不清"没设过"和"显式设成空",默认行为完全不同;
  默认指向失效不兜底 → 删掉一个模型行会让整个能力报"未配置"。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import ProviderProfile
from app.domain import provider_models
from app.domain.provider_defaults import set_default
from tests.util import fresh_client


def _profile(db, vendor: str = "openai-compatible") -> ProviderProfile:
    profile = ProviderProfile(name=vendor, vendor=vendor, base_url="http://x/v1", api_key="k", default_model="")
    db.add(profile)
    db.flush()
    return profile


def test_同一条连接可以同时有对话与生图模型():
    """这正是重构要解决的那件事:此前只能建两个档案。"""
    fresh_client()
    with SessionLocal() as db:
        profile = _profile(db)
        provider_models.upsert(db, profile, "chat-model", capability_ids=["chat"])
        provider_models.upsert(db, profile, "image-model", capability_ids=["image"])
        db.commit()

        chat = [m.model_id for m in provider_models.models_for_capability(db, "chat")]
        image = [m.model_id for m in provider_models.models_for_capability(db, "image")]
    assert "chat-model" in chat and "image-model" not in chat
    assert "image-model" in image and "chat-model" not in image


def test_能力为空时回落_vendor_预设():
    """回填来的老行没写能力。不回落的话它们会变成"什么都不能做",等于数据丢了。"""
    fresh_client()
    with SessionLocal() as db:
        profile = _profile(db)
        model = provider_models.upsert(db, profile, "m1")
        db.commit()
        assert provider_models.effective_capabilities(model)  # 非空


def test_停用的模型与停用的连接都不出现():
    fresh_client()
    with SessionLocal() as db:
        profile = _profile(db)
        provider_models.upsert(db, profile, "on", capability_ids=["chat"])
        provider_models.upsert(db, profile, "off", capability_ids=["chat"], enabled=False)
        db.commit()
        assert [m.model_id for m in provider_models.models_for_capability(db, "chat")] == ["on"]

        profile.enabled = False
        db.commit()
        assert provider_models.models_for_capability(db, "chat") == []


def test_runtime_limits_只带设过的键():
    fresh_client()
    with SessionLocal() as db:
        profile = _profile(db)
        model = provider_models.upsert(db, profile, "m", context_window=128000, vision=True)
        db.commit()
        limits = provider_models.runtime_limits(model)
    assert limits == {"context_window": 128000, "vision": True}
    assert provider_models.runtime_limits(None) == {}


def test_默认指向失效时退回第一个可用模型():
    """删掉被指向的模型行不该让整个能力变成"未配置" —— 那会让所有用到它的地方一起停摆。"""
    fresh_client()
    with SessionLocal() as db:
        profile = _profile(db)
        first = provider_models.upsert(db, profile, "a", capability_ids=["chat"])
        provider_models.upsert(db, profile, "b", capability_ids=["chat"])
        set_default(db, "chat", first)
        db.commit()
        assert provider_models.resolve_default(db, "chat").model_id == "a"

        db.delete(first)
        db.commit()
        assert provider_models.resolve_default(db, "chat").model_id == "b"


def test_同一连接下模型_id_唯一():
    fresh_client()
    with SessionLocal() as db:
        profile = _profile(db)
        provider_models.upsert(db, profile, "m", capability_ids=["chat"])
        provider_models.upsert(db, profile, "m", capability_ids=["image"])
        db.commit()
        assert len(provider_models.list_models(db, profile.id)) == 1
