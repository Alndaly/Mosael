"""棘轮:**多能力供应商下,认不出、也没标过能力的模型不出现在任何生成入口里。**

此前模型行没写能力时兜底的是整个供应商预设:OpenAI 兼容连接的预设是「对话 + 图像」,于是 147ai / Ollama
上的 `claude-opus-4-6`、`gemma4` 都成了生图模型;Evolink 的预设是「图像 + 视频 + 音频」,于是上面一个认不出
的视频模型同时出现在三个生成下拉里。

现在生成能力(和语音合成)要**正面证据**:行上标了、内置目录认得、连接声明过、用户写过这种生成的参数契约,
或者供应商只有这一种能力。规则只有一处(provider_models.evidenced_capabilities),这里逐家预设钉住它 ——
新加一家多能力供应商,它上面的陌生模型同样得进不了生成下拉。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import pytest

from app.core.db import SessionLocal
from app.db.models import GenerationCapabilityDeclaration, ProviderProfile
from app.domain import provider_models
from app.domain.generation.catalog import GENERATION_KINDS
from app.domain.generation.resolution import (
    GenerationResolutionError,
    generation_options,
    resolve_generation_model,
)
from app.domain.provider_presets import provider_definition, _VENDOR_PRESETS
from tests.util import fresh_client, user_id

UNKNOWN = "definitely-not-in-any-catalog-7f3a"

#: 要证据的能力:三种生成,加语音合成(见 PRESET_FALLBACK_CAPABILITIES 的说明)。
NEEDS_EVIDENCE = (*GENERATION_KINDS, "tts")

MULTI = sorted(v for v in _VENDOR_PRESETS if len(provider_definition(v).capability_ids) > 1)
SINGLE = sorted(v for v in _VENDOR_PRESETS if len(provider_definition(v).capability_ids) == 1)


def _row(db, vendor: str, model_id: str = UNKNOWN, **fields):
    profile = ProviderProfile(
        owner_user_id=user_id(), name=f"{vendor} 连接", vendor=vendor, base_url="https://example.invalid",
        auth_type="api_key", extra={}, enabled=True,
    )
    db.add(profile)
    db.flush()
    return provider_models.upsert(db, profile, model_id, source="manual", **fields)


def test_扫描面站得住() -> None:
    assert "openai-compatible" in MULTI and "evolink" in MULTI and "alibaba" in MULTI
    assert "volcano" in SINGLE


@pytest.mark.parametrize("vendor", MULTI)
def test_多能力供应商下认不出的模型不进任何生成入口(vendor: str) -> None:
    fresh_client()
    me = user_id()
    with SessionLocal() as db:
        row = _row(db, vendor)
        db.commit()
        preset = provider_definition(vendor).capability_ids
        effective = provider_models.effective_capabilities(row)
        assert not set(effective) & set(NEEDS_EVIDENCE), f"{vendor} 上的陌生模型被认成了 {effective}"
        # 预设里有对话的,陌生模型只当对话模型;没有对话的(Evolink、方舟……)什么都不是
        assert effective == [c for c in preset if c in provider_models.PRESET_FALLBACK_CAPABILITIES]
        for kind in GENERATION_KINDS:
            assert UNKNOWN not in [m.model_id for m in provider_models.models_for_capability(db, kind, me)]
            assert UNKNOWN not in [option["model"] for option in generation_options(db, kind, user_id=me)]


@pytest.mark.parametrize("vendor", SINGLE)
def test_单能力供应商的连接本身就是证据(vendor: str) -> None:
    fresh_client()
    with SessionLocal() as db:
        row = _row(db, vendor)
        db.commit()
        assert provider_models.effective_capabilities(row) == list(provider_definition(vendor).capability_ids)


def test_正面证据各自都算数() -> None:
    fresh_client()
    me = user_id()
    with SessionLocal() as db:
        catalog = _row(db, "openai-compatible", "gpt-image-2")
        named = _row(db, "openai", "gpt-4o-mini-tts")
        tagged = _row(db, "openai-compatible", "my-flux", capability_ids=["image"])
        declared = _row(db, "evolink", "brand-new-video-model")
        declared.declared_capabilities = {"video": {"parameter_keys": []}}
        contract = _row(db, "openai-compatible", "relay-image-model")
        db.flush()
        db.add(GenerationCapabilityDeclaration(provider_model_id=contract.id, kind="image", catalog_ref="profile:openai-image"))
        db.commit()

        assert provider_models.effective_capabilities(catalog) == ["image"]
        assert provider_models.effective_capabilities(named) == ["tts"]
        assert provider_models.effective_capabilities(tagged) == ["image"]
        assert provider_models.effective_capabilities(declared) == ["video"]
        assert provider_models.effective_capabilities(contract) == ["image"]
        images = {option["model"] for option in generation_options(db, "image", user_id=me)}
        assert {"gpt-image-2", "my-flux", "relay-image-model"} <= images


def test_设置页目录里还没加的模型按同一条规则显示能力() -> None:
    """目录项(还没加进来的)显示的能力和加进来之后的必须是同一个答案 —— 用户是照着列表做的决定。"""
    client = fresh_client()
    profile_id = client.post(
        "/api/settings/providers",
        json={"vendor": "evolink", "name": "Evolink", "api_key": "sk-test", "base_url": "http://127.0.0.1:1"},
    ).json()["id"]
    rows = {row["id"]: row for row in client.get(f"/api/settings/providers/{profile_id}/models").json()}
    assert rows["suno-v5-beta"]["effective_capability_ids"] == ["audio"]


def test_默认模型被摘掉这项能力就不再是默认() -> None:
    fresh_client()
    me = user_id()
    with SessionLocal() as db:
        from app.domain.provider_defaults import set_default

        row = _row(db, "openai-compatible", "my-flux", capability_ids=["chat", "image"])
        set_default(db, "image", row, owner_user_id=me)
        db.commit()
        assert provider_models.resolve_default(db, "image", me) is not None
        row.capability_ids = ["chat"]
        db.commit()
        assert provider_models.resolve_default(db, "image", me) is None


def test_生成选项标出默认模型_没设就一项都不标() -> None:
    fresh_client()
    me = user_id()
    with SessionLocal() as db:
        from app.domain.provider_defaults import set_default

        first = _row(db, "openai-compatible", "a-image", capability_ids=["image"])
        second = _row(db, "openai-compatible", "b-image", capability_ids=["image"])
        db.commit()
        assert [o["is_default"] for o in generation_options(db, "image", user_id=me)] == [False, False]
        set_default(db, "image", second, owner_user_id=me)
        db.commit()
        marked = {o["model"]: o["is_default"] for o in generation_options(db, "image", user_id=me)}
        assert marked == {"a-image": False, "b-image": True}
        assert first is not None


def test_存着的选择指着一个不再能出图的模型_漏斗说清是能力标签的事() -> None:
    fresh_client()
    me = user_id()
    with SessionLocal() as db:
        row = _row(db, "openai-compatible", "claude-opus-4-6")
        db.commit()
        with pytest.raises(GenerationResolutionError) as caught:
            resolve_generation_model(
                db, user_id=me, provider="openai-compatible", model="claude-opus-4-6", kind="image",
                provider_profile_id=row.provider_profile_id,
            )
        assert caught.value.key == "genErr_modelLacksKind_image"
        with pytest.raises(GenerationResolutionError) as missing:
            resolve_generation_model(
                db, user_id=me, provider="openai-compatible", model="no-such-model", kind="image",
                provider_profile_id=row.provider_profile_id,
            )
        assert missing.value.key == "genErr_modelNotEnabled"
