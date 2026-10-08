"""创作页的语音、播客(ADR 0055):记录收在生成会话里,活儿由配音那一族做。

钉住的是这几条:
- 念一段字 / 一段播客是会话里的一条记录(kind `speech` / `podcast`),任务种类还是 `tts` / `podcast`;
- 产出在**任务落「成功」的同一个事务里**挂到记录上(result_asset_id + generated_assets),不是事后补;
- 用量记在记录名下(`generation_job`),任务清掉之后脚注的价格还在;
- 失败、停下抄到记录上(和生成同一个落终态监听);
- 会话锁族:有记录的语音会话不能拿来出图、念播客;
- 素材名是「音色名 · 文本开头」/「主题 · 播客」;播客的对谈稿跟着素材走;
- 创作页的任务列表只列挂着记录的任务。
"""

from __future__ import annotations

from app.domain.generation.origins import STUDIO_ORIGIN
import threading
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Asset, GeneratedAsset, GenerationJob, GenerationSession, Job, ProviderUsageEvent
from app.domain.jobs import CANCELLED_ERROR_KEY, create_job, wait_for_idle_jobs
from tests.util import fresh_client, until


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


@pytest.fixture
def spoken(monkeypatch):
    """远端引擎念出来的那一段(不联网):记下合成收到了什么,交回一个文件。"""
    from app.domain.voices import voices as voices_domain

    calls: list[dict] = []

    def fake_speak(_db, **kwargs):
        calls.append(kwargs)
        out = Path(kwargs["out_dir"]) / "speech.mp3"
        out.write_bytes(b"ID3fake-audio")
        return out

    monkeypatch.setattr(voices_domain, "speak_to_file", fake_speak)
    return calls


def _speak(client, ws: str, **extra):
    body = {"workspace_id": ws, "text": "欢迎来到 Mosael 的世界,今天我们聊聊 AI 剪辑", "engine": "builtin:edge",
            "voice": "zh-CN-XiaoxiaoNeural", **extra}
    return client.post("/api/generation/speech", json=body)


def _records(client, ws: str, session_id: str) -> list[dict]:
    return client.get("/api/generation/jobs", params={"workspace_id": ws, "session_id": session_id}).json()


def test_念一段字是会话里的一条_产出和用量都挂在记录上(spoken) -> None:
    client = fresh_client()
    ws = _workspace(client)
    res = _speak(client, ws, speed=1.25)
    assert res.status_code == 200, res.text
    created, job = res.json()["generation"], res.json()["job"]
    assert created["kind"] == "speech" and job["kind"] == "tts", "记录是语音,任务还是配音那一族的"
    assert created["provider"] == "builtin:edge" and created["model"] == "zh-CN-XiaoxiaoNeural"
    assert created["request"]["voice_label"] == "晓晓(女·温暖)" and created["request"]["speed"] == 1.25
    assert created["request"]["engine_label"], "引擎名记下来:引擎以后不在了,脚注照样说得出是谁念的"
    session_id = created["session_id"]
    assert job["payload"]["session_id"] == session_id, "任务中心「前往」打开这条会话"

    assert wait_for_idle_jobs(15)
    [record] = _records(client, ws, session_id)
    assert record["result_asset_id"] and record["result_asset_ids"] == [record["result_asset_id"]]
    with SessionLocal() as db:
        asset = db.get(Asset, record["result_asset_id"])
        assert asset.name == "晓晓 · 欢迎来到 Mosael 的世界,…", "音色名 · 文本开头,不是 `zh-CN-XiaoxiaoNeural · 配音`"
        made = db.get(GeneratedAsset, asset.id)
        assert (made.provider, made.model, made.job_id) == ("builtin:edge", "zh-CN-XiaoxiaoNeural", job["id"])
    [call] = spoken
    assert (call["source_type"], call["source_id"]) == ("generation_job", record["id"]), "用量记在记录名下"

    sessions = client.get("/api/generation/sessions", params={"workspace_id": ws, "kind": "speech"}).json()
    assert [one["id"] for one in sessions] == [session_id]
    assert sessions[0]["kind"] == "speech" and sessions[0]["model"] == "builtin:edge"
    assert sessions[0]["title"].startswith("欢迎来到 Mosael")


def test_产出在任务落成功的同一个事务里挂上_不等事后补(spoken, monkeypatch) -> None:
    """落终态监听在提交之后另开事务:靠它挂的话,中间那一下界面读到「成功了、没有产出」,画成一张一直在排队的占位。"""
    from app.domain import jobs as jobs_bus

    seen: list[tuple[str, object]] = []
    real_finish = jobs_bus.finish_job

    def watching_finish(db, job, **kwargs):
        if kwargs.get("status") == "succeeded":
            record = db.scalars(select(GenerationJob).where(GenerationJob.job_id == job.id)).first()
            seen.append((job.kind, record.result_asset_id if record is not None else None))
        return real_finish(db, job, **kwargs)

    from app.domain.voices import voices as voices_domain

    monkeypatch.setattr(voices_domain, "finish_job", watching_finish)
    client = fresh_client()
    ws = _workspace(client)
    assert _speak(client, ws).status_code == 200
    assert wait_for_idle_jobs(15)
    assert len(seen) == 1 and seen[0][0] == "tts" and seen[0][1], seen


def test_同一条会话接着念_会话的种类是语音_标题不改(spoken) -> None:
    client = fresh_client()
    ws = _workspace(client)
    first = _speak(client, ws).json()["generation"]
    again = _speak(client, ws, session_id=first["session_id"], text="第二段").json()["generation"]
    assert again["session_id"] == first["session_id"]
    assert wait_for_idle_jobs(15)
    assert [one["request"]["prompt"] for one in _records(client, ws, first["session_id"])][-1] == "第二段"


def test_没念成的原因抄到记录上(monkeypatch) -> None:
    from app.domain.voices import voices as voices_domain
    from app.domain.voices.errors import VoiceError

    def broken(_db, **_kwargs):
        raise VoiceError("voiceErr_synthNoAudio")

    monkeypatch.setattr(voices_domain, "speak_to_file", broken)
    client = fresh_client()
    ws = _workspace(client)
    created = _speak(client, ws).json()["generation"]
    assert wait_for_idle_jobs(15)
    #: 抄原因是落终态之后的收拾,在那次提交之后
    assert until(lambda: _records(client, ws, created["session_id"])[0]["error"] is not None, timeout=10)
    [record] = _records(client, ws, created["session_id"])
    assert record["error"] and record["error_summary"] and record["stopped"] is False
    assert record["result_asset_id"] is None and record["retrievable"] is False, "语音没有「重新取回」"


def test_停下的那一条记成已停止_没有产出(monkeypatch) -> None:
    from app.domain.voices import voices as voices_domain

    started, release = threading.Event(), threading.Event()

    def slow(_db, **kwargs):
        started.set()
        release.wait(10)
        out = Path(kwargs["out_dir"]) / "speech.mp3"
        out.write_bytes(b"ID3fake-audio")
        return out

    monkeypatch.setattr(voices_domain, "speak_to_file", slow)
    client = fresh_client()
    ws = _workspace(client)
    res = _speak(client, ws).json()
    assert started.wait(10)
    #: 在念的时候任务上说的是音色名,不是音色 id
    with SessionLocal() as db:
        running = db.get(Job, res["job"]["id"]).message
    assert "晓晓" in running and "zh-CN-XiaoxiaoNeural" not in running, running
    assert client.post(f"/api/jobs/{res['job']['id']}/cancel").status_code == 200
    release.set()
    assert wait_for_idle_jobs(15)
    assert until(lambda: _records(client, ws, res["generation"]["session_id"])[0]["stopped"], timeout=10)
    [record] = _records(client, ws, res["generation"]["session_id"])
    assert record["stopped"] is True and record["result_asset_id"] is None
    with SessionLocal() as db:
        assert db.get(GenerationJob, record["id"]).error_key == CANCELLED_ERROR_KEY


def test_会话锁族_有记录的语音会话不出图也不念播客_空会话随便换(spoken) -> None:
    client = fresh_client()
    ws = _workspace(client)
    created = _speak(client, ws).json()["generation"]
    session_id = created["session_id"]
    locked = client.patch(f"/api/generation/sessions/{session_id}", json={"kind": "image"})
    assert locked.status_code == 422 and "新开" in locked.json()["detail"], locked.text
    podcast = client.post("/api/generation/podcast", json={
        "workspace_id": ws, "session_id": session_id, "mode": "research", "text": "AI 剪辑",
    })
    assert podcast.status_code == 422 and "语音" in podcast.json()["detail"], podcast.text
    image = client.post("/api/generation/jobs", json={
        "workspace_id": ws, "session_id": session_id, "provider": "openai", "model": "gpt-image-1", "kind": "image",
        "prompt": "一张海报",
    })
    assert image.status_code == 422 and "新开" in image.json()["detail"], "创作页往语音会话里出图:在解析模型之前就拦下"
    assert client.patch(f"/api/generation/sessions/{session_id}", json={"kind": "speech"}).status_code == 200

    empty = client.post("/api/generation/sessions", json={"workspace_id": ws, "kind": "image"}).json()
    moved = client.patch(f"/api/generation/sessions/{empty['id']}", json={"kind": "speech"})
    assert moved.status_code == 200 and moved.json()["kind"] == "speech", "还空着的会话不是任何东西的会话"
    assert wait_for_idle_jobs(15)

    #: 锁族是创作页的规矩,不是会话本身的:别的入口(按出处归的会话,一块画板一条,ADR 0052)往里放别的种类照样放得进
    from app.domain.generation.voiced import create_podcast as podcast_into

    with SessionLocal() as db:
        owner = db.get(GenerationSession, session_id).owner_user_id
        record, _job = podcast_into(db, workspace_id=ws, session_id=session_id, project_id=None, created_by=owner,
                                    mode="research", text="AI 剪辑", origin=STUDIO_ORIGIN)
        assert record.session_id == session_id
        db.rollback()


def test_视觉一族里换种类_会话记着最后一次用的() -> None:
    """图像会话里接着生视频是同一族:会话的 kind 改成视频,创作页的筛选把它归到「视频」。"""
    from app.domain.generation.operations import _named_session, _resolve_session

    client = fresh_client()
    ws = _workspace(client)
    with SessionLocal() as db:
        session = GenerationSession(workspace_id=ws, owner_user_id=None, title="海报", kind="image", model="m")
        db.add(session)
        db.flush()
        db.add(GenerationJob(workspace_id=ws, session_id=session.id, provider="p", model="m", kind="image", request={}))
        db.flush()
        session.owner_user_id = client.get("/api/auth/me").json()["id"]
        db.commit()
        named = _named_session(db, workspace_id=ws, session_id=session.id, actor=session.owner_user_id, family_of="video")
        resolved = _resolve_session(db, workspace_id=ws, named=named, prompt="动起来", created_by=session.owner_user_id,
                                    engine=(None, "v", "video"), origin=STUDIO_ORIGIN)
        assert resolved.id == session.id and resolved.kind == "video"
        from app.domain.generation.operations import GenerationDomainError

        with pytest.raises(GenerationDomainError):
            _named_session(db, workspace_id=ws, session_id=session.id, actor=session.owner_user_id, family_of="audio")


def test_播客照稿念_一段一轮_对谈稿跟着素材走(monkeypatch) -> None:
    import app.ai.providers as providers
    from app.ai.providers import PodcastSynthesisResult

    asked: dict = {}

    def fake_podcast(appid, token, **kwargs):
        asked.update(kwargs)
        kwargs["out_path"].write_bytes(b"ID3fake-podcast")
        return PodcastSynthesisResult(audio=b"x", texts=[{"speaker": turn["speaker"], "text": turn["text"]}
                                                         for turn in kwargs["turns"]])

    monkeypatch.setattr(providers, "synthesize_volcano_podcast", fake_podcast)
    client = fresh_client()
    ws = _workspace(client)
    speakers = [{"value": "zh_male_dayixiansheng_v2_saturn_bigtts", "label": "大壹先生"},
                {"value": "zh_female_mizaitongxue_v2_saturn_bigtts", "label": "咪仔同学"}]
    res = client.post("/api/generation/podcast", json={
        "workspace_id": ws, "mode": "read", "speakers": speakers, "speed": 1.0,
        "turns": [{"speaker": 0, "text": "大家好,欢迎收听。"}, {"speaker": 1, "text": "今天聊聊 AI 剪辑。"},
                  {"speaker": 0, "text": "先说结论。"}],
    })
    assert res.status_code == 200, res.text
    created = res.json()["generation"]
    assert created["kind"] == "podcast" and res.json()["job"]["kind"] == "podcast"
    assert created["request"]["turns"][1] == {"speaker": 1, "text": "今天聊聊 AI 剪辑。"}
    assert [one["label"] for one in created["request"]["speakers"]] == ["大壹先生", "咪仔同学"]
    assert wait_for_idle_jobs(15)

    assert asked["turns"] == [
        {"speaker": "zh_male_dayixiansheng_v2_saturn_bigtts", "text": "大家好,欢迎收听。"},
        {"speaker": "zh_female_mizaitongxue_v2_saturn_bigtts", "text": "今天聊聊 AI 剪辑。"},
        {"speaker": "zh_male_dayixiansheng_v2_saturn_bigtts", "text": "先说结论。"},
    ], "一段一轮原样交出去,发音人按下标换成音色"
    [record] = _records(client, ws, created["session_id"])
    with SessionLocal() as db:
        asset = db.get(Asset, record["result_asset_id"])
        assert asset.name == "大家好,欢迎收听。 · 播客"
        assert [one["text"] for one in asset.media_info["dialogue"]] == ["大家好,欢迎收听。", "今天聊聊 AI 剪辑。", "先说结论。"]
        assert asset.media_info["speakers"][0]["value"] == "zh_male_dayixiansheng_v2_saturn_bigtts"
        event = db.scalars(select(ProviderUsageEvent).where(ProviderUsageEvent.capability == "podcast")).one()
        assert (event.source_type, event.source_id) == ("generation_job", record["id"])
        assert event.units["characters"] == len("大家好,欢迎收听。今天聊聊 AI 剪辑。先说结论。"), "按交出去的稿子计字数"


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"mode": "read", "turns": []}, 422),
        ({"mode": "read", "turns": [{"speaker": 2, "text": "第三位"}]}, 422),
        ({"mode": "read", "turns": [{"speaker": 0, "text": "字" * 281}]}, 422),
        ({"mode": "read", "turns": [{"speaker": 0, "text": "一句"}] * 61}, 422),
        ({"mode": "summarize", "text": "  "}, 422),
        ({"mode": "research", "text": ""}, 422),
        ({"mode": "summarize", "text": "材料", "speakers": [{"value": "a"}, {"value": "a"}]}, 422),
    ],
)
def test_播客建任务之前就说清哪里不对(body: dict, status: int) -> None:
    client = fresh_client()
    ws = _workspace(client)
    res = client.post("/api/generation/podcast", json={"workspace_id": ws, **body})
    assert res.status_code == status, res.text
    with SessionLocal() as db:
        assert db.scalars(select(Job).where(Job.kind == "podcast")).first() is None, "没建任务"
        assert db.scalars(select(GenerationSession)).first() is None, "没开会话"


def test_播客没给发音人_用目录里的前两位(monkeypatch) -> None:
    import app.ai.providers as providers
    from app.ai.providers import PODCAST_SPEAKERS, PodcastSynthesisResult

    asked: dict = {}

    def fake_podcast(appid, token, **kwargs):
        asked.update(kwargs)
        kwargs["out_path"].write_bytes(b"ID3fake-podcast")
        return PodcastSynthesisResult(audio=b"x", texts=[])

    monkeypatch.setattr(providers, "synthesize_volcano_podcast", fake_podcast)
    client = fresh_client()
    ws = _workspace(client)
    res = client.post("/api/generation/podcast", json={"workspace_id": ws, "mode": "research", "text": "AI 剪辑的未来"})
    assert res.status_code == 200, res.text
    assert wait_for_idle_jobs(15)
    assert asked["speakers"] == [voice for voice, _ in PODCAST_SPEAKERS[:2]]
    assert asked["prompt_text"] == "AI 剪辑的未来" and asked["input_text"] == ""
    assert [one["value"] for one in res.json()["generation"]["request"]["speakers"]] == asked["speakers"]


def test_创作页的任务列表只列挂着记录的任务(spoken) -> None:
    client = fresh_client()
    ws = _workspace(client)
    recorded = _speak(client, ws).json()["job"]["id"]
    with SessionLocal() as db:
        bare = create_job(db, workspace_id=ws, kind="tts", payload={"subject": "字幕一句"}, created_by=None)
        bare.status = "succeeded"
        db.commit()
        bare_id = bare.id
    assert wait_for_idle_jobs(15)
    listed = [one["id"] for one in client.get("/api/jobs", params={"workspace_id": ws, "recorded": "true"}).json()]
    assert listed == [recorded]
    every = {one["id"] for one in client.get("/api/jobs", params={"workspace_id": ws}).json()}
    assert {recorded, bare_id} <= every


def test_照稿念的上限在领域里也守着_不只靠接口的校验() -> None:
    """智能体、以后别的入口直接调 start_podcast,不经过请求体的 max_length:60 段、每段 280 字照样在建任务之前拦下。"""
    from app.domain.voices.errors import VoiceError
    from app.domain.voices.voices import start_podcast

    client = fresh_client()
    ws = _workspace(client)
    with SessionLocal() as db:
        with pytest.raises(VoiceError, match="60"):
            start_podcast(db, workspace_id=ws, project_id=None, created_by=None, mode="read",
                          turns=[{"speaker": 0, "text": "一句"}] * 61)
        with pytest.raises(VoiceError, match="280"):
            start_podcast(db, workspace_id=ws, project_id=None, created_by=None, mode="read",
                          turns=[{"speaker": 1, "text": "字" * 281}])
        with pytest.raises(VoiceError):
            start_podcast(db, workspace_id=ws, project_id=None, created_by=None, mode="read",
                          turns=[{"speaker": True, "text": "布尔不是下标"}])
        assert db.scalars(select(Job).where(Job.kind == "podcast")).first() is None


def test_素材名的文本开头_中文十六个字_西文多给一些() -> None:
    from app.domain.voices.voices import podcast_asset_name, speech_asset_name

    assert speech_asset_name("晓晓(女·温暖)", "短句") == "晓晓 · 短句"
    assert speech_asset_name("Jenny", "Welcome to Mosael. Today we look at AI editing.") == "Jenny · Welcome to Mosael. Today we…"
    assert speech_asset_name("alloy", "  多  个\n空白  ") == "alloy · 多 个 空白"
    assert podcast_asset_name("") == "未命名 · 播客"
