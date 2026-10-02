"""智能体能给项目新建一条空时间线。

用户会话(Kimi · k3):用户说「请你重新创建对应时间线」,模型绕了二十多次调用 —— 往画板上加时间线格、拿项目 id 去
edit_timeline…… —— 最后只能请用户手动去建。工具面上根本没有「建时间线」这件事:create_project 只建项目,
edit_timeline 要一条已有的时间线。

并进 create_project(工具定义每轮重发,预算由 test_tool_definitions_budget 盯着):和工作流的
project_sequence_create 节点同一个形状 —— 给了 project_id 就把时间线建在那个已有项目里,`timeline=true` 时新项目
顺手带一条。画幅 / 帧率不给就跟这个项目当前那条时间线,项目里还没有就和剪辑页「新建时间线」同一个缺省。
"""

from __future__ import annotations

import contextvars

import pytest

import mcp_server
from app.core.db import SessionLocal
from app.core.security import find_session
from app.db.models import Project
from tests.util import fresh_client


@pytest.fixture
def agent(monkeypatch):
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        me = find_session(db, client.headers["Authorization"].removeprefix("Bearer ")).user_id
    monkeypatch.setattr(mcp_server, "_CALLER_ID", contextvars.ContextVar("test_caller", default=me))
    return client, ws


def _timeline(sequence_id: str) -> dict:
    return mcp_server.inspect_sequence(sequence_id=sequence_id)


def test_给已有项目建一条空时间线_能直接拿去剪(agent) -> None:
    client, ws = agent
    project = mcp_server.create_project(name="宣传片")
    assert project.get("sequence_id") is None, "不要 timeline 时只建项目,和此前一样"

    created = mcp_server.create_project(name="竖屏版", project_id=project["id"], width=1080, height=1920)

    assert created["id"] == project["id"], "给了 project_id 就不该再建一个项目"
    timeline = _timeline(created["sequence_id"])
    assert (timeline["name"], timeline["width"], timeline["height"], timeline["fps"]) == ("竖屏版", 1080, 1920, 30)
    assert {track["kind"] for track in timeline["tracks"]} == {"video", "audio"}, "要有能直接放片段的音视频轨"
    with SessionLocal() as db:
        assert db.get(Project, project["id"]).active_sequence_id == created["sequence_id"], "项目原本没有时间线:打开就停在这一条"


def test_不给画幅就跟项目当前那条时间线(agent) -> None:
    _client, _ws = agent
    project = mcp_server.create_project(name="宣传片")
    first = mcp_server.create_project(name="主序列", project_id=project["id"], width=1080, height=1920, fps=25)
    second = mcp_server.create_project(name="备选剪法", project_id=project["id"])

    timeline = _timeline(second["sequence_id"])
    assert (timeline["width"], timeline["height"], timeline["fps"]) == (1080, 1920, 25)
    with SessionLocal() as db:
        assert db.get(Project, project["id"]).active_sequence_id == first["sequence_id"], "已有项目保持它原来那条"


def test_新项目可以顺手带一条时间线_缺省画幅和剪辑页新建的一样(agent) -> None:
    _client, _ws = agent
    created = mcp_server.create_project(name="新片", timeline=True)
    timeline = _timeline(created["sequence_id"])
    assert (timeline["name"], timeline["width"], timeline["height"], timeline["fps"]) == ("新片", 1920, 1080, 30)


def test_别的工作区的项目建不进去(agent) -> None:
    client, _ws = agent
    other = client.post("/api/workspaces", json={"name": "别处"}).json()["id"]
    elsewhere = client.post("/api/projects", json={"workspace_id": other, "name": "别处的项目"}).json()["id"]
    with pytest.raises(Exception) as caught:
        mcp_server.create_project(name="x", project_id=elsewhere, workspace_id=_ws)
    assert "not found" in str(caught.value).lower() or "不" in str(caught.value)


def test_项目里还没有时间线时_inspect_sequence_指路去建(agent) -> None:
    _client, _ws = agent
    project = mcp_server.create_project(name="空项目")
    with pytest.raises(ValueError) as caught:
        mcp_server.inspect_sequence(project_id=project["id"])
    assert "create_project" in str(caught.value), "只说「没有时间线」,模型不知道怎么建"
