from __future__ import annotations

import io
import time
import wave

from tests.util import add_provider, fresh_client


#: 8 秒:够得着参考音频的下限(见 voices.REFERENCE_MIN_SECONDS)。此前这里是 1 秒,
#: 而那正是用户那条 2.6 秒音色的同类 —— 测试用的夹具比真实要求还宽,下限就测不出来。
def _tiny_wav(seconds: int = 8) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000 * seconds)
    return buf.getvalue()


def test_voice_upload_list_synthesize_delete() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    # Upload a reference sample → creates a voice.
    resp = client.post(
        "/api/voices/upload",
        data={"workspace_id": ws["id"], "name": "小明", "reference_text": "你好世界"},
        files={"file": ("ref.wav", _tiny_wav(), "audio/wav")},
    )
    assert resp.status_code == 200, resp.text
    voice = resp.json()
    assert voice["name"] == "小明" and voice["reference_text"] == "你好世界"

    # It lists.
    voices = client.get(f"/api/voices?workspace_id={ws['id']}").json()
    assert [v["id"] for v in voices] == [voice["id"]]

    # Sample serves.
    sample = client.get(f"/api/voices/{voice['id']}/sample")
    assert sample.status_code == 200 and sample.headers["content-type"] == "audio/wav"

    # 合成:这台机器上没装本地引擎,于是它**当场拒绝**,而不是起一个任务、发一段占位音。
    # (装上引擎后走的是同一个接口,区别只在这一句能不能过。)
    refused = client.post(f"/api/voices/{voice['id']}/synthesize", json={"text": "这是一段测试配音。"})
    assert refused.status_code == 422, refused.text
    assert "引擎" in refused.json()["detail"]

    # Delete.
    assert client.delete(f"/api/voices/{voice['id']}").status_code == 204
    assert client.get(f"/api/voices?workspace_id={ws['id']}").json() == []


def test_voice_from_transcribed_speaker() -> None:
    from app.core.db import SessionLocal
    from app.domain.transcripts.operations import SegmentIn, attach_transcript

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    proj = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"], "project_id": proj["id"]},
        files={"file": ("clip.wav", _tiny_wav(3), "audio/wav")},
    ).json()

    with SessionLocal() as db:
        attach_transcript(
            db,
            asset_id=asset["id"],
            language="zh",
            segments=[
                SegmentIn(start_time=0.0, end_time=1.0, text="你好世界", speaker="SPEAKER_00", tokens=()),
                SegmentIn(start_time=1.0, end_time=2.0, text="欢迎收看", speaker="SPEAKER_00", tokens=()),
            ],
            source="test",
        )

    voice = client.post(
        "/api/voices/from-speaker",
        json={"asset_id": asset["id"], "speaker": "SPEAKER_00", "name": "甲"},
    ).json()
    assert voice["name"] == "甲"
    assert voice["source"] == "speaker"
    assert "你好世界" in voice["reference_text"]


def test_tts_models_listed() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    rows = client.get("/api/tts/models").json()
    assert {r["id"] for r in rows} == {"f5-tts", "fish-speech"}


def test_tts_config_get_and_update() -> None:
    from app.domain import tts_config

    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    got = client.get("/api/settings/tts").json()
    assert got["engine"] == "f5-tts" and got["source"] == "hf-mirror"
    assert "worker_ready" in got

    saved = client.put(
        "/api/settings/tts",
        json={
            "engine": "fish-speech",
            "python_path": "/tmp/py",
            "source": "modelscope",
            "fish_repo_dir": "/tmp/fish-speech",
            "fish_model_dir": "/tmp/s2-pro",
        },
    ).json()
    assert saved["engine"] == "fish-speech" and saved["source"] == "modelscope"
    assert saved["fish_repo_dir"] == "/tmp/fish-speech" and saved["fish_model_dir"] == "/tmp/s2-pro"
    assert tts_config.get().engine == "fish-speech"  # cache refreshed
    assert tts_config.get().fish_repo_dir == "/tmp/fish-speech"
    # invalid engine rejected
    assert client.put("/api/settings/tts", json={"engine": "nope", "source": "hf"}).status_code == 422


def test_engine_list_marks_which_engines_need_a_typed_voice_id() -> None:
    """The panel renders a dropdown or a text field off these two flags, so they are contract."""
    client = fresh_client()
    engines = {item["id"]: item for item in client.get("/api/tts/engines").json()}

    assert engines["clone"]["needs_key"] is False
    # openai-tts 与 openai-compatible-tts 已并成一个 "openai":前者拆分是"能力要分开"的
    # 产物(能力现在挂模型行),后者存在的唯一理由是"要填自定义 endpoint",而档案本来就有
    # base_url 字段。旧 id 仍能被解析(REMOTE_ENGINES 里留作只读别名),但不再出现在列表里。
    assert engines["openai"]["needs_voice_id"] is False and engines["openai"]["voices"]
    assert "openai-tts" not in engines and "openai-compatible-tts" not in engines
    # 火山's catalogue is account-specific, but /api/tts/voices always answers with a list —
    # live when AK/SK are configured, built-in otherwise — so the panel offers a dropdown
    # rather than asking the user to type an opaque id.
    assert engines["volcano"]["needs_voice_id"] is False and engines["volcano"]["voices"]


def test_自建兼容端点的_base_url_能走到引擎() -> None:
    """A user pointing an OpenAI-compatible TTS profile at a proxy must not have the request
    sent to api.openai.com with a key that is not valid there — a 401 whose cause is invisible."""
    import time

    import app.audio.tts as providers
    from app.core.db import SessionLocal
    from app.db.models import ProviderProfile

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        add_provider(
            db,
            name="proxy",
            vendor="openai",
            api_key="k",
            base_url="https://proxy.test/v1",
            model="custom-tts",
        )
        db.commit()

    seen: dict = {}

    def spy(engine, api_key, voice="", model="", base_url=""):
        seen.update(engine=engine, api_key=api_key, model=model, base_url=base_url)
        raise RuntimeError("no network in tests — the constructor arguments are what this asserts")

    saved = providers.build_remote_provider
    providers.build_remote_provider = spy
    try:
        res = client.post(
            "/api/tts/synthesize",
            json={
                "workspace_id": workspace_id,
                "text": "hello",
                "engine": "openai",
                "engine_voice": "alloy",
            },
        )
        assert res.status_code == 200, res.text
        # Synthesis runs on a job thread; wait for it rather than racing it.
        deadline = time.time() + 5
        while not seen and time.time() < deadline:
            time.sleep(0.02)
    finally:
        providers.build_remote_provider = saved

    assert seen.get("base_url") == "https://proxy.test/v1", seen
    assert seen.get("api_key") == "k"
    assert seen.get("model") == "custom-tts"


def test_the_voice_resource_survives_the_hand_off_to_the_job_thread() -> None:
    """火山 needs the voice's family in a synthesis header, and it travels from the request
    through three functions that pass their arguments positionally. Adding a parameter to one
    of them is silent until synthesis fails with an opaque 55000000 — so pin the whole path."""
    import time

    import app.audio.tts as providers
    from app.core.db import SessionLocal
    from app.db.models import ProviderProfile

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        add_provider(db, name="v", vendor="volcano", api_key="k")
        db.commit()

    seen: dict = {}

    def spy(engine, api_key, voice="", model="", base_url=""):
        seen.update(voice=voice, model=model)
        raise RuntimeError("no network in tests")

    saved = providers.build_remote_provider
    providers.build_remote_provider = spy
    try:
        res = client.post(
            "/api/tts/synthesize",
            json={
                "workspace_id": workspace_id,
                "text": "你好",
                "engine": "volcano",
                "engine_voice": "zh_male_custom_bigtts",
                "engine_voice_resource": "seed-icl-2.0",
            },
        )
        assert res.status_code == 200, res.text
        deadline = time.time() + 5
        while not seen and time.time() < deadline:
            time.sleep(0.02)
    finally:
        providers.build_remote_provider = saved

    assert seen.get("voice") == "zh_male_custom_bigtts", seen
    assert seen.get("model") == "seed-icl-2.0", seen
