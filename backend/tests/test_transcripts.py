from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.db.models import Job
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


def test_find_existing_transcript_by_legacy_url_import_job() -> None:
    """扩展生成后重开侧栏，应复用既有逐字稿，不能再次要求下载和转写。"""
    client = reset()
    asset = make_asset(client)
    client.put(f"/api/assets/{asset['id']}/transcript", json={"language": "zh", "segments": SEGMENTS})
    with SessionLocal() as db:
        db.add(Job(
            workspace_id=asset["workspace_id"],
            kind="url_import",
            status="succeeded",
            payload={
                "items": [{
                    "url": "https://www.pornhub.com/view_video.php?viewkey=abc123&utm_source=test",
                    "title": "A video",
                }],
            },
            result={"asset_ids": [asset["id"]]},
        ))
        db.commit()

    response = client.get(
        "/api/assets/transcript-by-source",
        params={
            "workspace_id": asset["workspace_id"],
            "url": "https://cn.pornhub.com/view_video.php?viewkey=abc123",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["asset_id"] == asset["id"]
    assert response.json()["segments"][0]["text"] == SEGMENTS[0]["text"]


def test_find_existing_transcript_by_remembered_source_url() -> None:
    client = reset()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    asset = client.post(
        "/api/assets",
        json={
            "workspace_id": workspace["id"],
            "kind": "video",
            "source": "downloaded",
            "name": "Talk",
            "file_key": "media/talk.mp4",
            "media_info": {
                "source_url": "https://www.youtube.com/watch?v=abc123&utm_source=old",
                "source_url_key": "youtube:abc123",
            },
        },
    ).json()
    client.put(f"/api/assets/{asset['id']}/transcript", json={"language": "zh", "segments": SEGMENTS})

    response = client.get(
        "/api/assets/transcript-by-source",
        params={"workspace_id": workspace["id"], "url": "https://youtu.be/abc123?t=5"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["asset_id"] == asset["id"]
