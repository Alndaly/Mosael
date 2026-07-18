from __future__ import annotations

import io
import time
import wave

from tests.util import fresh_client


def _tiny_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000)  # 1s silence
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


def test_tts_models_listed() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    rows = client.get("/api/tts/models").json()
    assert {r["id"] for r in rows} == {"f5-tts", "fish-speech"}
