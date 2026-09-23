"""建了任务的请求,响应头上说一声 —— 前端据此立刻刷新任务中心。

此前只有少数几个按钮记得自己去刷新,其余的(人声分离、转写、导出……)要等任务中心下一轮
轮询:空闲时 8 秒一次。用户看到的是「点了开始,好几秒后任务才进队列」。
"""
from __future__ import annotations

from app.api.middleware import NEW_JOBS_HEADER
from tests.util import fresh_client


def _no_threads(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # 只看「建没建任务」,不真跑转写。
    monkeypatch.setattr("app.domain.voices.transcription._run_transcription", lambda job_id, asset_id: None)


def test_a_request_that_creates_a_job_says_so(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _no_threads(monkeypatch)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    created = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "kind": "video", "name": "S",
              "file_key": "media/s.mp4", "media_info": {"duration": 10}},
    )
    # 建素材不是建任务 —— 不该让任务中心白刷一次。
    assert NEW_JOBS_HEADER not in created.headers

    res = client.post(f"/api/assets/{created.json()['id']}/transcribe?engine=whisperx")
    assert res.status_code == 200
    assert res.headers[NEW_JOBS_HEADER] == "1"
    # 下一个请求重新开始计:上一次的记录不会串过来。
    assert NEW_JOBS_HEADER not in client.get(f"/api/jobs?workspace_id={ws['id']}").headers


def test_the_frontend_origin_can_read_the_header(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # 前端在 5173(开发)或 file://(打包)上,对后端都是跨源 —— 不点名放行,页面读不到这个头。
    _no_threads(monkeypatch)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "kind": "video", "name": "S",
              "file_key": "media/s.mp4", "media_info": {"duration": 10}},
    ).json()
    res = client.post(
        f"/api/assets/{asset['id']}/transcribe?engine=whisperx",
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    exposed = res.headers.get("access-control-expose-headers", "").lower()
    assert NEW_JOBS_HEADER.lower() in exposed
