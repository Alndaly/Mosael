"""音色选择改存一个 `VoiceRef` 的那五步迁移(ADR 0087 第 2 步)。

读的一侧只认新形状(`VoiceRef.of` 不认 `engine_voice` / `voice_id` / `clone_engine`…),所以每一步都得把库里的旧形状
真的搬对:喂老库那样的行,看搬成了什么、边界怎么处理(克隆音色 vs 引擎音色、没选嗓子、厂商对不上的默认模型),
再跑一次什么都不做。真库副本上的试跑见提交说明;这里钉的是每一种形状。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import (
    _migrate_agent_voice_prefs_store_a_voice_ref,
    _migrate_character_voices_become_voice_refs,
    _migrate_dub_lines_use_the_voice_ref_identity,
    _migrate_speech_records_store_a_voice_ref,
    _migrate_voice_default_stores_a_voice_ref,
)
from app.domain.jobs import create_job
from app.db.models import Asset, Entity, GeneratedAsset, GenerationJob, GenerationSession, ProviderModel
from app.domain.voices.voice_ref import VoiceRef
from tests.util import add_provider, fresh_client, make_voice, user_id


def _workspace() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _columns(table: str) -> set[str]:
    with engine.begin() as conn:
        return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}


def _old_agent_voice_prefs(rows: list[dict]) -> None:
    """把 agent_voice_prefs 换回改形之前的那张表(六格音色),塞进这几行。"""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE agent_voice_prefs"))
        conn.execute(text(
            "CREATE TABLE agent_voice_prefs (owner_user_id VARCHAR(64) PRIMARY KEY, engine VARCHAR(40) NOT NULL DEFAULT '', "
            "engine_voice VARCHAR(120) NOT NULL DEFAULT '', engine_voice_resource VARCHAR(200) NOT NULL DEFAULT '', "
            "engine_model VARCHAR(120) NOT NULL DEFAULT '', provider_profile_id VARCHAR(64), voice_id VARCHAR(64), "
            "speed FLOAT NOT NULL DEFAULT 1.0, enabled BOOLEAN NOT NULL DEFAULT 0, asr_engine VARCHAR(100) NOT NULL DEFAULT '', "
            "speak_early BOOLEAN NOT NULL DEFAULT 1, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
        for row in rows:
            conn.execute(text(
                "INSERT INTO agent_voice_prefs (owner_user_id, engine, engine_voice, engine_voice_resource, engine_model, "
                "provider_profile_id, voice_id, speed) VALUES (:owner, :engine, :engine_voice, :resource, :model, :profile, "
                ":voice_id, 1.25)"
            ), {"engine_voice": "", "resource": "", "model": "", "profile": None, "voice_id": None, **row})


def _agent_voices() -> dict[str, dict]:
    with engine.begin() as conn:
        return {owner: json.loads(voice) for owner, voice in conn.execute(text("SELECT owner_user_id, voice FROM agent_voice_prefs"))}


def test_朗读偏好的六格并成一把嗓子_tts_默认模型并进来之后删掉() -> None:
    workspace = _workspace()
    me = user_id()
    library = make_voice(workspace)
    with SessionLocal() as db:
        profile = add_provider(db, name="百炼", vendor="alibaba", api_key="sk", model="cosyvoice-v3-flash",
                               capability_ids=["tts"], make_default=False)
        model_row = db.query(ProviderModel).filter(ProviderModel.provider_profile_id == profile.id).one()
        db.commit()
        profile_id, model_row_id = profile.id, model_row.id
    _old_agent_voice_prefs([
        #: 我:CosyVoice 的引擎音色,没写模型 —— 旧的 tts 默认正好是这家这一族的模型,并进来。
        {"owner": me, "engine": "builtin:alibaba-cosyvoice", "engine_voice": "longxiaochun_v3"},
        #: 别人:火山账号音色,带着资源族和手写的模型。
        {"owner": "u-volcano", "engine": "builtin:volcano", "engine_voice": "S_abc", "resource": "seed-icl-2.0",
         "model": "seed-icl-2.0", "profile": "p-1"},
        #: 配音库里的嗓子交给 CosyVoice 念(ADR 0037)。
        {"owner": "u-clone", "engine": "builtin:alibaba-cosyvoice", "voice_id": library},
        #: 只选了引擎、没选嗓子:不是一把能念的嗓子。
        {"owner": "u-bare", "engine": "builtin:edge"},
    ])
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO provider_defaults (capability, owner_user_id, provider_model_id, updated_at) "
                          "VALUES ('tts', :me, :m, CURRENT_TIMESTAMP)"),
                     {"me": me, "m": model_row_id})
        #: 别人那条 tts 默认的厂商对不上他的引擎(火山):不并,照样删。
        conn.execute(text("INSERT INTO provider_defaults (capability, owner_user_id, provider_model_id, updated_at) "
                          "VALUES ('tts', 'u-volcano', :m, CURRENT_TIMESTAMP)"),
                     {"m": model_row_id})

    _migrate_agent_voice_prefs_store_a_voice_ref()

    assert {"engine", "engine_voice", "engine_voice_resource", "engine_model", "provider_profile_id", "voice_id"}.isdisjoint(
        _columns("agent_voice_prefs")), "六列旧格都删了"
    voices = _agent_voices()
    assert VoiceRef.of(voices[me]) == VoiceRef("builtin:alibaba-cosyvoice", voice="longxiaochun_v3", model="cosyvoice-v3-flash",
                                               connection=profile_id)
    assert VoiceRef.of(voices["u-volcano"]) == VoiceRef("builtin:volcano", voice="S_abc", model="seed-icl-2.0", connection="p-1",
                                                        extra={"resource_id": "seed-icl-2.0"})
    assert VoiceRef.of(voices["u-clone"]) == VoiceRef("builtin:alibaba-cosyvoice", cloned_voice=library)
    assert voices["u-bare"] == {}
    with engine.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM provider_defaults WHERE capability = 'tts'")).scalar() == 0
        #: 语速、开关这些不是嗓子的格原样留着。
        assert conn.execute(text("SELECT speed FROM agent_voice_prefs WHERE owner_user_id = :me"), {"me": me}).scalar() == 1.25

    _migrate_agent_voice_prefs_store_a_voice_ref()
    assert _agent_voices() == voices, "再跑一次什么都不做"


def test_部署默认的两格并成一把嗓子() -> None:
    _workspace()
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE voice_default_config"))
        conn.execute(text(
            "CREATE TABLE voice_default_config (id VARCHAR(64) PRIMARY KEY, engine VARCHAR(80) NOT NULL DEFAULT '', "
            "voice VARCHAR(200) NOT NULL DEFAULT '', updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        ))
        conn.execute(text("INSERT INTO voice_default_config (id, engine, voice) VALUES ('default', 'builtin:edge', 'zh-CN-YunxiNeural')"))

    _migrate_voice_default_stores_a_voice_ref()

    assert _columns("voice_default_config") == {"id", "voice", "updated_at"}
    with engine.begin() as conn:
        stored = json.loads(conn.execute(text("SELECT voice FROM voice_default_config")).scalar())
    assert VoiceRef.of(stored) == VoiceRef("builtin:edge", voice="zh-CN-YunxiNeural")

    _migrate_voice_default_stores_a_voice_ref()
    with engine.begin() as conn:
        assert json.loads(conn.execute(text("SELECT voice FROM voice_default_config")).scalar()) == stored


def test_人物资产的引擎和音色两格并成一把嗓子() -> None:
    workspace = _workspace()
    library = make_voice(workspace)
    shapes = {
        "edge": {"voice_engine": "builtin:edge", "voice_id": "zh-CN-XiaoxiaoNeural", "real_person": False},
        #: 没写引擎的是配音库里的(旧的规范化就这么补)。
        "library": {"voice_id": library},
        #: 能复刻的远端引擎上,那一格正好是配音库里的嗓子:克隆音色。
        "remote": {"voice_engine": "builtin:alibaba-cosyvoice", "voice_id": library},
        #: 只有引擎没挑嗓子 = 没选,两个键一起删。
        "bare": {"voice_engine": "builtin:edge", "blockout_color": "#ff8800"},
    }
    with SessionLocal() as db:
        ids = {}
        for name, attributes in shapes.items():
            entity = Entity(workspace_id=workspace, kind="character", name=name, attributes=attributes)
            db.add(entity)
            db.flush()
            ids[name] = entity.id
        db.commit()

    _migrate_character_voices_become_voice_refs()

    with SessionLocal() as db:
        migrated = {name: dict(db.get(Entity, entity_id).attributes) for name, entity_id in ids.items()}
    assert migrated["edge"] == {"real_person": False, "voice": {"engine": "builtin:edge", "voice": "zh-CN-XiaoxiaoNeural"}}
    assert migrated["library"] == {"voice": {"engine": "builtin:clone", "cloned_voice": library}}
    assert migrated["remote"] == {"voice": {"engine": "builtin:alibaba-cosyvoice", "cloned_voice": library}}
    assert migrated["bare"] == {"blockout_color": "#ff8800"}

    _migrate_character_voices_become_voice_refs()
    with SessionLocal() as db:
        assert {name: dict(db.get(Entity, entity_id).attributes) for name, entity_id in ids.items()} == migrated


def test_创作页的语音记录_音色改成一把嗓子_产出那一行跟着重写() -> None:
    workspace = _workspace()
    library = make_voice(workspace)
    requests = {
        #: ADR 0055 并进来的老记录:引擎是裸名。
        "edge": ("edge", None, {"prompt": "你好", "voice": "zh-CN-XiaoxiaoNeural"}),
        "clone": ("builtin:clone", None, {"prompt": "你好", "voice": library, "clone_engine": "f5-tts", "clone_model": "fr",
                                          "voice_label": "小明", "speed": 1.0}),
        "volcano": ("builtin:volcano", None, {"prompt": "你好", "voice": "S_abc", "voice_resource": "seed-icl-2.0"}),
    }
    with SessionLocal() as db:
        session = GenerationSession(workspace_id=workspace, owner_user_id=None, title="语音", kind="speech", model="m")
        db.add(session)
        db.flush()
        ids, jobs = {}, {}
        for name, (provider, profile, request) in requests.items():
            jobs[name] = create_job(db, workspace_id=workspace, kind="tts", payload={}, created_by=None).id
            record = GenerationJob(workspace_id=workspace, session_id=session.id, provider=provider, model="m", kind="speech",
                                   request=request, provider_profile_id=profile, job_id=jobs[name])
            db.add(record)
            db.flush()
            ids[name] = record.id
        asset = Asset(workspace_id=workspace, kind="audio", name="念的", file_key="media/x.mp3")
        db.add(asset)
        db.flush()
        db.add(GeneratedAsset(asset_id=asset.id, provider="builtin:clone", model="m", prompt="你好",
                              parameters={key: value for key, value in requests["clone"][2].items() if key != "prompt"},
                              job_id=jobs["clone"]))
        db.commit()
        asset_id = asset.id

    _migrate_speech_records_store_a_voice_ref()

    with SessionLocal() as db:
        migrated = {name: dict(db.get(GenerationJob, record_id).request) for name, record_id in ids.items()}
        parameters = dict(db.get(GeneratedAsset, asset_id).parameters)
    assert migrated["edge"] == {"prompt": "你好", "voice": {"engine": "builtin:edge", "voice": "zh-CN-XiaoxiaoNeural"}}
    assert migrated["clone"] == {"prompt": "你好", "voice_label": "小明", "speed": 1.0,
                                 "voice": {"engine": "builtin:clone", "cloned_voice": library, "model": "f5-tts/fr"}}
    assert migrated["volcano"]["voice"] == {"engine": "builtin:volcano", "voice": "S_abc", "extra": {"resource_id": "seed-icl-2.0"}}
    assert "voice_resource" not in migrated["volcano"]
    assert parameters == {key: value for key, value in migrated["clone"].items() if key != "prompt"}

    _migrate_speech_records_store_a_voice_ref()
    with SessionLocal() as db:
        assert {name: dict(db.get(GenerationJob, record_id).request) for name, record_id in ids.items()} == migrated


def test_字幕配音记在音频上的嗓子身份照新形状重算() -> None:
    workspace = _workspace()
    library = make_voice(workspace)
    identities = {
        "edge": ("engine=builtin:edge|engine_voice=zh-TW-HsiaoChenNeural|speed=1.0",
                 "engine=builtin:edge|voice=zh-TW-HsiaoChenNeural|speed=1.0"),
        "clone": (f"engine=builtin:clone|voice_id={library}|clone_engine=f5-tts|speed=1.2",
                  f"engine=builtin:clone|cloned_voice={library}|model=f5-tts|speed=1.2"),
    }
    with SessionLocal() as db:
        ids = {}
        for name, (old, _new) in identities.items():
            asset = Asset(workspace_id=workspace, kind="audio", name=name, file_key="media/d.wav",
                          media_info={"duration": 2.0, "dub_line": {"text": "一句", "voice": old}})
            db.add(asset)
            db.flush()
            ids[name] = asset.id
        db.commit()

    _migrate_dub_lines_use_the_voice_ref_identity()

    with SessionLocal() as db:
        for name, (_old, new) in identities.items():
            info = db.get(Asset, ids[name]).media_info
            assert info["dub_line"] == {"text": "一句", "voice": new}, name
            assert info["duration"] == 2.0

    _migrate_dub_lines_use_the_voice_ref_identity()
    with SessionLocal() as db:
        assert [db.get(Asset, ids[name]).media_info["dub_line"]["voice"] for name in identities] == [
            new for _old, new in identities.values()
        ]
