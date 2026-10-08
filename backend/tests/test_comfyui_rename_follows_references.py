"""在 Mosael 的工作流库里改名、挪目录时,指着旧路径的引用当场改过去(ADR 0045 修订之二 D2–D5,维护者 2026-10-09 按推荐拍板)。

此前在工作流库里把一张工作流挪进文件夹,下一次目录刷新旧路径那几行模型被删(目录就是答案),挂在上面的默认模型被外键置空;
画板格子、AI Studio 会话、工作流的生成节点、定时任务全成了「用不了」;工具名按路径哈希起的老文件,工作流里用它的节点也断了。

- 插件在改名的回答里报一次 `moved`(模型 id 和工具名各一串),宿主在**同一个请求里、目录重拉之前**照做:模型行原地改名
  (默认模型、停用跟着走),各领域改存着的引用(包括历史:生成记录),工作流落一版 `rename` 修订;工具开关、工作流里的插件
  节点改到新工具名。不记一次性改名的账。(D2)
- 改不成:引用的改动整批撤掉,文件改名照样算成功。(D3)
- 另一条连接哪怕指着同一台 ComfyUI,也不跟着改 —— 连接是边界。(D4)
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import (
    Board, GenerationJob, GenerationSession, PluginCapability, PluginInstance, ProviderModel, ProviderProfile, Workflow,
    WorkflowRevision,
)
from app.domain.providers import defaults as provider_defaults
from tests.fake_comfyui import FakeComfyUI, comfyui_grants
from tests.test_plugin_dynamic_tools import _workflow
from tests.util import fresh_client, user_id

PACKAGE = "dev.mosael.comfyui"
VENDOR = f"plugin:{PACKAGE}"


def _formed(ui: dict[str, Any], *, ident: bool = True) -> dict[str, Any]:
    """一张有表单(`app`)的工作流;`ident=False` 是没有 ComfyUI 存的 id 的老文件(工具名退到路径哈希,改名就变)。"""
    stored = copy.deepcopy(ui)
    stored["extra"] = {"mosael": {"version": 2, "forms": [{"id": "app", "title": "快速出图", "description": "",
                                                           "graph_items": {}}]}}
    next(one for one in stored["nodes"] if one["id"] == 6)["properties"] = {
        "mosael": {"forms": {"app": {"text": {"order": 0, "main": True}}}}}
    if not ident:
        stored.pop("id", None)
    return stored


def _connect(client, comfy: FakeComfyUI, name: str) -> tuple[str, str]:
    created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"name": name, "config": {"server_url": comfy.url}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    with SessionLocal() as db:
        return instance_id, db.scalar(select(ProviderProfile.id).where(ProviderProfile.plugin_instance_id == instance_id))


def _tool_of(instance_id: str, path: str, entry: str) -> str:
    with SessionLocal() as db:
        tools = db.get(PluginInstance, instance_id).discovered_tools
    return next(one["name"] for one in tools if (one.get("workflow") or {}).get("path") == path
                and (one.get("group") or {}).get("entry") == entry)


@pytest.fixture
def library():
    """一台 ComfyUI、两条连接(工作室 = 要改的那条,笔记本 = 指着同一台的另一条);工作室那条上的引用遍布各个领域。"""
    with FakeComfyUI() as comfy:
        comfy.state.workflows["portrait.json"] = _formed(comfy.state.workflows["portrait.json"])
        comfy.state.workflows["hashed.json"] = _formed(comfy.state.workflows["portrait.json"], ident=False)
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        studio, profile = _connect(client, comfy, "工作室")
        laptop, other_profile = _connect(client, comfy, "笔记本")
        hashed_full, hashed_form = _tool_of(studio, "hashed.json", "full"), _tool_of(studio, "hashed.json", "form")
        with SessionLocal() as db:
            row = db.scalar(select(ProviderModel).where(ProviderModel.provider_profile_id == profile,
                                                        ProviderModel.model_id == "portrait.json#app"))
            provider_defaults.set_default(db, "image", row, owner_user_id=user_id())
            db.get(PluginCapability, {"instance_id": studio, "tool_name": hashed_form}).exposed = False
            mine = GenerationSession(workspace_id=ws, owner_user_id=user_id(), provider_profile_id=profile,
                                     model="portrait.json#app", kind="image", title="工作室的")
            theirs = GenerationSession(workspace_id=ws, owner_user_id=user_id(), provider_profile_id=other_profile,
                                       model="portrait.json#app", kind="image", title="笔记本的")
            db.add_all([mine, theirs])
            db.flush()
            db.add(GenerationJob(workspace_id=ws, session_id=mine.id, provider_profile_id=profile, provider=VENDOR,
                                 model="portrait.json#app", kind="image", request={"prompt": "柴犬", "parameters": {}}))
            db.add(Board(workspace_id=ws, name="画板", revision=1, canvas={"edges": [], "items": [
                {"id": "mine", "kind": "image", "x": 0, "y": 0, "w": 100, "h": 100,
                 "form": {"provider": VENDOR, "provider_profile_id": profile, "model": "portrait.json", "parameters": {}}},
                {"id": "theirs", "kind": "image", "x": 200, "y": 0, "w": 100, "h": 100,
                 "form": {"provider": VENDOR, "provider_profile_id": other_profile, "model": "portrait.json"}},
            ]}))
            db.commit()
            row_id = row.id
        workflow_id = _workflow(ws, {"nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "gen", "type": "ai_generate", "config": {"provider_profile_id": profile, "provider": VENDOR,
                                                           "model": "portrait.json#app", "kind": "image", "prompt": "柴犬"}},
            {"id": "pick", "type": "entity_angles", "config": {"model": f"{profile}:image:portrait.json"}},
            {"id": "full", "type": f"plugin.{PACKAGE}.{hashed_full}", "config": {"instance_id": studio, "prompt": "柴犬"}},
            {"id": "form", "type": f"plugin.{PACKAGE}.{hashed_form}", "config": {"instance_id": studio, "prompt": "柴犬"}},
        ], "edges": [{"id": "e1", "source": "start", "target": "gen"}]})
        yield client, comfy, {"studio": studio, "laptop": laptop, "profile": profile, "other": other_profile, "ws": ws,
                              "row": row_id, "workflow": workflow_id, "hashed_full": hashed_full,
                              "hashed_form": hashed_form}


def _rename(client, instance_id: str, path: str, new_path: str) -> None:
    done = client.post(f"/api/plugins/instances/{instance_id}/workflow-library/rename",
                       json={"path": path, "new_path": new_path})
    assert done.status_code == 200, done.text


def test_在工作流库里改名_各处引用当场跟过去_历史也改_不记账_另一条连接不动(library) -> None:
    client, comfy, ids = library
    with SessionLocal() as db:
        moves_before = db.get(PluginInstance, ids["studio"]).applied_moves
    _rename(client, ids["studio"], "portrait.json", "归档/portrait.json")

    with SessionLocal() as db:
        rows = {row.model_id: row for row in db.scalars(
            select(ProviderModel).where(ProviderModel.provider_profile_id == ids["profile"]))}
        assert rows["归档/portrait.json#app"].id == ids["row"], "模型行原地改名:行 id 不变"
        assert "portrait.json#app" not in rows and "portrait.json" not in rows, "目录重拉之后旧路径那几行不在了"
        assert provider_defaults.get_row(db, "image", user_id()).provider_model_id == ids["row"], \
            "默认模型跟着走(此前旧行被删,外键置空)"
        sessions = {one.title: one.model for one in db.scalars(select(GenerationSession).where(
            GenerationSession.workspace_id == ids["ws"]))}
        assert sessions == {"工作室的": "归档/portrait.json#app", "笔记本的": "portrait.json#app"}, \
            "只改这条连接的:指着同一台 ComfyUI 的另一条连接是另一套目录(D4)"
        assert db.scalar(select(GenerationJob.model).where(GenerationJob.workspace_id == ids["ws"])) == \
            "归档/portrait.json#app", "生成记录(历史)也改:记录脚注、「用同样的参数再来一次」读它"
        board = db.scalar(select(Board).where(Board.workspace_id == ids["ws"]))
        forms = {item["id"]: item["form"]["model"] for item in board.canvas["items"]}
        assert forms == {"mine": "归档/portrait.json", "theirs": "portrait.json"}
        workflow = db.get(Workflow, ids["workflow"])
        nodes = {node["id"]: node for node in workflow.graph["nodes"]}
        assert nodes["gen"]["config"]["model"] == "归档/portrait.json#app"
        assert nodes["pick"]["config"]["model"] == f"{ids['profile']}:image:归档/portrait.json"
        latest = db.scalars(select(WorkflowRevision).where(WorkflowRevision.workflow_id == ids["workflow"])
                            .order_by(WorkflowRevision.revision.desc())).first()
        assert latest.source == "rename" and "改了名" in latest.note, "工作流落一版 rename 修订,说清楚为什么改"
        moves_after = db.get(PluginInstance, ids["studio"]).applied_moves
        assert moves_after["generation"]["form-entries"] == sorted([*moves_before["generation"]["form-entries"],
                                                                     "归档/portrait.json"]), \
            "改名本身不进账;账上做过的旧名字换了地方,新名字也算做过 —— 不然下一次刷新又把跟过去的完整入口改到表单"
        assert moves_after["tools"] == moves_before["tools"], "工具名没变(按图的 id 起的):工具那本账不动"
    options = {one["model"] for one in client.get("/api/generation/options?kind=image").json()
               if one["provider"] == VENDOR}
    assert {"归档/portrait.json", "归档/portrait.json#app"} <= options


def test_工具名按路径哈希起的老文件_挪目录后工作流节点和工具开关跟着新名字(library) -> None:
    client, comfy, ids = library
    _rename(client, ids["studio"], "hashed.json", "归档/hashed.json")
    new_full, new_form = _tool_of(ids["studio"], "归档/hashed.json", "full"), _tool_of(ids["studio"], "归档/hashed.json", "form")
    assert new_full != ids["hashed_full"], "没有 id 的老文件,工具名跟着路径变"
    with SessionLocal() as db:
        nodes = {node["id"]: node for node in db.get(Workflow, ids["workflow"]).graph["nodes"]}
        assert nodes["full"]["type"] == f"plugin.{PACKAGE}.{new_full}" and nodes["form"]["type"] == f"plugin.{PACKAGE}.{new_form}"
        assert nodes["full"]["config"] == {"instance_id": ids["studio"], "prompt": "柴犬"}, "填的值原样带过去"
        toggles = {row.tool_name: row.exposed for row in db.scalars(
            select(PluginCapability).where(PluginCapability.instance_id == ids["studio"]))}
        assert toggles[new_form] is False, "用户关掉的那个开关,跟着新名字照旧关着"
    unusable = client.get("/api/workflows/node-types/unusable", params={
        "types": [f"plugin.{PACKAGE}.{new_full}", f"plugin.{PACKAGE}.{new_form}"]}).json()
    assert [one for one in unusable if "工作室" in one["reason"] and one["type"].endswith(new_full)] == [], \
        "改过去的节点在这条连接上用得了"


def test_文件夹改名_里面每一张的引用都跟过去(library) -> None:
    client, comfy, ids = library
    _rename(client, ids["studio"], "portrait.json", "归档/portrait.json")
    done = client.post(f"/api/plugins/instances/{ids['studio']}/workflow-library/folders/rename",
                       json={"path": "归档", "new_path": "旧的"})
    assert done.status_code == 200, done.text
    with SessionLocal() as db:
        assert db.scalar(select(GenerationSession.model).where(GenerationSession.title == "工作室的")) == \
            "旧的/portrait.json#app"


def test_改引用出错_引用整批撤掉_文件改名照样算成功(library, monkeypatch, caplog) -> None:
    """D3:那台机器上的文件已经挪了,撤回又要再挪一次,出错面更大 —— 引用停在旧名字上(会说清楚「工作流不在了」),记一条日志。"""
    from app.domain.providers import moved_models

    client, comfy, ids = library

    def broken(db, profile_id, renames, **_) -> None:
        raise RuntimeError("画板那一侧炸了")

    monkeypatch.setattr(moved_models, "_listeners", [*moved_models._listeners, broken])
    _rename(client, ids["studio"], "portrait.json", "归档/portrait.json")
    assert "归档/portrait.json" in comfy.state.workflows and "portrait.json" not in comfy.state.workflows, "文件改名照样算成功"
    with SessionLocal() as db:
        assert db.scalar(select(GenerationSession.model).where(GenerationSession.title == "工作室的")) == \
            "portrait.json#app", "引用的改动整批撤掉,停在旧名字上"
        nodes = {node["id"]: node for node in db.get(Workflow, ids["workflow"]).graph["nodes"]}
        assert nodes["gen"]["config"]["model"] == "portrait.json#app", "排在前面改好的那几处也一起撤掉"
    assert any("跟着改引用没做成" in record.getMessage() for record in caplog.records)
