from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.db import Base, engine, init_db
from app.main import app
from tests.util import fresh_client


def reset() -> TestClient:
    return fresh_client()


def make_asset(client: TestClient) -> dict:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    return client.post(
        "/api/assets",
        json={
            "workspace_id": ws["id"],
            "project_id": project["id"],
            "kind": "video",
            "name": "Talk",
            "file_key": "media/talk.mp4",
            "media_info": {"duration": 20},
        },
    ).json()


SEGMENTS = [
    {
        "start_time": 0.0,
        "end_time": 2.4,
        "text": "大家好，欢迎回来。",
        "speaker": "S1",
        "tokens": [
            {"start_time": 0.0, "end_time": 0.6, "text": "大家"},
            {"start_time": 0.6, "end_time": 1.0, "text": "好"},
            {"start_time": 1.2, "end_time": 2.4, "text": "欢迎回来"},
        ],
    },
    {"start_time": 2.8, "end_time": 5.0, "text": "今天讲时间线内核。", "speaker": "S1", "tokens": []},
]


def test_attach_and_get_transcript() -> None:
    client = reset()
    asset = make_asset(client)

    res = client.put(f"/api/assets/{asset['id']}/transcript", json={"language": "zh", "segments": SEGMENTS})
    assert res.status_code == 200
    transcript = res.json()
    assert transcript["language"] == "zh"
    assert len(transcript["segments"]) == 2
    assert transcript["segments"][0]["tokens"][2]["text"] == "欢迎回来"

    fetched = client.get(f"/api/assets/{asset['id']}/transcript").json()
    assert fetched["id"] == transcript["id"]


def test_reattach_replaces_previous_transcript() -> None:
    client = reset()
    asset = make_asset(client)
    client.put(f"/api/assets/{asset['id']}/transcript", json={"language": "zh", "segments": SEGMENTS})
    client.put(
        f"/api/assets/{asset['id']}/transcript",
        json={"language": "en", "segments": [{"start_time": 0, "end_time": 1, "text": "Hi.", "tokens": []}]},
    )
    fetched = client.get(f"/api/assets/{asset['id']}/transcript").json()
    assert fetched["language"] == "en"
    assert len(fetched["segments"]) == 1


def test_attach_validation_and_missing() -> None:
    client = reset()
    asset = make_asset(client)
    bad = client.put(
        f"/api/assets/{asset['id']}/transcript",
        json={"segments": [{"start_time": 2, "end_time": 2, "text": "x", "tokens": []}]},
    )
    assert bad.status_code == 422

    missing_asset = client.put("/api/assets/nope/transcript", json={"segments": []})
    assert missing_asset.status_code == 404

    no_transcript = client.get(f"/api/assets/{asset['id']}/transcript")
    assert no_transcript.status_code == 404
