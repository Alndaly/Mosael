from __future__ import annotations

import io
import time
import wave

from tests.util import fresh_client


def _tiny_wav(seconds: int = 1) -> bytes:
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

    # Synthesize → job → succeeds with an audio asset (placeholder engine here).
    job = client.post(f"/api/voices/{voice['id']}/synthesize", json={"text": "这是一段测试配音。"}).json()
    for _ in range(60):
        state = client.get(f"/api/jobs/{job['id']}").json()
        if state["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.2)
    assert state["status"] == "succeeded", state
    asset_id = state["result"]["asset_id"]
    asset = next(a for a in client.get(f"/api/assets?workspace_id={ws['id']}").json() if a["id"] == asset_id)
    assert asset["kind"] == "audio"

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
        json={"engine": "fish-speech", "python_path": "/tmp/py", "source": "modelscope"},
    ).json()
    assert saved["engine"] == "fish-speech" and saved["source"] == "modelscope"
    assert tts_config.get().engine == "fish-speech"  # cache refreshed
    # invalid engine rejected
    assert client.put("/api/settings/tts", json={"engine": "nope", "source": "hf"}).status_code == 422
