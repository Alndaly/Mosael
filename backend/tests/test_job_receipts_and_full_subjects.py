"""后台任务的回执与标题:直接工具建的 job 也要寄回执,payload.subject 要存完整原文。

两条真机上的缺口:

1. 确认卡那条路会把回执挂在执行体外面(`confirmations._execute` 的 `set_receipt`),而
   `transcribe_asset` / `import_media_from_url` 这类**直接写工具**不经过卡,只设了 `calling_as`。
   于是它们建出来的任务没有 `payload.receipt`:干完了没人知道,也不能按对话归属(「本对话的后台任务」里看不到)。
2. `payload.subject` 在建任务处被静默切到 80 字,而界面上一笔已经把回执/任务卡改成 `Truncate` 了 ——
   源头只存了半句,界面再裁也回不到全文。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import AgentSession, Job, User
from app.domain import jobs as jobs_domain
from app.domain.agent import host
from app.domain.assets import from_url
from app.domain.voices import voices
from app.domain.voices.voice_ref import VoiceRef
from tests.util import fresh_client, insert_asset


def _chat() -> tuple:
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    session_id = client.post(
        "/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": workspace_id, "title": "T"}
    ).json()["id"]
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "tester").one()
        token = mint_service_session(db, user.id, agent_session_id=session_id)
    return client, workspace_id, session_id, token


def _workspace() -> tuple:
    """一条干净的库 + 一个工作区 + 它的主人。"""
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "tester").one()
        return client, workspace_id, user.id


def test_直接工具建的job带着会话回执_出现在jobs里_终态送回执(monkeypatch) -> None:
    """`transcribe_asset` 不经过确认卡,它建出来的任务仍要归属到这次对话并在终态寄回执。"""
    client, workspace_id, session_id, token = _chat()
    asset_id = insert_asset(workspace_id, kind="audio", name="一段录音.mp3", file_key="media/voice.mp3")
    from app.domain.voices import transcription

    #: 只验建任务这一刻的归属,不真去跑转写(它要引擎和文件)。
    monkeypatch.setattr(transcription, "dispatch_job", lambda *args, **kwargs: True)

    response = client.post(
        "/api/agent/tools/transcribe_asset",
        json={"arguments": {"asset_id": asset_id}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    job = response.json()["result"]
    assert job["payload"]["receipt"] == {"kind": "agent_session", "session_id": session_id}

    #: 任务中心/「本对话的后台任务」读的是 /api/jobs 的 payload —— receipt 必须从那里带得出来。
    listed = client.get(f"/api/jobs?workspace_id={workspace_id}").json()
    row = next(one for one in listed if one["id"] == job["id"])
    assert row["payload"]["receipt"]["session_id"] == session_id

    #: 断开之后它跑完了:既有 receipts.deliver 那条路要把回执送回这次对话。
    with SessionLocal() as db:
        db.get(AgentSession, session_id).status = "running"  # 会话正忙 → 落成待送回执,不在这条测试里起一轮
        settling = db.get(Job, job["id"])
        settling.status = "failed"
        settling.error = "转写引擎没装"
        db.commit()

    messages = client.get(f"/api/agent/sessions/{session_id}/messages").json()
    receipts = [one for one in messages if one["role"] == host.JOB_RECEIPT_ROLE]
    assert [one["payload"]["job_id"] for one in receipts] == [job["id"]], "终态回执没送回来"


def test_读工具不凭空产生回执() -> None:
    """`list_generation_models` 一个任务都不建:不能因为这次调用有会话就多出一条回执。"""
    client, workspace_id, _session_id, token = _chat()
    before = client.get(f"/api/jobs?workspace_id={workspace_id}").json()

    response = client.post(
        "/api/agent/tools/list_generation_models",
        json={"arguments": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert client.get(f"/api/jobs?workspace_id={workspace_id}").json() == before


def test_一次调用建出的每个job都归属到这次会话(monkeypatch) -> None:
    """回执挂在调用上,不挂在「返回的那一个」上:调用期间建几个 job,几个都带同一份回执。"""
    from app.core.unit_of_work import unit_of_work

    import mcp_server

    client, workspace_id, session_id, token = _chat()
    created: list[str] = []

    def two_jobs() -> dict:
        with unit_of_work() as db:
            for _ in range(2):
                job = jobs_domain.create_job(
                    db, workspace_id=workspace_id, kind="export", payload={"subject": "x"},
                    created_by=mcp_server._CALLER_ID.get(),
                )
                created.append(job.id)
        return {"queued": len(created)}

    monkeypatch.setattr(mcp_server, "REGISTERED_TOOLS", mcp_server.REGISTERED_TOOLS | {"test_two_jobs"})
    monkeypatch.setattr(mcp_server, "test_two_jobs", two_jobs, raising=False)
    response = client.post(
        "/api/agent/tools/test_two_jobs",
        json={"arguments": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text

    listed = {one["id"]: one for one in client.get(f"/api/jobs?workspace_id={workspace_id}").json()}
    assert [listed[job_id]["payload"]["receipt"]["session_id"] for job_id in created] == [session_id] * 2


def _long_prompt() -> str:
    return "一只在雨里等车的柴犬," * 24


def test_列任务的模型简报截subject时带省略号() -> None:
    """给模型看的列表有长度上限,但截了要说 —— 完整原文在 get_job 的 payload 里。"""
    import mcp_server

    subject = _long_prompt()
    brief = mcp_server._job_brief({
        "id": "j", "kind": "workflow", "status": "succeeded", "progress": 0,
        "payload": {"subject": subject}, "result": {},
    })
    assert brief["subject"].endswith("…"), "静默切一半,模型以为那就是全部"
    assert brief["subject"][:-1] == subject[:119].rstrip()

    short = mcp_server._job_brief({
        "id": "j", "kind": "workflow", "status": "succeeded", "progress": 0,
        "payload": {"subject": "出海流程"}, "result": {},
    })
    assert short["subject"] == "出海流程"


def test_生成任务的subject存完整提示词(monkeypatch) -> None:
    """>80 字的提示词,`payload.subject` 不该只剩前 80 字。"""
    from tests.test_entity_generation_paths import _seedance

    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    profile_id = _seedance(client)
    #: 不真的去跑生成:这里只看建任务时写下的载荷。
    monkeypatch.setattr(
        jobs_domain, "_EXECUTION_MODES", {**jobs_domain._EXECUTION_MODES, "ai_generation": "external"}
    )
    prompt = _long_prompt()
    assert len(prompt) > 80

    response = client.post("/api/generation/jobs", json={
        "workspace_id": workspace_id, "provider_profile_id": profile_id, "provider": "bytedance",
        "model": "doubao-seedance-2-0-260128", "kind": "video", "prompt": prompt,
    })
    assert response.status_code == 200, response.text
    assert response.json()["job"]["payload"]["subject"] == prompt


def test_tts的subject存完整文本(monkeypatch) -> None:
    _client, workspace_id, user_id = _workspace()
    text = _long_prompt()
    monkeypatch.setattr(voices, "dispatch_job", lambda *args, **kwargs: True)
    with SessionLocal() as db:
        job = voices.start_synthesis(
            db, text=text, project_id=None, created_by=user_id, workspace_id=workspace_id,
            voice=VoiceRef("builtin:edge", voice="zh-CN-XiaoxiaoNeural"),
        )
        db.commit()
        assert job.payload["subject"] == text


def test_podcast的subject存完整材料(monkeypatch) -> None:
    _client, workspace_id, user_id = _workspace()
    text = _long_prompt()
    monkeypatch.setattr(voices, "dispatch_job", lambda *args, **kwargs: True)
    with SessionLocal() as db:
        job = voices.start_podcast(
            db, workspace_id=workspace_id, project_id=None, created_by=user_id, text=text, mode="summarize",
        )
        db.commit()
        assert job.payload["subject"] == text


def test_链接导入的subject存完整标题(monkeypatch) -> None:
    _client, workspace_id, user_id = _workspace()
    title = _long_prompt()
    monkeypatch.setattr(from_url, "ensure_public_link", lambda url: None)
    monkeypatch.setattr(from_url, "dispatch_job", lambda *args, **kwargs: True)
    with SessionLocal() as db:
        job = from_url.start_url_import(
            db, workspace_id=workspace_id, project_id=None,
            items=[{"url": "https://example.com/video", "title": title}], kind="video", created_by=user_id,
        )
        db.commit()
        assert job.payload["subject"] == title
