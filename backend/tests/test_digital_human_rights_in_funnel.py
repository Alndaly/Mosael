"""人物与音色的授权声明在生成漏斗里查,所有入口一致(ADR 0028 §4、§5)。

此前这两道只有数字人工作流节点查(executors/talking):AI 工作台、画板生成格、智能体只要勾一个「已取得授权」就放行
—— 一段用未声明的克隆音色配的音、一张真人人物资产的参考图,换个入口就能拿去做数字人。
"""

from __future__ import annotations

from app.domain.generation.origins import STUDIO_ORIGIN

import pytest

from app.core.db import SessionLocal
from app.db.models import Entity, EntityReference, Voice
from app.domain.generation.operations import create_generation_job
from app.domain.generation.operations import GenerationDomainError
from tests.util import fresh_client, insert_asset, make_voice


def _workspace() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _submit(ws: str, sources: list[dict]) -> str:
    """走漏斗;返回它拒的理由(模型不存在那一道在后面,过了授权一定会撞上它)。"""
    with SessionLocal() as db, pytest.raises(GenerationDomainError) as refused:
        create_generation_job(
            db, origin=STUDIO_ORIGIN, workspace_id=ws, session_id=None, project_id=None, created_by=None,
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
    line = insert_asset(ws, kind="audio", name="开场.wav", voices=[voice])
    face = insert_asset(ws, kind="image", name="脸.png")
    sources = [{"asset_id": face, "role": "first_frame"}, {"asset_id": line, "role": "driving_audio"}]
    assert _submit(ws, sources) == "genErr_voiceConsentMissing"

    with SessionLocal() as db:
        db.get(Voice, voice).consent_kind = "fictional"
        db.commit()
    assert _submit(ws, sources) != "genErr_voiceConsentMissing", "声明过是谁的就放行(虚构也算)"


def test_从克隆配音截出拼出的音频_照样查每一把嗓子(tmp_path) -> None:
    """数字人长片每段的驱动音频都是截出来的:截出来的、几句拼起来的都继承出处的嗓子(ADR 0093)。
    此前只查素材自己记的那一把,截一刀就查不到了;拼两把嗓子时干脆一把都不记。"""
    import subprocess

    from app.core.config import settings
    from app.domain.assets.importer import register_file_asset
    from app.domain.assets.lineage import CONCAT, TRIM, derived

    ws = _workspace()
    wav = tmp_path / "line.wav"
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", str(wav)], check=True)
    undeclared = make_voice(ws, "老王的嗓子")
    declared = make_voice(ws, "小李的嗓子")
    with SessionLocal() as db:
        db.get(Voice, declared).consent_kind = "self"
        db.commit()
        wang = register_file_asset(db, workspace_id=ws, project_id=None, source_path=wav, name="老王", source="tts",
                                   ai_generated=True, voices=[undeclared])
        li = register_file_asset(db, workspace_id=ws, project_id=None, source_path=wav, name="小李", source="tts",
                                 ai_generated=True, voices=[declared])
        cut = register_file_asset(db, workspace_id=ws, project_id=None, source_path=wav, name="截一段",
                                  source="generated", derived_from=derived(TRIM, wang.id))
        both = register_file_asset(db, workspace_id=ws, project_id=None, source_path=wav, name="两人拼一段",
                                   source="tts", derived_from=derived(CONCAT, li.id, wang.id))
        assert cut.voices == [undeclared] and sorted(both.voices) == sorted([declared, undeclared])
        cut_id, both_id = cut.id, both.id
    face = insert_asset(ws, kind="image", name="脸.png")
    for line in (cut_id, both_id):
        assert _submit(ws, [{"asset_id": face, "role": "first_frame"}, {"asset_id": line, "role": "driving_audio"}]) \
            == "genErr_voiceConsentMissing"
    with SessionLocal() as db:
        db.get(Voice, undeclared).consent_kind = "fictional"
        db.commit()
    for line in (cut_id, both_id):
        assert _submit(ws, [{"asset_id": face, "role": "first_frame"}, {"asset_id": line, "role": "driving_audio"}]) \
            != "genErr_voiceConsentMissing"


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




def test_智能体开卡时就说_不等人批准之后才被拒() -> None:
    from app.domain.agent.confirmable.generation import _validate_generate_video
    from app.domain.agent.errors import ConfirmationError

    ws = _workspace()
    voice = make_voice(ws, "老王的嗓子")
    line = insert_asset(ws, kind="audio", name="开场.wav", voices=[voice])
    face = insert_asset(ws, kind="image", name="脸.png")
    payload = {"source_assets": [{"asset_id": face, "role": "first_frame"}, {"asset_id": line, "role": "driving_audio"}],
               "digital_human_consent": True, "prompt": "", "kind": "video"}
    with SessionLocal() as db, pytest.raises(ConfirmationError) as refused:
        _validate_generate_video(db, ws, payload, None)
    assert "老王的嗓子" in str(refused.value)
