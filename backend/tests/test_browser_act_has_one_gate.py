"""智能体在浏览器会话上动手:**闸只在领域用例里**(`domain/browser/use_cases.act`),三条入口同一个说法。

此前三步(会话能不能动手 → 上传来源放行 → 交给执行器)写在路由里;工作流执行器手抄了第二步;
智能体工具层借道调**路由函数本体**(`mcp_server._route`),把 HTTPException 拼成 `"403: …"` 字符串 ——
工具层一套错误契约,`_use_case` 另一套。现在路由和工具都只调用例,拒绝就是领域错误,HTTP 那侧由
`api/domain_errors` 的一张表翻成状态码。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

import mcp_server
from app.api.domain_errors import STATUS_BY_ERROR
from app.core.db import SessionLocal
from app.db.models import User
from app.domain import browser
from app.domain.browser import use_cases as sessions
from app.domain.permissions import NotVisible
from tests.util import fresh_client, make_video_asset


def _uid(username: str) -> str:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).one().id


def _two_workspaces():
    """同一个人的两个工作区:素材在 B,会话开在 A —— 拿别处的素材往这个会话里传,该被拒。"""
    client = fresh_client()
    a = client.post("/api/workspaces", json={"name": "A"}).json()
    b = client.post("/api/workspaces", json={"name": "B"}).json()
    elsewhere = make_video_asset(client, b["id"])
    with SessionLocal() as db:
        session_id = browser.open_session(db, workspace_id=a["id"], owner_kind="manual", actor=_uid("tester")).id
        db.commit()
    return client, a, elsewhere, session_id


@pytest.fixture
def uploads(monkeypatch) -> list:
    sent: list = []
    monkeypatch.setattr(browser, "upload_file", lambda sid, file, **kw: sent.append(file) or {})
    return sent


def test_the_use_case_is_the_gate(uploads) -> None:
    """不经 HTTP 直接调用例:拒绝是领域错误,文件没有交给执行器。"""
    _client, a, elsewhere, session_id = _two_workspaces()
    with SessionLocal() as db:
        user = db.get(User, _uid("tester"))
        with pytest.raises(NotVisible):
            sessions.act(db, user, a["id"], session_id, "upload", {"asset_id": elsewhere["id"], "selector": "input"})
        with pytest.raises(NotVisible):
            sessions.act(db, user, a["id"], "no-such-session", "click", {"selector": "a"})
    assert uploads == []


def test_three_entrances_refuse_the_same_way(uploads, monkeypatch) -> None:
    """接口回 404、智能体工具抛同一个领域错误、工作流节点记下同一个文案 key。"""
    from app.db.models import Workflow
    from app.domain.workflows.errors import WorkflowDomainError
    from app.domain.workflows.executors.registry import get_executor
    from app.domain.jobs import create_job, reset_parent_job, set_parent_job
    from app.domain.workflows import create_workflow
    from tests.util import pinned

    client, a, elsewhere, session_id = _two_workspaces()
    args = {"asset_id": elsewhere["id"], "selector": "input"}

    over_http = client.post(
        "/api/agent-browser/act",
        json={"workspace_id": a["id"], "session_id": session_id, "action": "upload", "args": args},
    )
    assert over_http.status_code == 404, over_http.text

    with mcp_server.calling_as(user_id=_uid("tester")), pytest.raises(NotVisible) as from_tool:
        mcp_server.browser_upload(session_id, "input", elsewhere["id"], workspace_id=a["id"])
    assert str(from_tool.value) == over_http.json()["detail"]

    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=a["id"], name="W", graph={"nodes": [], "edges": []}, created_by=_uid("tester"))
        db.commit()
        run = create_job(db, workspace_id=a["id"], kind="workflow", payload=pinned(db, workflow), created_by=_uid("tester"))
        run.status = "running"
        db.commit()
        workflow_id, run_id = workflow.id, run.id
    token = set_parent_job(run_id)
    try:
        with SessionLocal() as db, pytest.raises(WorkflowDomainError) as from_node:
            get_executor("browser_upload")(db, db.get(Workflow, workflow_id), {"session": session_id, "asset_id": elsewhere["id"]})
    finally:
        reset_parent_job(token)
    assert from_node.value.key == from_tool.value.key
    assert uploads == []


def test_the_agent_tools_no_longer_borrow_route_functions() -> None:
    """工具层只剩 `_use_case` 一种调用:不 import 路由模块,也没有 `_route` 这条借道。"""
    tree = ast.parse(pathlib.Path("mcp_server.py").read_text(encoding="utf-8"))
    borrowed = sorted(
        {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.api.routes")}
    )
    assert borrowed == [], f"工具层又借道调路由了:{borrowed}"
    assert not any(isinstance(node, ast.FunctionDef) and node.name == "_route" for node in ast.walk(tree))


def test_every_mapped_error_reaches_http_with_its_code() -> None:
    """表里每一类错误都真的装到了应用上(漏装的那一类会落成 500)。"""
    from app.main import app

    for error_type in STATUS_BY_ERROR:
        assert error_type in app.exception_handlers, f"{error_type.__name__} 没装到应用上"
