"""`migrate-prompt-requirement-becomes-one-field`:用户参数组里「提示词要不要写」从两个布尔收成一格 `prompt`。

喂它老形状的参数组(可以不写描述 / 必须写描述 / 两个都没有 / 已经是新写法 / 存坏了的),看它搬成新写法、
别的不碰,再跑一次什么都不动 —— 而且搬完的那份能被今天的校验收下(老键会让它再也存不回去)。
"""

from __future__ import annotations

from sqlalchemy import select, text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_prompt_requirement_becomes_one_field as migrate
from app.db.models import GenerationCapabilityProfile, ProviderProfile
from app.domain.generation.custom_profiles import validate_capabilities
from tests.util import fresh_client, user_id


def test_两个布尔收成一格_别的不碰_再跑一次什么都不动() -> None:
    fresh_client()
    with SessionLocal() as db:
        profile = ProviderProfile(owner_user_id=user_id("tester"), name="中转", vendor="openai-compatible",
                                  base_url="https://relay", auth_type="api_key", extra={}, enabled=True)
        db.add(profile)
        db.flush()
        rows = {
            "配声": {"parameter_keys": ["source_video"], "prompt_optional": True, "requires_lyrics": False},
            "音效": {"parameter_keys": ["duration_seconds"], "requires_prompt": True},
            "两个都关": {"parameter_keys": ["lyrics"], "requires_prompt": False, "prompt_optional": False},
            "新写法": {"parameter_keys": ["seed"], "prompt": "none", "prompt_optional": True},
            "不相干": {"parameter_keys": ["seed"], "max_prompt_chars": 200},
        }
        for name, capabilities in rows.items():
            db.add(GenerationCapabilityProfile(provider_profile_id=profile.id, name=name, kind="audio",
                                               capabilities=capabilities))
        db.commit()
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO generation_capability_profiles (id, provider_profile_id, name, kind, capabilities,"
            " created_at, updated_at) SELECT 'broken', provider_profile_id, '存坏了', 'audio', 'not json',"
            " created_at, updated_at FROM generation_capability_profiles LIMIT 1"
        ))

    migrate()

    with SessionLocal() as db:
        found = {row.name: row.capabilities for row in db.scalars(select(GenerationCapabilityProfile).where(
                     GenerationCapabilityProfile.id != "broken"))}
    assert found == {
        "配声": {"parameter_keys": ["source_video"], "prompt": "optional", "requires_lyrics": False},
        "音效": {"parameter_keys": ["duration_seconds"]},
        "两个都关": {"parameter_keys": ["lyrics"]},
        "新写法": {"parameter_keys": ["seed"], "prompt": "none"},
        "不相干": {"parameter_keys": ["seed"], "max_prompt_chars": 200},
    }
    # 搬完的每一份都是今天的校验收得下的
    validate_capabilities(found["配声"], "audio")
    validate_capabilities(found["音效"], "audio")
    with engine.begin() as conn:
        assert conn.execute(text("SELECT capabilities FROM generation_capability_profiles WHERE id = 'broken'")
                            ).scalar() == "not json", "存坏了的不动,也不让整个迁移倒下"

    migrate()
    with SessionLocal() as db:
        again = {row.name: row.capabilities for row in db.scalars(select(GenerationCapabilityProfile).where(
                     GenerationCapabilityProfile.id != "broken"))}
    assert again == found
