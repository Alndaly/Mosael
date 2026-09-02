from __future__ import annotations

import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from tests.util import fresh_client


def setup_sequence(client: TestClient) -> tuple[dict, dict, dict, dict]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "project_id": project["id"], "kind": "video", "name": "Src",
              "file_key": "media/src.mp4", "media_info": {"duration": 10}},
    ).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"},
    ).json()
    return ws, project, asset, sequence


def video_clips(sequence: dict) -> list[dict]:
    return next(t for t in sequence["tracks"] if t["kind"] == "video")["clips"]


def wait_job(client: TestClient, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    job = client.get(f"/api/jobs/{job_id}").json()
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.05)
    return job


def test_edit_timeline_requires_approval_then_executes() -> None:
    client = fresh_client()
    ws, _, asset, sequence = setup_sequence(client)
    track = next(t for t in sequence["tracks"] if t["kind"] == "video")

    confirmation = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "edit_timeline",
            "requested_by": "pi",
            "payload": {
                "sequence_id": sequence["id"],
                "operations": [
                    {"kind": "insert_clip", "track_id": track["id"], "asset_id": asset["id"],
                     "timeline_start": 0, "src_in": 0, "src_out": 5},
                    {"kind": "add_track", "track_kind": "video"},
                ],
            },
        },
    )
    assert confirmation.status_code == 200, confirmation.text
    data = confirmation.json()
    assert data["status"] == "pending"
    assert data["permission"] == "edit"
    assert "2 个时间线操作" in data["summary"]

    # Nothing applied while pending.
    state = client.get(f"/api/sequences/{sequence['id']}").json()
    assert video_clips(state) == []

    approved = client.post(f"/api/confirmations/{data['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    assert approved["result"]["applied_operations"] == 2

    state = client.get(f"/api/sequences/{sequence['id']}").json()
    assert len(video_clips(state)) == 1
    assert "V2" in [t["name"] for t in state["tracks"]]
    # AI edits stay undoable (plan §10.2).
    assert state["can_undo"] is True


def test_edit_workflow_applies_granular_ops() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "WF"}).json()
    assert [n["type"] for n in workflow["graph"]["nodes"]] == ["start"]

    confirmation = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "edit_workflow",
            "requested_by": "pi",
            "payload": {
                "workflow_id": workflow["id"],
                "operations": [
                    {"kind": "add_node", "type": "llm", "node_id": "llm_1", "config": {"prompt": "hi {{start.q}}"}},
                    {"kind": "connect", "source": "start", "target": "llm_1"},
                ],
            },
        },
    )
    assert confirmation.status_code == 200, confirmation.text
    data = confirmation.json()
    assert data["status"] == "pending"
    assert "2 个工作流编辑" in data["summary"]

    # Nothing applied while pending.
    current = client.get(f"/api/workflows/{workflow['id']}").json()
    assert [n["type"] for n in current["graph"]["nodes"]] == ["start"]

    approved = client.post(f"/api/confirmations/{data['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")

    after = client.get(f"/api/workflows/{workflow['id']}").json()
    types = sorted(n["type"] for n in after["graph"]["nodes"])
    assert types == ["llm", "start"]
    assert any(e["source"] == "start" and e["target"] == "llm_1" for e in after["graph"]["edges"])


def test_edit_workflow_rejects_bad_ops() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "WF"}).json()
    # Connecting to a node that doesn't exist must fail fast at request time.
    bad = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "edit_workflow",
            "requested_by": "pi",
            "payload": {"workflow_id": workflow["id"], "operations": [{"kind": "connect", "source": "start", "target": "ghost"}]},
        },
    )
    assert bad.status_code == 422, bad.text
    assert "ghost" in bad.text or "不存在" in bad.text


def test_edit_workflow_clear_can_delete_start_and_create_confirmation() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "WF"}).json()
    add = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "edit_workflow",
            "requested_by": "pi",
            "payload": {
                "workflow_id": workflow["id"],
                "operations": [
                    {"kind": "add_node", "type": "llm", "node_id": "llm_1", "config": {"prompt": "hi"}},
                    {"kind": "connect", "source": "start", "target": "llm_1"},
                ],
            },
        },
    ).json()
    client.post(f"/api/confirmations/{add['id']}/approve")

    clear = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "edit_workflow",
            "requested_by": "pi",
            "payload": {
                "workflow_id": workflow["id"],
                "operations": [
                    {"kind": "remove_node", "node_id": "start"},
                    {"kind": "remove_node", "node_id": "llm_1"},
                ],
            },
        },
    )

    assert clear.status_code == 200, clear.text
    data = clear.json()
    assert data["status"] == "pending"
    assert data["payload"]["operations"] == [
        {"kind": "remove_node", "node_id": "start"},
        {"kind": "remove_node", "node_id": "llm_1"},
    ]
    assert "2 个工作流编辑" in data["summary"]

    approved = client.post(f"/api/confirmations/{data['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    after = client.get(f"/api/workflows/{workflow['id']}").json()
    assert after["graph"]["nodes"] == []
    assert after["graph"]["edges"] == []


def test_edit_workflow_can_delete_only_start() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "WF"}).json()

    res = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "edit_workflow",
            "requested_by": "pi",
            "payload": {
                "workflow_id": workflow["id"],
                "operations": [{"kind": "remove_node", "node_id": "start"}],
            },
        },
    )

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "pending"
    approved = client.post(f"/api/confirmations/{data['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    after = client.get(f"/api/workflows/{workflow['id']}").json()
    assert after["graph"]["nodes"] == []


def test_reject_leaves_timeline_untouched() -> None:
    client = fresh_client()
    ws, _, asset, sequence = setup_sequence(client)
    track = next(t for t in sequence["tracks"] if t["kind"] == "video")
    data = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "edit_timeline",
            "payload": {
                "sequence_id": sequence["id"],
                "operations": [{"kind": "insert_clip", "track_id": track["id"], "asset_id": asset["id"],
                                "timeline_start": 0, "src_in": 0, "src_out": 5}],
            },
        },
    ).json()
    rejected = client.post(f"/api/confirmations/{data['id']}/reject").json()
    assert rejected["status"] == "rejected"
    state = client.get(f"/api/sequences/{sequence['id']}").json()
    assert video_clips(state) == []
    # A resolved confirmation cannot be approved afterwards.
    assert client.post(f"/api/confirmations/{data['id']}/approve").status_code == 409


def test_generate_image_confirmation_carries_ai_cost_permission(monkeypatch) -> None:
    monkeypatch.setattr("app.domain.generation.runner.start_generation_thread", lambda _generation_id: None)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    # 生成任务现在按"用户配了哪条连接"校验(内置目录表已退场),所以先配一条。
    profile = client.post(
        "/api/settings/providers",
        json={"name": "百炼", "vendor": "alibaba", "config": {"api_key": "k"}},
    ).json()
    client.post(
        f"/api/settings/providers/{profile['id']}/models",
        json={"model_id": "qwen-image", "enabled": True, "capability_ids": ["image"]},
    )
    data = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "generate_image",
            "payload": {"prompt": "a lighthouse at dawn", "provider": "alibaba", "model": "qwen-image",
                        "parameters": {"size": "1024x1024"}},
        },
    ).json()
    assert data["permission"] == "ai-cost"
    approved = client.post(f"/api/confirmations/{data['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    assert approved["result"]["job_id"]
    job = client.get(f"/api/jobs/{approved['result']['job_id']}").json()
    assert job["status"] == "queued"


def test_generate_audio_confirmation_uses_tts_default(monkeypatch) -> None:
    captured: dict = {}

    def fake_start_synthesis(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="tts-job-1")

    monkeypatch.setattr("app.domain.voices.voices.start_synthesis", lambda _db, **kwargs: fake_start_synthesis(**kwargs))
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    profile = client.post(
        "/api/settings/providers",
        json={"name": "Speech", "vendor": "openai", "config": {"api_key": "sk-tts", "default_model": "tts-model"}},
    ).json()
    client.put(
        "/api/settings/provider-defaults/tts",
        json={"provider_profile_id": profile["id"], "model": "tts-model"},
    )
    data = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "generate_audio",
            "payload": {"text": "旁白测试", "voice": "nova"},
        },
    ).json()
    assert data["permission"] == "ai-cost"
    approved = client.post(f"/api/confirmations/{data['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    assert approved["result"]["job_id"] == "tts-job-1"
    assert captured["engine"] == "openai"  # 语音引擎 id 已并成 openai
    assert captured["provider_profile_id"] == profile["id"]
    assert captured["engine_model"] == "tts-model"
    assert captured["engine_voice"] == "nova"


def test_invalid_payloads_rejected() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    unknown = client.post(
        "/api/confirmations", json={"workspace_id": ws["id"], "tool": "drop_database", "payload": {}}
    )
    assert unknown.status_code == 422
    bad_seq = client.post(
        "/api/confirmations",
        json={"workspace_id": ws["id"], "tool": "render_sequence", "payload": {"sequence_id": "nope"}},
    )
    assert bad_seq.status_code == 422
    empty_ops = client.post(
        "/api/confirmations",
        json={"workspace_id": ws["id"], "tool": "edit_timeline", "payload": {"sequence_id": "nope", "operations": []}},
    )
    assert empty_ops.status_code == 422


def test_confirmations_scoped_by_session() -> None:
    """确认卡按发起会话归属,列表能据此筛。

    此前只有 workspace_id:同工作区任何来源的待确认都会被每个对话的内联确认卡拉到,
    而内联卡的「本会话始终允许」会自动批准它们 —— 用户以为授的是「这次对话」,
    实际授的是「这个工作区里所有人的这个工具」。

    归属**由凭据决定**:一次 turn 一个令牌,铸的时候就写上是哪次对话(见
    tests/test_confirmation_session_ownership.py)。这里造卡因此要换令牌,而不是在请求体里填。
    """
    from app.core.db import SessionLocal
    from app.core.security import mint_service_session
    from app.db.models import User

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    login_token = client.headers["Authorization"]
    # 用 browser_open:它不校验外部实体,测的是归属与筛选本身,不牵扯时间线。
    base = {"workspace_id": ws["id"], "tool": "browser_open", "payload": {"url": "https://example.com"}}

    def card_as(agent_session_id: str | None) -> dict:
        if agent_session_id is None:
            client.headers["Authorization"] = login_token  # 登录令牌 = 没有会话的外部智能体
        else:
            with SessionLocal() as db:
                user = db.query(User).filter(User.username == "tester").one()
                token = mint_service_session(db, user.id, agent_session_id=agent_session_id)
            client.headers["Authorization"] = f"Bearer {token}"
        return client.post("/api/confirmations", json=base).json()

    a = card_as("sess-a")
    b = card_as("sess-b")
    ext = card_as(None)  # 外部智能体:没有会话
    client.headers["Authorization"] = login_token

    assert a["session_id"] == "sess-a"
    assert ext["session_id"] is None

    def ids(**params: str) -> set[str]:
        query = "&".join(f"{k}={v}" for k, v in params.items())
        rows = client.get(f"/api/confirmations?workspace_id={ws['id']}&status=pending&{query}").json()
        return {row["id"] for row in rows}

    # 各自只看得到自己的
    assert ids(session_id="sess-a") == {a["id"]}
    assert ids(session_id="sess-b") == {b["id"]}
    # 全局中心只兜没有会话的那些
    assert ids(unowned="true") == {ext["id"]}
    # 不带筛选仍是全部(调试/审计)
    assert ids() == {a["id"], b["id"], ext["id"]}


# --- 工作流有、智能体也该有的三件事:发布 / 外部写请求 / 跑代码 -------------------
#
# 这三件的后果都不在这个应用里 —— 发出去的帖子、别人服务器上的改动、本机跑过的代码,
# 都撤不回来。所以它们全部走确认卡,而且**和工作流节点共用同一段实现**:超时、截断上限、
# 子进程隔离这些约定,不该因为入口不同而在一边被改、另一边不知道。


def test_run_code_confirmation_runs_the_same_code_path_as_the_node() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    confirmation = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "run_code",
            "requested_by": "pi",
            "payload": {"code": "output = inputs['a'] + 1", "inputs": {"a": 41}},
        },
    ).json()
    assert confirmation["status"] == "pending"
    assert "在你的机器上运行" in confirmation["summary"]

    approved = client.post(f"/api/confirmations/{confirmation['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    assert approved["result"]["output"] == 42


def test_run_code_confirmation_cannot_see_the_backend_env() -> None:
    """后端进程里有各家模型的 API key。代码节点靠子进程 + 最小 env 挡住它 ——
    智能体这条入口共用同一个实现,那道隔离才不会只在其中一边成立。"""
    import os

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    os.environ["MOSAEL_SECRET_PROBE"] = "leaked"
    try:
        confirmation = client.post(
            "/api/confirmations",
            json={
                "workspace_id": ws["id"],
                "tool": "run_code",
                "requested_by": "pi",
                "payload": {"code": "import os\noutput = os.environ.get('MOSAEL_SECRET_PROBE', '')"},
            },
        ).json()
        approved = client.post(f"/api/confirmations/{confirmation['id']}/approve").json()
        assert approved["status"] == "executed", approved.get("error")
        assert approved["result"]["output"] == ""
    finally:
        os.environ.pop("MOSAEL_SECRET_PROBE", None)


def test_http_request_confirmation_goes_through_the_shared_node_implementation(monkeypatch) -> None:
    import httpx as _httpx

    from app.domain.workflows.executors import basic

    seen: dict[str, object] = {}

    def fake_request(method, url, **kwargs):
        seen.update(method=method, url=url, headers=kwargs.get("headers"), content=kwargs.get("content"))
        return _httpx.Response(201, json={"ok": True}, request=_httpx.Request(method, url))

    monkeypatch.setattr(basic.httpx, "request", fake_request)

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    confirmation = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "http_request",
            "requested_by": "pi",
            "payload": {
                "url": "https://example.test/hook",
                "method": "POST",
                "headers": {"X-Token": "t"},
                "body": '{"hi":1}',
            },
        },
    ).json()
    # 请求在批准之前不该发出去
    assert seen == {}
    assert "向外部发起 POST" in confirmation["summary"]

    approved = client.post(f"/api/confirmations/{confirmation['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    assert approved["result"] == {"status": 201, "text": '{"ok":true}', "json": {"ok": True}}
    assert seen["method"] == "POST"
    assert seen["headers"] == {"X-Token": "t"}
    assert seen["content"] == b'{"hi":1}'


def test_publish_confirmation_rejects_an_account_outside_the_workspace() -> None:
    """确认卡里带的是 id,不是对象 —— 批准的那一刻要重新验一次归属,
    否则一个别处的账号 id 就能借这条路发到别人的号上。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    confirmation = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "publish_asset",
            "requested_by": "pi",
            "payload": {"account_id": "no-such-account", "asset_id": "no-such-asset", "title": "标题"},
        },
    ).json()
    assert "公开发布" in confirmation["summary"]

    approved = client.post(f"/api/confirmations/{confirmation['id']}/approve").json()
    assert approved["status"] == "failed"
    assert "发布账号不存在" in approved["error"]


def test_http_request_confirmation_refuses_non_http_urls() -> None:
    """file:// 会把本机文件读成「请求结果」交回给模型。这道校验在开卡时就做 ——
    一张说不清要请求什么的卡,没有让用户去点批准的道理。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    denied = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "http_request",
            "requested_by": "pi",
            "payload": {"url": "file:///etc/passwd", "method": "GET"},
        },
    )
    assert denied.status_code == 422, denied.text
    assert "http(s)" in denied.json()["detail"]


def test_approving_run_code_still_requires_edit() -> None:
    """批准永远是写操作 —— 只读的人批不了,哪怕代码本身跑在隔离里。

    此前这里挡的是「不是部署管理员就不能跑代码」;那道闸随隔离执行器撤掉了(ADR 0008 D2 ——
    「谁有资格写代码」是个错问题)。**剩下的这条仍然成立而且更基本**:viewer 不能替工作区做
    任何写决定,run_code 也不例外。
    """
    from tests.util import second_client

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    member = second_client("member")
    invited = client.post(f"/api/workspaces/{ws['id']}/invitations", json={"username": "member", "role": "viewer"})
    assert invited.status_code == 200, invited.text
    invitation = member.get("/api/invitations").json()["invitations"][0]
    assert member.post(f"/api/invitations/{invitation['id']}/accept").status_code == 200

    # 卡由 owner 开(开卡本身就要 edit),viewer 去批 —— 这样隔离出的正是**批准**那道闸。
    confirmation = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "run_code",
            "requested_by": "pi",
            "payload": {"code": "output = 1"},
        },
    ).json()
    denied = member.post(f"/api/confirmations/{confirmation['id']}/approve")
    assert denied.status_code == 403, denied.text
    # 拒绝之后卡还在 pending,可以由有权限的人来批
    assert client.get(f"/api/confirmations/{confirmation['id']}").json()["status"] == "pending"
