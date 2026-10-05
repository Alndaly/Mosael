"""克隆音色复刻到百炼 CosyVoice(ADR 0037):副本的建、用、重建、删,和上传之前要点的那一次头。

**不打网络**:远端换成一个假的百炼账号(`FakeBailian`),它记得建过哪些音色、各绑哪个模型;合成换成一个只认得
那些音色的假 CosyVoice —— 真的那个在音色不存在、或绑的不是这个模型时也是拒绝。
"""

from __future__ import annotations

import wave
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ai.providers import CosyVoiceSpeechAdapter, RemoteVoice, SpeechSynthesisError, VoiceEnrollmentError
from app.ai.providers import registry as provider_registry
from app.core.db import SessionLocal
from app.db.models import Asset, Job, ProviderUsageEvent, Voice, VoiceEnrollment
from app.domain.voices import remote
from app.domain.voices import voices as voices_domain
from app.media.paths import voice_dir, voice_key
from tests.util import add_provider, fresh_client, user_id, wait_status

COSY = "builtin:alibaba-cosyvoice"
MODEL = "cosyvoice-v3-flash"


class FakeBailian:
    """一个百炼账号。建音色免费、立刻返回 id;查第一次是 DEPLOYING,之后 OK(真机约 10 秒)。"""

    def __init__(self) -> None:
        self.voices: dict[str, str] = {}  # 远端音色 id → 绑的模型
        self.created: list[dict] = []
        self.deleted: list[str] = []
        self.spoken: list[tuple[str, str]] = []  # (模型, 音色)
        self.queried: dict[str, int] = {}
        self.fail_delete = False
        #: 建好之后立刻又没了(模拟「一年没用被删」一直发生):用来钉「只重建一次」。
        self.forget_on_create = False

    def create(self, *, target_model: str, prefix: str, reference: Path) -> str:
        assert reference.is_file(), "交上去的是本机那份参考音频"
        voice_id = f"{target_model}-{prefix}-{len(self.created):032x}"
        self.created.append({"target_model": target_model, "prefix": prefix})
        if not self.forget_on_create:
            self.voices[voice_id] = target_model
        return voice_id

    def query(self, voice_id: str) -> RemoteVoice:
        self.queried[voice_id] = self.queried.get(voice_id, 0) + 1
        status = "deploying" if self.queried[voice_id] == 1 else "ok"
        return RemoteVoice(voice_id=voice_id, status=status, raw_status=status.upper())

    def list(self, *, prefix: str) -> list[RemoteVoice]:
        return [RemoteVoice(voice_id=one, status="ok", target_model=model)
                for one, model in self.voices.items() if f"-{prefix}-" in one]

    def delete(self, voice_id: str) -> None:
        if self.fail_delete:
            raise VoiceEnrollmentError("providerErr_voiceEnrollFailed", detail="HTTP 401 · InvalidApiKey")
        self.deleted.append(voice_id)
        self.voices.pop(voice_id, None)


@pytest.fixture()
def bailian(monkeypatch) -> FakeBailian:
    fake = FakeBailian()
    monkeypatch.setitem(provider_registry.VOICE_ENROLLMENT_ADAPTERS, "alibaba-cosyvoice", lambda api_key, base_url="": fake)
    monkeypatch.setattr(remote, "POLL_SECONDS", 0)

    def synthesize(adapter, request, out_path: Path) -> None:
        if fake.voices.get(request.voice) != adapter._model:
            raise SpeechSynthesisError("providerErr_bailianTtsFailed", detail="HTTP 400 · voice not found")
        fake.spoken.append((adapter._model, request.voice))
        with wave.open(str(out_path), "wb") as handle:  # 一段真能探测的静音,素材登记要量时长
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(22050)
            handle.writeframes(b"\0\0" * 22050)

    monkeypatch.setattr(CosyVoiceSpeechAdapter, "synthesize", synthesize)
    return fake


def _setup(*, consent_kind: str = "self", model: str = MODEL) -> SimpleNamespace:
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        profile = add_provider(db, name="我的百炼", vendor="alibaba", base_url="", api_key="sk-test",
                               model=model, capability_ids=["tts"])
        voice = Voice(workspace_id=workspace_id, name="小美", reference_text="你好", consent_kind=consent_kind)
        db.add(voice)
        db.flush()
        folder = voice_dir(workspace_id, voice.id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "reference.wav").write_bytes(b"RIFFreference")
        voice.reference_key = voice_key(workspace_id, voice.id, "reference.wav")
        db.commit()
        return SimpleNamespace(client=client, workspace_id=workspace_id, profile_id=profile.id, voice_id=voice.id)


def _consent(env: SimpleNamespace) -> None:
    """确认框里点了同意:带着同意排一个复刻任务,等它做完。"""
    job = env.client.post(f"/api/voices/{env.voice_id}/remote-copies", json={"engine": COSY, "consent": True})
    assert job.status_code == 200, job.text
    assert wait_status(env.client, job.json()["id"]) == "succeeded"


def _synthesize(env: SimpleNamespace, **extra):
    return env.client.post("/api/tts/synthesize", json={
        "workspace_id": env.workspace_id, "text": "念一句", "engine": COSY, "voice_id": env.voice_id, **extra,
    })


def _copies(voice_id: str) -> list[VoiceEnrollment]:
    with SessionLocal() as db:
        return list(db.query(VoiceEnrollment).filter(VoiceEnrollment.voice_id == voice_id).order_by(VoiceEnrollment.created_at))


# ---------------- 上传之前要点头,而且后端说了算 ----------------


def test_没同意过_建任务之前就回409_带着传到哪(bailian) -> None:
    env = _setup()
    with SessionLocal() as db:
        jobs_before = db.query(Job).count()
    refused = _synthesize(env)
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "remote_voice_consent_required"
    assert (detail["voice_id"], detail["engine"], detail["provider_profile_id"], detail["model"]) == (
        env.voice_id, COSY, env.profile_id, MODEL,
    )
    assert detail["connection"] == "我的百炼" and "小美" in detail["message"]
    assert bailian.created == [], "没点头就什么都没传"
    with SessionLocal() as db:
        assert db.query(Job).count() == jobs_before, "没同意就不排任务"


def test_字幕配音_智能体音色设置也一样拦(bailian) -> None:
    """同意不是界面上的一道闸:每个把配音库的嗓子交给远端引擎的入口,后端自己问。"""
    env = _setup()
    sequence_id = _subtitled_sequence(env.client, env.workspace_id)
    dubbed = env.client.post(f"/api/sequences/{sequence_id}/dub-subtitles", json={"engine": COSY, "voice_id": env.voice_id})
    assert dubbed.status_code == 409 and dubbed.json()["detail"]["code"] == "remote_voice_consent_required", dubbed.text

    chosen = env.client.put("/api/settings/agent-voice", json={"engine": COSY, "voice_id": env.voice_id, "enabled": True})
    assert chosen.status_code == 409 and chosen.json()["detail"]["code"] == "remote_voice_consent_required", chosen.text

    # 绕开入口直接合成(智能体语音对话走的那一层):照样问,而不是悄悄传上去。
    with SessionLocal() as db, pytest.raises(remote.RemoteConsentRequired):
        voices_domain.speak_to_file(
            db, text="嗨", engine=COSY, engine_voice="", speed=1.0, workspace_id=env.workspace_id,
            user_id=user_id(), out_dir=Path("/nonexistent"), source_type="test", source_id="t", voice_id=env.voice_id,
        )
    assert bailian.created == []


def _subtitled_sequence(client, workspace_id: str) -> str:
    project = client.post("/api/projects", json={"workspace_id": workspace_id, "name": "P"}).json()
    sequence = client.post("/api/sequences", json={"workspace_id": workspace_id, "project_id": project["id"], "name": "S"}).json()
    tracks = client.post(f"/api/sequences/{sequence['id']}/tracks", json={"kind": "subtitle"}).json()
    track_id = next(one["id"] for one in tracks["tracks"] if one["kind"] == "subtitle")
    created = client.post(f"/api/sequences/{sequence['id']}/text-clips",
                          json={"track_id": track_id, "text": "第一句", "timeline_start": 0.0, "duration": 2.0})
    assert created.status_code == 200, created.text
    return sequence["id"]


def test_配音库的复刻到百炼_没带同意也先问_同意过的不再问(bailian) -> None:
    env = _setup()
    asked = env.client.post(f"/api/voices/{env.voice_id}/remote-copies", json={"engine": COSY})
    assert asked.status_code == 409 and asked.json()["detail"]["code"] == "remote_voice_consent_required", asked.text
    assert _copies(env.voice_id) == [] and bailian.created == []
    _consent(env)
    bailian.voices.clear()  # 被百炼删了:点「重新复刻」不用再同意一次
    again = env.client.post(f"/api/voices/{env.voice_id}/remote-copies", json={"engine": COSY})
    assert again.status_code == 200, again.text
    assert wait_status(env.client, again.json()["id"]) == "succeeded"
    assert len(bailian.created) == 2 and len(_copies(env.voice_id)) == 1


def test_同意之后复刻一份_配音直接用它_记一条免费的用量(bailian) -> None:
    env = _setup()
    _consent(env)
    [created] = bailian.created
    assert created == {"target_model": MODEL, "prefix": f"m{env.voice_id[:9]}"}, "前缀是 m + 嗓子 id 的前 9 位"
    [copy] = _copies(env.voice_id)
    assert (copy.status, copy.target_model, copy.provider_profile_id) == ("ok", MODEL, env.profile_id)
    assert copy.remote_voice_id in bailian.voices and copy.consented_at is not None

    with SessionLocal() as db:
        enroll = db.query(ProviderUsageEvent).filter(ProviderUsageEvent.operation == "enroll_voice").one()
        assert (enroll.capability, enroll.cost_confidence, enroll.cost_micros) == ("tts", "free", 0)
        assert (enroll.source_type, enroll.source_id, enroll.provider_profile_id) == ("voice", env.voice_id, env.profile_id)

    listed = env.client.get("/api/voices", params={"workspace_id": env.workspace_id}).json()
    [shown] = listed[0]["remote_copies"]
    assert (shown["engine"], shown["target_model"], shown["status"], shown["connection"]) == (COSY, MODEL, "ok", "我的百炼")

    job = _synthesize(env)
    assert job.status_code == 200, job.text
    assert wait_status(env.client, job.json()["id"]) == "succeeded"
    assert bailian.spoken == [(MODEL, copy.remote_voice_id)], "念的是那份副本"
    assert len(bailian.created) == 1, "已经有 ok 的副本,不再建"
    [copy] = _copies(env.voice_id)
    assert isinstance(copy.last_used_at, datetime), "合成成功记下最近一次用到的时间"
    with SessionLocal() as db:
        result = db.get(Job, job.json()["id"]).result
        asset = db.get(Asset, result["asset_id"])
        assert (asset.media_info or {}).get("voice_id") == env.voice_id, "和本机克隆一样记下是哪把嗓子的克隆"


def test_解析副本幂等_同一份不建第二个(bailian) -> None:
    env = _setup()
    _consent(env)
    account = _account(env)
    first = remote.ensure_copy(env.voice_id, account, model=MODEL)
    again = remote.ensure_copy(env.voice_id, account, model=MODEL)
    assert first == again and len(bailian.created) == 1


def _account(env: SimpleNamespace) -> remote.Account:
    from app.domain.voices.target import speech_target

    with SessionLocal() as db:
        profile, _model = speech_target(db, COSY, user_id=user_id())
        return remote.Account.of(COSY, profile, user_id())


# ---------------- 远端没了:标 missing,重建一次再念 ----------------


def test_副本被百炼删了_标missing重建一次再念_不再问(bailian) -> None:
    env = _setup()
    _consent(env)
    [before] = _copies(env.voice_id)
    bailian.voices.clear()  # 一年没被合成用过,百炼把它删了

    said: list[str] = []
    real_say = voices_domain._say_on_job

    def spy(job_id: str, key: str, **params) -> None:
        said.append(key)
        real_say(job_id, key, **params)

    import unittest.mock as mock

    with mock.patch.object(voices_domain, "_say_on_job", spy):
        job = _synthesize(env)
        assert job.status_code == 200, "同意过了,重建不再问"
        assert wait_status(env.client, job.json()["id"]) == "succeeded"
    assert len(bailian.created) == 2, "重建了一次"
    [after] = _copies(env.voice_id)
    assert after.id == before.id and after.status == "ok" and after.remote_voice_id != before.remote_voice_id
    assert bailian.spoken == [(MODEL, after.remote_voice_id)]
    assert "jobMsg_remoteVoiceEnrolling" in said, "任务进度说「正在百炼上复刻」"


def test_重建了还是念不出来_只重建一次就报错(bailian) -> None:
    env = _setup()
    _consent(env)
    bailian.voices.clear()
    bailian.forget_on_create = True  # 建好就又没了:每次合成都会失败
    job = _synthesize(env)
    assert wait_status(env.client, job.json()["id"]) == "failed"
    assert len(bailian.created) == 2, "第一次复刻 + 只重建一次,不是一直重建下去"


def test_念失败但副本还在_不重建_原样报错(bailian, monkeypatch) -> None:
    env = _setup()
    _consent(env)

    def busy(adapter, request, out_path):
        raise SpeechSynthesisError("providerErr_bailianTtsFailed", detail="HTTP 429 · Throttling")

    monkeypatch.setattr(CosyVoiceSpeechAdapter, "synthesize", busy)
    job = _synthesize(env)
    assert wait_status(env.client, job.json()["id"]) == "failed"
    assert len(bailian.created) == 1, "限流不是副本没了,不该重建"
    with SessionLocal() as db:
        assert "Throttling" in (db.get(Job, job.json()["id"]).error or "")


# ---------------- 没声明授权的不往外传 ----------------


def test_没声明是谁的嗓子_不复刻也不列(bailian) -> None:
    env = _setup(consent_kind="undeclared")
    refused = env.client.post(f"/api/voices/{env.voice_id}/remote-copies", json={"engine": COSY, "consent": True})
    assert refused.status_code == 422 and "声明" in refused.json()["detail"], refused.text
    synth = _synthesize(env)
    assert synth.status_code == 422, synth.text
    listed = env.client.get("/api/tts/voices", params={"engine": COSY, "workspace_id": env.workspace_id}).json()
    assert not [one for one in listed if one.get("cloned")], "下拉里不列没声明的嗓子"
    assert bailian.created == []


# ---------------- 换模型:建新副本、不动旧的 ----------------


def test_换了模型_按需建新副本_旧的不动_也不再问(bailian) -> None:
    env = _setup()
    _consent(env)
    [old] = _copies(env.voice_id)
    job = _synthesize(env, engine_model="cosyvoice-v2")
    assert job.status_code == 200, "同一个账号同意过,换模型不再问"
    assert wait_status(env.client, job.json()["id"]) == "succeeded"
    copies = {one.target_model: one for one in _copies(env.voice_id)}
    assert set(copies) == {MODEL, "cosyvoice-v2"}
    assert (copies[MODEL].id, copies[MODEL].remote_voice_id, copies[MODEL].status) == (old.id, old.remote_voice_id, "ok")
    assert bailian.spoken == [("cosyvoice-v2", copies["cosyvoice-v2"].remote_voice_id)]


# ---------------- 删嗓子 ----------------


def test_删嗓子_先删远端每一份_连没登记上的也按前缀清掉(bailian) -> None:
    env = _setup()
    _consent(env)
    orphan = f"{MODEL}-m{env.voice_id[:9]}-{'f' * 32}"
    bailian.voices[orphan] = MODEL  # 建到一半进程没了:远端有、本机没登记
    [copy] = _copies(env.voice_id)
    deleted = env.client.delete(f"/api/voices/{env.voice_id}")
    assert deleted.status_code == 200 and deleted.json() == {"remote_failures": []}, deleted.text
    assert set(bailian.deleted) == {copy.remote_voice_id, orphan}
    assert _copies(env.voice_id) == []


def test_删嗓子_远端删不掉的列出来_本机照删(bailian) -> None:
    env = _setup()
    _consent(env)
    [copy] = _copies(env.voice_id)
    bailian.fail_delete = True
    deleted = env.client.delete(f"/api/voices/{env.voice_id}")
    assert deleted.status_code == 200, deleted.text
    [failure] = deleted.json()["remote_failures"]
    assert (failure["connection"], failure["target_model"], failure["remote_voice_id"]) == ("我的百炼", MODEL, copy.remote_voice_id)
    assert "InvalidApiKey" in failure["reason"]
    with SessionLocal() as db:
        assert db.get(Voice, env.voice_id) is None, "本机这一行照删"
    assert _copies(env.voice_id) == []


# ---------------- 下拉、参数、重启 ----------------


def test_CosyVoice的音色下拉多一组克隆音色_要带工作区(bailian) -> None:
    env = _setup()
    plain = env.client.get("/api/tts/voices", params={"engine": COSY}).json()
    assert plain and not [one for one in plain if one.get("cloned")], "不带工作区只有系统音色"
    grouped = env.client.get("/api/tts/voices", params={"engine": COSY, "workspace_id": env.workspace_id}).json()
    assert grouped[-1] == {"value": env.voice_id, "label": "小美", "resource_id": "", "cloned": True}
    assert [one["value"] for one in grouped[:-1]] == [one["value"] for one in plain], "系统音色在前,克隆音色在后"
    edge = env.client.get("/api/tts/voices", params={"engine": "builtin:edge", "workspace_id": env.workspace_id}).json()
    assert not [one for one in edge if one.get("cloned")], "念不了克隆音色的引擎不列"


def test_工作流的配音说明_说克隆音色的名字_不说一串id(bailian) -> None:
    from app.domain.voices.engine_catalog import voice_note

    env = _setup()
    with SessionLocal() as db:
        note = voice_note(db, engine=COSY, voice=env.voice_id, workspace_id=env.workspace_id, user_id=user_id())
    assert "小美" in note and env.voice_id not in note, note


def test_一格音色是配音库里的嗓子时_交voice_id(bailian) -> None:
    from app.domain.voices.engine_catalog import synthesis_params

    env = _setup()
    with SessionLocal() as db:
        params = synthesis_params(db, engine=COSY, voice=env.voice_id, user_id=user_id(), workspace_id=env.workspace_id)
        assert params["voice_id"] == env.voice_id and "engine_voice" not in params
        stock = synthesis_params(db, engine=COSY, voice="longxiaochun_v3", user_id=user_id(), workspace_id=env.workspace_id)
        assert stock["engine_voice"] == "longxiaochun_v3" and "voice_id" not in stock


def test_重启时建到一半的副本记成失败_拿到id的接着等(bailian) -> None:
    env = _setup()
    with SessionLocal() as db:
        for model, remote_id in (("cosyvoice-v2", ""), (MODEL, "cosyvoice-v3-flash-m1-x")):
            db.add(VoiceEnrollment(voice_id=env.voice_id, engine="alibaba-cosyvoice", provider_profile_id=env.profile_id,
                                   owner_user_id=user_id(), target_model=model, remote_voice_id=remote_id,
                                   status="deploying"))
        db.commit()
        assert remote.reconcile_orphaned_enrollments(db) == 1
        db.commit()
    statuses = {one.target_model: one.status for one in _copies(env.voice_id)}
    assert statuses == {"cosyvoice-v2": "failed", MODEL: "deploying"}
