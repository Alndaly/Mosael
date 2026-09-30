"""人物与音色的授权声明在生成漏斗里查,所有入口一致(ADR 0028 §4、§5)。

此前这两道只有数字人工作流节点查(executors/talking):AI 工作台、画板生成格、智能体只要勾一个「已取得授权」就放行
—— 一段用未声明的克隆音色配的音、一张真人人物资产的参考图,换个入口就能拿去做数字人。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.models import Asset, Entity, EntityReference, Voice
from app.domain.generation import create_generation_job
from app.domain.generation.operations import GenerationDomainError
from tests.util import fresh_client, insert_asset, make_voice


def _workspace() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _submit(ws: str, sources: list[dict]) -> str:
    """走漏斗;返回它拒的理由(模型不存在那一道在后面,过了授权一定会撞上它)。"""
    with SessionLocal() as db, pytest.raises(GenerationDomainError) as refused:
        create_generation_job(
            db, workspace_id=ws, session_id=None, project_id=None, created_by=None,
            provider="nobody", model="no-such-model", kind="video", prompt="", negative_prompt="",
            parameters={}, source_assets=sources, digital_human_consent=True,
        )
    return refused.value.key


def _character(ws: str, name: str, attributes: dict, *, image: str, parent: str | None = None) -> str:
    with SessionLocal() as db:
        entity = Entity(workspace_id=ws, kind="character", name=name, attributes=attributes, parent_id=parent)
        db.add(entity)
        db.flush()
        db.add(EntityReference(entity_id=entity.id, asset_id=image, role="front"))
        db.commit()
        return entity.id


def test_未声明的克隆音色配的音_哪个入口都做不了数字人() -> None:
    ws = _workspace()
    voice = make_voice(ws, "老王的嗓子")
    line = insert_asset(ws, kind="audio", name="开场.wav", media_info={"voice_id": voice})
    face = insert_asset(ws, kind="image", name="脸.png")
    sources = [{"asset_id": face, "role": "first_frame"}, {"asset_id": line, "role": "driving_audio"}]
    assert _submit(ws, sources) == "genErr_voiceConsentMissing"

    with SessionLocal() as db:
        db.get(Voice, voice).consent_kind = "fictional"
        db.commit()
    assert _submit(ws, sources) != "genErr_voiceConsentMissing", "声明过是谁的就放行(虚构也算)"


def test_真人人物的参考图当脸_要本人或已获同意的声明_变体连同母体一起看() -> None:
    ws = _workspace()
    face = insert_asset(ws, kind="image", name="小李正面.png")
    line = insert_asset(ws, kind="audio", name="开场.wav")
    person = _character(ws, "小李", {"real_person": True}, image=face)
    sources = [{"asset_id": face, "role": "first_frame"}, {"asset_id": line, "role": "driving_audio"}]
    assert _submit(ws, sources) == "genErr_entityConsentMissing"

    #: 变体的图也是这个人:母体没声明,变体自己写了也不算。
    winter = insert_asset(ws, kind="image", name="小李冬装.png")
    _character(ws, "小李 · 冬装", {"real_person": True, "consent": {"kind": "self"}}, image=winter, parent=person)
    assert _submit(ws, [{"asset_id": winter, "role": "first_frame"}, sources[1]]) == "genErr_entityConsentMissing"

    with SessionLocal() as db:
        db.get(Entity, person).attributes = {"real_person": True, "consent": {"kind": "authorized"}}
        db.commit()
    assert _submit(ws, sources) != "genErr_entityConsentMissing"
    assert _submit(ws, [{"asset_id": winter, "role": "first_frame"}, sources[1]]) != "genErr_entityConsentMissing"


def test_改口型的原片同样看_虚构人物和查不到出处的素材不拦() -> None:
    ws = _workspace()
    clip = insert_asset(ws, kind="video", name="采访.mp4")
    line = insert_asset(ws, kind="audio", name="译配.wav")
    _character(ws, "受访者", {"real_person": True}, image=clip)
    assert _submit(ws, [{"asset_id": clip, "role": "source_video"}, {"asset_id": line, "role": "driving_audio"}]) \
        == "genErr_entityConsentMissing"

    face = insert_asset(ws, kind="image", name="虚构.png")
    _character(ws, "阿星", {"real_person": False}, image=face)
    uploaded = insert_asset(ws, kind="image", name="随手传的.png")
    for image in (face, uploaded):
        assert _submit(ws, [{"asset_id": image, "role": "first_frame"}, {"asset_id": line, "role": "driving_audio"}]) \
            not in ("genErr_entityConsentMissing", "genErr_voiceConsentMissing")


def test_迁移_已有的克隆配音从配音任务补上是哪把嗓子() -> None:
    from app.db.migrations import _migrate_cloned_speech_remembers_its_voice as migrate
    from app.domain import jobs as jobs_domain

    ws = _workspace()
    voice = make_voice(ws, "旧嗓子")
    old = insert_asset(ws, kind="audio", name="旧配音.wav", media_info={"duration": 3.0})
    edge = insert_asset(ws, kind="audio", name="Edge 配的.wav")
    with SessionLocal() as db:
        for voice_id, asset_id in ((voice, old), ("zh-CN-XiaoxiaoNeural", edge)):
            job = jobs_domain.create_job(db, workspace_id=ws, kind="tts", created_by=None, payload={"voice_id": voice_id})
            job.status, job.result = "succeeded", {"asset_id": asset_id}
        db.commit()

    migrate()
    migrate()

    with SessionLocal() as db:
        assert db.get(Asset, old).media_info == {"duration": 3.0, "voice_id": voice}
        assert "voice_id" not in (db.get(Asset, edge).media_info or {}), "引擎自带的嗓子不是谁的克隆,不记"
    with engine.begin() as conn:
        stored = json.loads(conn.execute(text("SELECT media_info FROM assets WHERE id = :a"), {"a": old}).scalar_one())
    assert stored["voice_id"] == voice


def test_智能体开卡时就说_不等人批准之后才被拒() -> None:
    from app.domain.agent.confirmable.generation import _validate_generate_video
    from app.domain.agent.errors import ConfirmationError

    ws = _workspace()
    voice = make_voice(ws, "老王的嗓子")
    line = insert_asset(ws, kind="audio", name="开场.wav", media_info={"voice_id": voice})
    face = insert_asset(ws, kind="image", name="脸.png")
    payload = {"source_assets": [{"asset_id": face, "role": "first_frame"}, {"asset_id": line, "role": "driving_audio"}],
               "digital_human_consent": True, "prompt": "", "kind": "video"}
    with SessionLocal() as db, pytest.raises(ConfirmationError) as refused:
        _validate_generate_video(db, ws, payload, None)
    assert "老王的嗓子" in str(refused.value)
