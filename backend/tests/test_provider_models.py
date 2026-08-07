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
from app.db.models import User
from app.db.models import ProviderProfile
from app.domain import provider_models
from app.domain.provider_defaults import set_default
from tests.util import add_provider, fresh_client


def _profile(db, vendor: str = "openai-compatible") -> ProviderProfile:
    profile = add_provider(db, name=vendor, vendor=vendor, base_url="http://x/v1", api_key="k")
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


def test_默认指向的模型被删掉之后不会静默换一个():
    """**这条曾经断言相反的行为**:退回"该能力下第一个可用模型"。

    换掉是因为那个兜底的失败方式跑出来过 —— 界面显示 DeepSeek、回答却是「我是 Kimi」,
    因为那个"第一个"碰巧是一条订阅计划连接。原来的担心(删一行模型让整个能力停摆)是真的,
    但代价换错了方向:**停摆看得见,静默换一个看不见**。现在删掉之后默认为空,调用方报
    「请先选一个模型」。
    """
    fresh_client()
    with SessionLocal() as db:
        # 默认永远挂在**某个人**身上 —— 部署那一档也删掉了(见 test_no_deployment_default_model)。
        me = db.query(User).order_by(User.created_at).first().id
        profile = _profile(db)
        first = provider_models.upsert(db, profile, "a", capability_ids=["chat"])
        provider_models.upsert(db, profile, "b", capability_ids=["chat"])
        set_default(db, "chat", first, owner_user_id=me)
        db.commit()
        assert provider_models.resolve_default(db, "chat", me).model_id == "a"

        db.delete(first)
        db.commit()
        assert provider_models.resolve_default(db, "chat", me) is None, "静默换成了另一个模型"


def test_同一连接下模型_id_唯一():
    fresh_client()
    with SessionLocal() as db:
        profile = _profile(db)
        provider_models.upsert(db, profile, "m", capability_ids=["chat"])
        provider_models.upsert(db, profile, "m", capability_ids=["image"])
        db.commit()
        assert len(provider_models.list_models(db, profile.id)) == 1


def test_新建档案立刻有模型行():
    """回填只覆盖历史数据。运行时新建的档案同样需要模型行,否则新系统对它们一无所知 ——
    能力选择器空着、默认解析退回不到任何候选。这个缺口是被测试抓到的:新建的 TTS 档案
    配了默认却报"没有配置可用于语音生成的真实供应商"。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    created = client.post(
        "/api/settings/providers",
        json={
            "name": "本地",
            "vendor": "openai-compatible",
            "config": {"base_url": "http://127.0.0.1:1/v1", "api_key": "k", "default_model": "m1"},
        },
    )
    assert created.status_code == 200, created.text
    with SessionLocal() as db:
        rows = provider_models.list_models(db, created.json()["id"])
    assert [row.model_id for row in rows] == ["m1"]


def test_改默认模型会补出新的模型行():
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    profile_id = client.post(
        "/api/settings/providers",
        json={
            "name": "本地",
            "vendor": "openai-compatible",
            "config": {"base_url": "http://127.0.0.1:1/v1", "api_key": "k", "default_model": "m1"},
        },
    ).json()["id"]
    client.patch(f"/api/settings/providers/{profile_id}", json={"config": {"default_model": "m2"}})
    with SessionLocal() as db:
        ids = sorted(row.model_id for row in provider_models.list_models(db, profile_id))
    # 换默认不删旧行 —— 旧模型可能仍在别处被引用(会话里选着它、工作流节点填着它)。
    assert ids == ["m1", "m2"]


def test_模型_id_带斜杠时也能改和删():
    """kimi/kimi-k2.7-code、MiniMax/MiniMax-M2.5、ZHIPU/GLM-5 —— 带斜杠是常态。
    普通路径参数不跨 `/`,路由匹配不上,表现是删除/修改一律 404,且只有带斜杠的模型才复现。"""
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    profile_id = client.post(
        "/api/settings/providers",
        json={
            "name": "端点",
            "vendor": "openai-compatible",
            "config": {"base_url": "http://127.0.0.1:1/v1", "api_key": "k", "default_model": "m"},
        },
    ).json()["id"]

    slashed = "kimi/kimi-k2.7-code"
    assert client.post(f"/api/settings/providers/{profile_id}/models", json={"model_id": slashed}).status_code == 200

    patched = client.patch(f"/api/settings/providers/{profile_id}/models/{slashed}", json={"enabled": False})
    assert patched.status_code == 200, patched.text
    assert patched.json()["enabled"] is False

    assert client.delete(f"/api/settings/providers/{profile_id}/models/{slashed}").status_code == 204
    remaining = [row["id"] for row in client.get(f"/api/settings/providers/{profile_id}/models").json() if row["configured"]]
    assert slashed not in remaining


def test_comfyui_的目录是它的工作流而不是模型() -> None:
    """ComfyUI 是工作流引擎,没有模型目录。走同一个接缝(_catalog_entries)而不是在前端
    分叉:这样「加入 / 启停 / 设能力 / 删除」整套交互对工作流原样成立,只有文案不同。"""
    from app.api.routes import settings as settings_routes
    from app.domain.provider_credentials import ResolvedProvider

    # _catalog_entries 拿的是解析过的连接(连接 + 这个人的钥匙)。
    profile = ResolvedProvider(
        id="p", name="C", vendor="comfyui", base_url="http://127.0.0.1:9", auth_type="api_key", enabled=True
    )

    class _Client:
        def __init__(self, base): pass
        def list_workflows(self): return [{"path": "a.json", "name": "a"}, {"path": "b.json", "name": "b"}]

    import app.ai.providers.comfyui_client as cc

    original = cc.ComfyUIClient
    cc.ComfyUIClient = _Client  # type: ignore[assignment]
    try:
        assert set(settings_routes._catalog_entries(profile)) == {"a.json", "b.json"}
    finally:
        cc.ComfyUIClient = original


def test_comfyui_连不上时目录为空而不是报错() -> None:
    """连不上是常态(忘了启动)。设置页不该因此 500 —— 空目录和"端点没有模型"是同一种表现。"""
    from app.api.routes import settings as settings_routes
    from app.domain.provider_credentials import ResolvedProvider

    profile = ResolvedProvider(
        id="p", name="C", vendor="comfyui", base_url="http://127.0.0.1:1", auth_type="api_key", enabled=True
    )
    assert settings_routes._catalog_entries(profile) == {}
