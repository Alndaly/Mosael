"""每个需要确认的工具都说了自己改了哪些数据(ADR 0053)。

此前界面批完一张卡要刷新哪些缓存,靠前端一份按工具逐行手写的清单 —— 每加一种会直接改数据的卡就得记得去补一行,
漏过项目(在剪辑页里批掉「删除项目 X」,切换器还列着 X、剪辑页还开着 X)、发布任务。现在由工具自己声明
(`ConfirmableTool.writes`,词见 app/domain/resources.py),卡的接口带着它,前端按 api/resourceKeys 那一张表换成缓存键。

1. 声明没有缺省值:新加一个工具不写它,构造就失败(导入这个包就报错,整套测试都红);
2. 写的词都在词表里,和任务目录(`JobKind.affects`)同一套;
3. 卡的接口把它带出去。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import pytest

from app.domain.agent.confirmable import registry
from app.domain.agent.confirmable.registry import ConfirmableTool, tool_families, tool_spec, tool_specs
from app.domain.agent.tool_manifest import PLUGIN_TOOL_PREFIX
from app.domain.job_catalog import FALLBACK, JOB_KINDS
from app.domain.resources import RESOURCES
from tests.util import fresh_client


def _noop(*_args):
    return {}


def test_不写改了什么就造不出一个需要确认的工具() -> None:
    with pytest.raises(TypeError, match="writes"):
        ConfirmableTool(name="x", permission="edit", cost="none", summarize=lambda db, p: ("", {}), execute=_noop)
    with pytest.raises(ValueError, match="writes"):
        ConfirmableTool(name="x", permission="edit", cost="none", summarize=lambda db, p: ("", {}), execute=_noop,
                        writes=("asset",))
    with pytest.raises(ValueError, match="writes"):
        ConfirmableTool(name="x", permission="edit", cost="none", summarize=lambda db, p: ("", {}), execute=_noop,
                        writes=["assets"])  # type: ignore[arg-type]


def test_每个需要确认的工具都声明了_而且用的是词表里的词() -> None:
    import mcp_server

    specs = tool_specs()
    #: 智能体开卡的每个工具都在登记表里(插件工具是一族,按名字造)。
    for name in mcp_server.CONFIRMATION_TOOLS:
        spec = tool_spec(name) if not name.startswith(PLUGIN_TOOL_PREFIX) else tool_spec(f"{name}x")
        assert spec is not None, f"{name}:开卡的工具不在 confirmable 登记表里"
    bound = [tool_spec(f"{prefix}conn__tool") for prefix in tool_families()]
    for spec in [*specs.values(), *bound]:
        assert spec is not None
        assert isinstance(spec.writes, tuple), spec.name
        assert set(spec.writes) <= set(RESOURCES), f"{spec.name}: {spec.writes}"
    assert len(specs) >= 30, "登记表几乎是空的 —— 这条测试什么都没量"
    #: 会直接改 Mosael 数据的那几样,声明不该是空的(手写清单那会儿漏过的两样在里面)。
    assert "projects" in specs["delete_projects"].writes
    assert "publish_tasks" in specs["publish_asset"].writes


def test_任务和需要确认的工具说的是同一套词() -> None:
    for kind in [*JOB_KINDS.values(), FALLBACK]:
        assert set(kind.affects) <= set(RESOURCES), f"{kind.kind}: {kind.affects}"


def test_卡的接口带着它改了哪些数据() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    project = client.post("/api/projects", json={"workspace_id": workspace, "name": "宣传片"}).json()["id"]
    opened = client.post("/api/confirmations", json={"workspace_id": workspace, "tool": "delete_projects",
                                                      "payload": {"project_ids": [project]}})
    assert opened.status_code == 200, opened.text
    card = opened.json()
    assert card["writes"] == ["projects", "assets", "sequences"]
    listed = client.get(f"/api/confirmations?workspace_id={workspace}&status=pending").json()
    assert [one["writes"] for one in listed if one["id"] == card["id"]] == [["projects", "assets", "sequences"]]
    #: 批完的那张也带着(界面按批准接口的回包刷新)。
    approved = client.post(f"/api/confirmations/{card['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "executed"
    assert approved.json()["writes"] == ["projects", "assets", "sequences"]


def test_登记表里认不出的工具_卡上是空的(monkeypatch) -> None:
    """老卡(工具后来改了名)、插件被卸掉:界面照样刷新卡本身,不猜。"""
    from app.api.schemas.agent import ConfirmationOut

    monkeypatch.setattr(registry, "_TOOLS", {})
    monkeypatch.setattr(registry, "_FAMILIES", {})
    out = ConfirmationOut.model_validate({
        "id": "c", "workspace_id": "w", "session_id": None, "tool": "gone_tool", "permission": "edit", "summary": "s",
        "payload": {}, "status": "pending", "result": {}, "error": None, "requested_by": "x",
        "created_at": "2026-10-09T00:00:00", "resolved_at": None,
    })
    assert out.writes == []
