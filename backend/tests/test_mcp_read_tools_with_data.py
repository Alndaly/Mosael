"""每个只读的列表 / 详情工具,都在**有数据**的工作区上真跑一遍。

用户会话(Kimi · k3):`list_boards` 连报三次「1 validation error for BoardOut canvas Field required」,模型以为是
「损坏数据」,绕开画板去找别的路。根因是工具拿**详情**的出参 schema(BoardOut,要整份 canvas)去校验用例返回的
**摘要**(board_summary 早就不带 canvas 了)。test_mcp_tool_payloads 里的 `"list_boards": {}` 只在空工作区跑过 ——
清单是空的,一行都没有可校验的,于是永远是绿的。

这里先给每一类实体各建一条,再把读它们的工具挨个调一遍:**任何异常都算失败**(这一次传的都是真 id)。

`READS` 是**棘轮**:新加一个列表类只读工具(list_* / search_* / *_list)却不在这里登记一份,下面那条就红。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import asyncio
import contextvars
from typing import Any, Callable

import mcp_server
from app.core.db import SessionLocal
from app.core.security import find_session
from app.db.models import BrowserProfile, PublishAccount, PublishTask, Scene3DModel
from app.domain import jobs as jobs_domain
from tests.util import fresh_client, insert_asset

#: 列表类只读工具里**不在这里跑**的 → 理由。只减不增。
UNSEEDED: dict[str, str] = {}


def _seed(client, monkeypatch) -> dict[str, str]:
    """每一类各建一条;返回各自的 id。"""
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        me = find_session(db, client.headers["Authorization"].removeprefix("Bearer ")).user_id
    monkeypatch.setattr(mcp_server, "_CALLER_ID", contextvars.ContextVar("test_caller", default=me))

    ids: dict[str, str] = {"workspace": ws}
    ids["project"] = mcp_server.create_project(name="宣传片")["id"]
    ids["asset"] = insert_asset(ws, kind="video", name="素材.mp4", media_info={"duration": 3.0})
    ids["workflow"] = client.post("/api/workflows", json={"workspace_id": ws, "name": "流", "graph": {
        "nodes": [{"id": "start", "type": "start", "config": {"params": {}}}], "edges": []}}).json()["id"]
    ids["board"] = client.post("/api/boards", json={"workspace_id": ws, "name": "灵感板", "canvas": {
        "items": [{"id": "n1", "kind": "note", "x": 0, "y": 0, "width": 200, "height": 120, "text": "开场要快"}],
        "edges": []}}).json()["id"]
    mcp_server.remember(content="视频统一竖屏")
    ids["note"] = mcp_server.create_note(title="脚本", markdown="第一场:清晨")["id"]
    ids["scene"] = mcp_server.create_scene(name="客厅")["id"]
    ids["entity"] = mcp_server.create_entity(kind="character", name="小林", prompt="黑色短发")["id"]
    ids["session"] = client.post("/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": ws}).json()["id"]
    with SessionLocal() as db:
        db.add(Scene3DModel(workspace_id=ws, name="沙发", format="glb", file_key="", size=10))
        account = PublishAccount(workspace_id=ws, owner_user_id=me, platform="bilibili", name="主号")
        db.add(account)
        db.add(BrowserProfile(workspace_id=ws, owner_user_id=me, name="登录档"))
        db.flush()
        db.add(PublishTask(workspace_id=ws, account_id=account.id, asset_id=ids["asset"], title="成片"))
        ids["job"] = jobs_domain.create_job(db, workspace_id=ws, kind="tts", created_by=me, payload={"subject": "配音"}).id
        db.commit()
    return ids


#: 工具名 → (参数, 结果里至少该有的条数)。参数是 id 表 → kwargs 的函数。
READS: dict[str, tuple[Callable[[dict[str, str]], dict[str, Any]], int]] = {
    "list_workspaces": (lambda ids: {}, 1),
    "list_projects": (lambda ids: {}, 1),
    "list_assets": (lambda ids: {}, 1),
    "list_workflows": (lambda ids: {}, 1),
    "list_boards": (lambda ids: {}, 1),
    "list_board_producers": (lambda ids: {}, 1),
    "list_workflow_node_types": (lambda ids: {}, 1),
    "list_memories": (lambda ids: {}, 1),
    #: 内置的三份技能每个工作区都有;给名字就是那一份的原文(ADR 0043)。
    "list_skills": (lambda ids: {}, 3),
    "search_notes": (lambda ids: {"query": "脚本"}, 1),
    "list_scenes": (lambda ids: {}, 1),
    "list_entities": (lambda ids: {}, 1),
    "list_scene_models": (lambda ids: {}, 1),
    "list_agent_sessions": (lambda ids: {}, 1),
    "list_jobs": (lambda ids: {}, 1),
    "list_publish_accounts": (lambda ids: {}, 1),
    "list_publish_tasks": (lambda ids: {}, 1),
    "browser_pool_list": (lambda ids: {}, 0),
    "list_generation_models": (lambda ids: {}, 0),
    "list_speech_engines": (lambda ids: {}, 0),
    "list_provider_models": (lambda ids: {}, 0),
    # 详情:同一类错配的另一面(拿摘要 schema 校验详情会丢字段,拿详情 schema 校验摘要会炸)。
    "get_board": (lambda ids: {"board_id": ids["board"]}, 0),
    "get_workflow": (lambda ids: {"workflow_id": ids["workflow"]}, 0),
    "get_scene": (lambda ids: {"scene_id": ids["scene"]}, 0),
    "get_entity": (lambda ids: {"entity_id": ids["entity"]}, 0),
    "read_note": (lambda ids: {"note_id": ids["note"]}, 0),
    "get_job": (lambda ids: {"job_id": ids["job"]}, 0),
}


def _count(result: Any) -> int:
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict):
        for key in ("profiles", "items", "models", "engines"):
            if isinstance(result.get(key), list):
                return len(result[key])
        return 1
    return 0


def test_有数据的工作区上_每个读工具都跑得通(monkeypatch) -> None:
    client = fresh_client()
    ids = _seed(client, monkeypatch)
    broken: list[str] = []
    for name, (args, at_least) in READS.items():
        try:
            result = getattr(mcp_server, name)(**args(ids))
        except Exception as exc:  # noqa: BLE001 — 这里传的全是真 id,任何异常都是 bug
            broken.append(f"{name}: {type(exc).__name__}: {str(exc)[:200]}")
            continue
        if _count(result) < at_least:
            broken.append(f"{name}: 建了数据却一条都没列出来({result!r:.200})")
    assert broken == [], "这些读工具在有数据时跑不通:\n  " + "\n  ".join(broken)


def test_list_boards_报出每张板的格子数(monkeypatch) -> None:
    """格子数来自摘要的 item_count —— 此前从 canvas 里数,而摘要里没有 canvas。"""
    client = fresh_client()
    ids = _seed(client, monkeypatch)
    assert mcp_server.list_boards() == [{"id": ids["board"], "name": "灵感板", "items": 1}]


def test_每个列表类只读工具都在有数据的工作区上跑过() -> None:
    """只减不增:新加的 list_* / search_* / *_list 只读工具,要么在 READS 里,要么在 UNSEEDED 里写明为什么不跑。"""
    tools = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    listing = {
        name for name in tools
        if mcp_server._TOOL_EFFECTS.get(name) == "reads"
        and (name.startswith(("list_", "search_")) or name.endswith("_list"))
    }
    missing = sorted(listing - set(READS) - set(UNSEEDED))
    assert missing == [], "这些列表类只读工具没在有数据的工作区上跑过:\n  " + "\n  ".join(missing)
    stale = sorted((set(READS) | set(UNSEEDED)) - tools)
    assert stale == [], f"登记了不存在的工具: {stale}"
