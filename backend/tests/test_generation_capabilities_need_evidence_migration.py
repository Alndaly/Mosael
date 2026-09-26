"""`migrate-generation-capabilities-need-evidence`:没写能力的模型行按新规则落成显式标签。

喂它一份旧库的样子 —— 147ai(OpenAI 兼容)上的对话模型、目录认得的生图模型、被设成默认生图模型的中转模型、
真出过图的中转模型、写过旧版「参数按什么来」的模型、用户自己标过能力的模型;Evolink 上一个认不出的模型和
一个目录里的 Suno;火山语音(单能力)上的一个模型;一个画板格存着「claude-opus-4-6 出图」—— 看它把能力写对、
用户写过的一样不碰、存着的选择不改,再跑一次什么都不动。
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.migrations import _migrate_generation_capabilities_need_evidence as migrate
from app.db.models import (
    Asset,
    Board,
    GenerationCapabilityDeclaration,
    GenerationJob,
    Job,
    ProviderDefault,
    ProviderModel,
    ProviderProfile,
)
from app.domain import provider_models
from app.domain.generation.resolution import GenerationResolutionError, generation_options, resolve_generation_model
from tests.util import fresh_client, user_id

import pytest


def _legacy(client) -> dict[str, str]:
    me = user_id("tester")
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    board_id = client.post("/api/boards", json={"workspace_id": workspace, "name": "B"}).json()["id"]
    with SessionLocal() as db:
        relay = ProviderProfile(owner_user_id=me, name="147ai", vendor="openai-compatible", base_url="https://relay",
                                auth_type="api_key", extra={}, enabled=True)
        evolink = ProviderProfile(owner_user_id=me, name="Evolink", vendor="evolink", base_url="",
                                  auth_type="api_key", extra={}, enabled=True)
        voice = ProviderProfile(owner_user_id=me, name="火山语音", vendor="volcano", base_url="",
                                auth_type="api_key", extra={}, enabled=True)
        db.add_all([relay, evolink, voice])
        db.flush()

        def row(profile: ProviderProfile, model_id: str, capabilities: list[str] | None = None, **fields) -> ProviderModel:
            model = ProviderModel(provider_profile_id=profile.id, model_id=model_id,
                                  capability_ids=capabilities or [], **fields)
            db.add(model)
            return model

        rows = {
            "opus": row(relay, "claude-opus-4-6"),
            "gpt_image": row(relay, "gpt-image-2"),
            "default_flux": row(relay, "my-flux"),
            "produced": row(relay, "nano-banana-relay"),
            "legacy_ref": row(relay, "flux-relay-client", generation_capability_ref="model:openai-compatible/gpt-image-2"),
            "declared": row(relay, "relay-declared"),
            "tagged": row(relay, "tagged-video", ["video"]),
            "mystery": row(evolink, "seedance-9.9-mini-image-to-video"),
            "suno": row(evolink, "suno-v5-beta"),
            "speech": row(voice, "seed-tts-2.0"),
        }
        db.flush()
        db.add(ProviderDefault(capability="image", owner_user_id=me, provider_model_id=rows["default_flux"].id))
        db.add(GenerationCapabilityDeclaration(provider_model_id=rows["declared"].id, kind="image",
                                               catalog_ref="profile:openai-image"))
        asset = Asset(workspace_id=workspace, kind="image", name="出过的图")
        db.add(asset)
        db.flush()
        db.add(GenerationJob(workspace_id=workspace, provider_profile_id=relay.id, provider="openai-compatible",
                             model="nano-banana-relay", kind="image", request={"prompt": "猫"},
                             result_asset_id=asset.id))
        # 失败了的那一趟不算数:opus 出图从来没成过
        failed = Job(workspace_id=workspace, kind="ai_generation", status="failed", created_by=me, payload={})
        db.add(failed)
        db.flush()
        db.add(GenerationJob(workspace_id=workspace, job_id=failed.id, provider_profile_id=relay.id,
                             provider="openai-compatible", model="claude-opus-4-6", kind="image",
                             request={"prompt": "猫"}))
        board = db.get(Board, board_id)
        board.canvas = {"items": [
            {"id": "i1", "kind": "image", "x": 0, "y": 0,
             "form": {"prompt": "猫", "provider": "openai-compatible", "provider_profile_id": relay.id,
                      "model": "claude-opus-4-6"}},
        ]}
        db.commit()
        ids = {name: model.id for name, model in rows.items()}
        ids.update(relay=relay.id, board=board_id, board_revision=str(board.revision))
    return ids


def test_没写能力的行落成新规则的答案_用户说过的留着_存着的选择不动_再跑一次什么都不动() -> None:
    client = fresh_client()
    ids = _legacy(client)
    me = user_id("tester")

    migrate()

    with SessionLocal() as db:
        caps = {name: db.get(ProviderModel, ids[name]).capability_ids for name in (
            "opus", "gpt_image", "default_flux", "produced", "legacy_ref", "declared", "tagged",
            "mystery", "suno", "speech",
        )}
        assert caps == {
            # 聚合连接上认不出的模型只当对话模型
            "opus": ["chat"],
            # 目录认得
            "gpt_image": ["image"],
            # 用户把它设成了默认生图模型 / 它真出过图 / 写过旧版参数指向 —— 生图能力留着
            "default_flux": ["chat", "image"],
            "produced": ["chat", "image"],
            "legacy_ref": ["chat", "image"],
            # 用户给它写过图像的参数契约
            "declared": ["image"],
            # 用户自己标过的不碰,哪怕新规则认不出来
            "tagged": ["video"],
            # Evolink 上认不出的:什么都不是(留空 = 按规则认,规则认不出)
            "mystery": [],
            "suno": ["audio"],
            # 单能力供应商:连接本身就是证据
            "speech": ["tts"],
        }

        images = {option["model"] for option in generation_options(db, "image", user_id=me)}
        assert "claude-opus-4-6" not in images
        assert {"gpt-image-2", "my-flux", "nano-banana-relay", "flux-relay-client", "relay-declared"} <= images
        for kind in ("image", "video", "audio"):
            assert "seedance-9.9-mini-image-to-video" not in {
                option["model"] for option in generation_options(db, kind, user_id=me)
            }
        # 默认模型照旧能用
        assert provider_models.resolve_default(db, "image", me).id == ids["default_flux"]

        # 存着的选择不改;指着一个不再能出图的模型时,漏斗说清是能力标签的事,不崩
        board = db.get(Board, ids["board"])
        assert board.canvas["items"][0]["form"]["model"] == "claude-opus-4-6"
        assert str(board.revision) == ids["board_revision"]
        with pytest.raises(GenerationResolutionError) as caught:
            resolve_generation_model(db, user_id=me, provider="openai-compatible", model="claude-opus-4-6",
                                     kind="image", provider_profile_id=ids["relay"])
        assert caught.value.key == "genErr_modelLacksKind_image"
        before = {row.id: list(row.capability_ids) for row in db.scalars(select(ProviderModel))}

    migrate()
    with SessionLocal() as db:
        assert {row.id: list(row.capability_ids) for row in db.scalars(select(ProviderModel))} == before


def test_没有模型行的库什么都不动() -> None:
    fresh_client()
    migrate()
    with SessionLocal() as db:
        assert db.scalars(select(ProviderModel)).all() == []
