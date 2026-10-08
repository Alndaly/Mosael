"""`speech-and-podcast-join-creation-sessions`(ADR 0055 §8):创作页之前做的语音、播客并进创作会话。

喂的是**照真实库的形状**造的老任务行:语音任务的 payload 只存了前 200 字(`text[:200]`)、播客 500 字;播客的对谈稿只在
`result.texts` 里;字幕配音逐句的合成带 `intermediate`、工作流派的是子任务;任务行被「清空已结束」删掉之后,素材还在、
却没人记得是谁做的(孤儿)。每一种该收的收、不该收的不碰,跑两遍和一遍一样。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.migrations import _migrate_speech_and_podcast_join_creation_sessions as migrate
from app.db.models import Asset, GeneratedAsset, GenerationJob, GenerationSession, Job, User, Voice
from tests.util import fresh_client

T0 = datetime(2026, 9, 30, 10, 0, 0)


_CLIENT: list = []


def _setup() -> tuple[str, str, str]:
    client = fresh_client()
    _CLIENT[:] = [client]
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        me = db.scalars(select(User).order_by(User.created_at)).first().id
        colleague = User(username="colleague", display_name="同事", password_hash="x")
        db.add(colleague)
        db.commit()
        return ws, me, colleague.id


def _asset(db, ws: str, asset_id: str, name: str, *, source: str, media_info: dict | None = None,
           intermediate: str = "") -> None:
    db.add(Asset(id=asset_id, workspace_id=ws, kind="audio", name=name, source=source,
                 media_info=media_info or {"duration": 3.0}, intermediate=intermediate))


def _job(db, ws: str, job_id: str, kind: str, payload: dict, result: dict, *, by: str | None, minutes: int,
         status: str = "succeeded", parent: str | None = None) -> None:
    at = T0 + timedelta(minutes=minutes)
    db.add(Job(id=job_id, workspace_id=ws, kind=kind, payload=payload, result=result, created_by=by, status=status,
               parent_job_id=parent, created_at=at, updated_at=at + timedelta(seconds=7)))


def _tts_payload(text_: str, **extra: object) -> dict:
    """voices.start_synthesis 写的那一份(老版本):文字只存前 200 字。"""
    return {"subject": text_[:80], "voice_id": None, "project_id": None, "text": text_[:200], "engine": "builtin:edge",
            "clone_engine": "", "clone_model": "", "engine_voice": "zh-CN-XiaoxiaoNeural", "provider_profile_id": None,
            "engine_model": "", "intermediate": "", **extra}


def _podcast_payload(text_: str = "", topic: str = "", mode: str = "summarize") -> dict:
    """voices.start_podcast 写的那一份(老版本):材料只存前 500 字,没有 subject。"""
    return {"project_id": None, "mode": mode, "speakers": ["zh_male_dayixiansheng_v2_saturn_bigtts", "zh_female_mizaitongxue_v2_saturn_bigtts"],
            "text": text_[:500], "topic": topic, "provider_profile_id": None}


def _fixture() -> dict[str, str]:
    ws, me, colleague = _setup()
    long_text = "这是一段很长的旁白。" * 40  # 400 字,payload 里只剩前 200
    material = "播客要改写的材料。" * 80  # 720 字,payload 里只剩前 500
    with SessionLocal() as db:
        voice = Voice(workspace_id=ws, name="我的嗓子", reference_text="参考", consent_kind="self")
        db.add(voice)
        db.flush()
        # 该收的
        _asset(db, ws, "a-edge", "zh-CN-XiaoxiaoNeural · 配音", source="tts")
        _job(db, ws, "j-edge", "tts", _tts_payload(long_text), {"asset_id": "a-edge", "engine": "builtin:edge"}, by=me, minutes=1)
        _asset(db, ws, "a-clone", "我的嗓子 · 配音", source="tts", media_info={"duration": 2.0, "voice_id": voice.id})
        _job(db, ws, "j-clone", "tts",
             _tts_payload("短短一句", engine="builtin:clone", voice_id=voice.id, engine_voice="", clone_engine="f5-tts"),
             {"asset_id": "a-clone", "engine": "f5-tts"}, by=me, minutes=2)
        _asset(db, ws, "a-pod", "播客对话", source="podcast")
        _job(db, ws, "j-pod", "podcast", _podcast_payload(material),
             {"asset_id": "a-pod", "texts": [{"speaker": "zh_male_dayixiansheng_v2_saturn_bigtts", "text": "大家好。"},
                                             {"speaker": "zh_female_mizaitongxue_v2_saturn_bigtts", "text": "今天聊聊。"}]},
             by=me, minutes=3)
        _asset(db, ws, "a-research", "播客对话", source="podcast", media_info={"duration": 9.0, "dialogue": [{"speaker": "x", "text": "早就有的稿"}]})
        _job(db, ws, "j-research", "podcast", _podcast_payload(topic="AI 剪辑的未来" * 60, mode="research"),
             {"asset_id": "a-research", "texts": [{"speaker": "y", "text": "任务里的稿"}]}, by=me, minutes=4)
        _asset(db, ws, "a-colleague", "zh-CN-YunxiNeural · 配音", source="tts")
        _job(db, ws, "j-colleague", "tts", _tts_payload("同事念的", engine_voice="zh-CN-YunxiNeural"),
             {"asset_id": "a-colleague", "engine": "builtin:edge"}, by=colleague, minutes=5)
        # 不该收的
        _asset(db, ws, "a-dub", "zh-TW-HsiaoChenNeural · 配音", source="tts", intermediate="dub_line")
        _job(db, ws, "j-dub", "tts", _tts_payload("字幕一句", intermediate="dub_line"), {"asset_id": "a-dub"}, by=me, minutes=6)
        #: 任务说它是零件、素材那一侧没标上(回填推不出来的那批):照任务说的,不收
        _asset(db, ws, "a-dub-unmarked", "zh-TW-HsiaoChenNeural · 配音", source="tts")
        _job(db, ws, "j-dub-unmarked", "tts", _tts_payload("字幕另一句", intermediate="dub_line"), {"asset_id": "a-dub-unmarked"},
             by=me, minutes=6)
        _asset(db, ws, "a-child", "工作流念的", source="tts")
        _job(db, ws, "j-parent", "workflow", {}, {}, by=me, minutes=7)
        _job(db, ws, "j-child", "tts", _tts_payload("工作流节点念的"), {"asset_id": "a-child"}, by=me, minutes=7, parent="j-parent")
        _job(db, ws, "j-failed", "tts", _tts_payload("没念成"), {}, by=me, minutes=8, status="failed")
        _job(db, ws, "j-gone", "tts", _tts_payload("产出已经删了"), {"asset_id": "deleted-asset"}, by=me, minutes=9)
        _asset(db, ws, "a-nobody", "没人认领", source="tts")
        _job(db, ws, "j-nobody", "tts", _tts_payload("后台念的"), {"asset_id": "a-nobody"}, by=None, minutes=10)
        _asset(db, ws, "a-part", "零件", source="tts", intermediate="dub_line")
        _job(db, ws, "j-part", "tts", _tts_payload("payload 没说是零件"), {"asset_id": "a-part"}, by=me, minutes=11)
        _asset(db, ws, "a-linked", "已经有记录", source="tts")
        _job(db, ws, "j-linked", "tts", _tts_payload("已经有记录的"), {"asset_id": "a-linked"}, by=me, minutes=12)
        linked = GenerationSession(workspace_id=ws, owner_user_id=me, title="已有", kind="speech", model="builtin:edge")
        db.add(linked)
        db.flush()
        db.add(GenerationJob(workspace_id=ws, session_id=linked.id, job_id="j-linked", provider="builtin:edge",
                             model="zh-CN-XiaoxiaoNeural", kind="speech", request={"prompt": "已经有记录的"},
                             result_asset_id="a-linked"))
        # 孤儿:任务行被「清空已结束」删掉了,素材还在
        _asset(db, ws, "a-orphan", "zh-CN-XiaoxiaoNeural · 配音", source="tts")
        db.commit()
        return {"ws": ws, "me": me, "colleague": colleague, "voice": voice.id, "linked": linked.id}


def _state() -> tuple[list, list, list, dict]:
    with SessionLocal() as db:
        sessions = [(one.workspace_id, one.owner_user_id, one.kind, one.title, one.model, one.id)
                    for one in db.scalars(select(GenerationSession).order_by(GenerationSession.created_at))]
        records = [(one.session_id, one.job_id, one.kind, one.provider, one.model, one.request, one.result_asset_id)
                   for one in db.scalars(select(GenerationJob).order_by(GenerationJob.created_at))]
        made = [(one.asset_id, one.provider, one.model, one.prompt, one.job_id) for one in db.scalars(select(GeneratedAsset))]
        infos = {one.id: one.media_info for one in db.scalars(select(Asset))}
    return sessions, records, made, infos


def test_每人每种一条以前的语音和播客_该收的收_不该收的不碰_跑两遍和一遍一样() -> None:
    ids = _fixture()
    migrate()
    first = _state()
    migrate()
    assert _state() == first, "再跑一次什么都不变"
    sessions, records, made, infos = first

    by_title = {(owner, kind): (title, model, session_id) for _ws, owner, kind, title, model, session_id in sessions
                if session_id != ids["linked"]}
    mine_speech = by_title[(ids["me"], "speech")]
    assert mine_speech[0] == "以前的语音"
    assert by_title[(ids["me"], "podcast")][0] == "以前的播客"
    assert by_title[(ids["colleague"], "speech")][0] == "以前的语音", "同事的进同事自己的会话,不进我的"
    assert sum(1 for one in sessions if one[3] in ("以前的语音", "以前的播客")) == 3

    by_job = {job_id: (session_id, kind, provider, model, request, asset) for session_id, job_id, kind, provider, model, request, asset in records}
    assert set(by_job) == {"j-edge", "j-clone", "j-pod", "j-research", "j-colleague", "j-linked"}, (
        "零件、子任务、失败的、产出删了的、没人发起的、产出是零件的都不收;已经有记录的不再收一次"
    )
    edge = by_job["j-edge"]
    assert edge[0] == mine_speech[2] and edge[1:4] == ("speech", "builtin:edge", "zh-CN-XiaoxiaoNeural")
    assert edge[4]["prompt"] == ("这是一段很长的旁白。" * 40)[:200] and edge[4]["truncated"] is True, "只剩开头的标出来"
    assert edge[5] == "a-edge"
    clone = by_job["j-clone"]
    assert clone[2:4] == ("builtin:clone", ids["voice"])
    assert clone[4] == {"prompt": "短短一句", "voice": ids["voice"], "voice_label": "我的嗓子", "clone_engine": "f5-tts"}
    pod = by_job["j-pod"]
    assert pod[1:4] == ("podcast", "builtin:volcano-podcast", "dialogue")
    assert pod[4]["mode"] == "summarize" and pod[4]["truncated"] is True
    assert [one["value"] for one in pod[4]["speakers"]] == ["zh_male_dayixiansheng_v2_saturn_bigtts", "zh_female_mizaitongxue_v2_saturn_bigtts"]
    research = by_job["j-research"]
    assert research[4]["prompt"] == "AI 剪辑的未来" * 60 and "truncated" not in research[4], "主题存的是全文"
    assert by_job["j-linked"][0] == ids["linked"], "原来那条记录不动"

    assert infos["a-pod"]["dialogue"] == [
        {"speaker": "zh_male_dayixiansheng_v2_saturn_bigtts", "text": "大家好。"},
        {"speaker": "zh_female_mizaitongxue_v2_saturn_bigtts", "text": "今天聊聊。"},
    ], "对谈稿抄到素材上:任务清掉之后还在"
    assert [one["value"] for one in infos["a-pod"]["speakers"]] == [one["value"] for one in pod[4]["speakers"]]
    assert infos["a-research"]["dialogue"] == [{"speaker": "x", "text": "早就有的稿"}], "素材上已经有的稿不改写"
    assert infos["a-orphan"] == {"duration": 3.0}, "孤儿留在素材库,什么都不加"
    assert infos["a-edge"] == {"duration": 3.0}

    made_by_asset = {asset_id: (provider, model, prompt, job_id) for asset_id, provider, model, prompt, job_id in made}
    assert made_by_asset["a-edge"][3] == "j-edge" and made_by_asset["a-pod"][0] == "builtin:volcano-podcast"
    assert "a-orphan" not in made_by_asset and "a-dub" not in made_by_asset and "a-dub-unmarked" not in made_by_asset


def test_会话的时间照任务的_最近的一条在最上面() -> None:
    ids = _fixture()
    migrate()
    with SessionLocal() as db:
        session = db.scalars(select(GenerationSession).where(
            GenerationSession.owner_user_id == ids["me"], GenerationSession.kind == "speech",
            GenerationSession.title == "以前的语音")).one()
        assert session.created_at == T0 + timedelta(minutes=1)
        assert session.updated_at == T0 + timedelta(minutes=2, seconds=7), "最后一条(克隆那条)完成的时候"
        records = db.scalars(select(GenerationJob).where(GenerationJob.session_id == session.id)
                             .order_by(GenerationJob.created_at)).all()
        assert [one.job_id for one in records] == ["j-edge", "j-clone"]
        assert records[0].created_at == T0 + timedelta(minutes=1)


def test_任务行后来被清掉_记录照样在_产出还看得见() -> None:
    """迁移出来的记录和创作页新写的同一个形状:任务被「清空已结束」删掉(job_id 置空),记录、产出、对谈稿都还在。"""
    ids = _fixture()
    migrate()
    with SessionLocal() as db:
        db.delete(db.get(Job, "j-pod"))
        db.commit()
    client = _CLIENT[0]
    sessions = client.get("/api/generation/sessions", params={"workspace_id": ids["ws"], "kind": "podcast"}).json()
    assert [one["title"] for one in sessions] == ["以前的播客"]
    records = client.get("/api/generation/jobs", params={"workspace_id": ids["ws"], "session_id": sessions[0]["id"]}).json()
    pod = next(one for one in records if one["result_asset_id"] == "a-pod")
    assert pod["job_id"] is None and pod["result_asset_ids"] == ["a-pod"] and pod["kind"] == "podcast"
    assert pod["error"] is None and pod["stopped"] is False, "没有失败,不画失败卡"
    asset = client.get("/api/assets/a-pod").json()
    assert asset["media_info"]["dialogue"][0]["text"] == "大家好。"
    assert json.dumps(pod["request"], ensure_ascii=False).count("播客要改写的材料") > 0
