"""老引用迁到表单入口(ADR 0045 §6):插件报的**一次性改名**(`moved`),宿主每个连接只做一次。

ComfyUI 插件 1.20 之前,一张有表单的工作流,它的路径(模型 id)和工具名指的是那张表单;从 1.20 起它们指完整工作流,
表单搬到 `<路径>#app` / `wf_<id>_app`。按完整工作流跑会不一样(主提示词写哪格、固定的种子、表单以外的旧参数、素材槽位),
界面也会从几项摊成全部参数 —— 所以升级后第一次刷新目录时,存着的引用改到表单入口:

- 模型行**原地改名**(行 id 不变 → 默认模型、停用跟着表单走),旧名字那一行由目录重新建出来(完整工作流,默认启用);
- 生成会话、生成记录、画板的生成格、工作流的生成节点(追加一版 migration 修订)、按生成选项 id 选的那几格;
- 工作流节点、画板的能力从 `wf_X` 改成 `wf_X_app`,配置一格不动;工具开关跟着新名字(用户关掉的照旧关着);
- **只做一次**:做过之后再报也不改 —— 升级之后特意选的完整工作流,不会被改走;别的连接上的引用不动。

升级前的样子这样造:先接上(第一次刷新已经按 1.20 做过一遍、记了账),再把库退回 1.20 之前留下的样子 —— 账清掉、表单入口那一行
和它的工具开关删掉、引用都写旧名字。
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from sqlalchemy import delete, select, text

from app.core.db import SessionLocal, engine
from app.db.models import (
    Board, GenerationJob, GenerationSession, PluginCapability, PluginInstance, ProviderModel, ProviderProfile, Workflow,
    WorkflowRevision,
)
from app.domain.providers import defaults as provider_defaults
from tests.fake_comfyui import PORTRAIT_ID, FakeComfyUI, comfyui_grants
from tests.test_plugin_dynamic_tools import _workflow
from tests.util import fresh_client, user_id

PACKAGE = "dev.mosael.comfyui"
VENDOR = f"plugin:{PACKAGE}"
FULL_TOOL = "wf_" + PORTRAIT_ID.replace("-", "")[:12]
FORM_TOOL = FULL_TOOL + "_app"


def _formed(ui: dict[str, Any]) -> dict[str, Any]:
    stored = copy.deepcopy(ui)
    stored["extra"] = {"mosael": {"version": 2, "forms": [{"id": "app", "title": "快速出图", "description": "",
                                                           "graph_items": {}}]}}
    next(one for one in stored["nodes"] if one["id"] == 6)["properties"] = {
        "mosael": {"forms": {"app": {"text": {"order": 0, "main": True}}}}}
    return stored


@pytest.fixture
def upgraded():
    """一个刚从 1.20 之前的版本升上来的库:引用都写旧名字,这条连接一批改名都没做过。"""
    with FakeComfyUI() as comfy:
        comfy.state.workflows["portrait.json"] = _formed(comfy.state.workflows["portrait.json"])
        client = fresh_client()
        created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": comfy.url}})
        instance_id = created.json()["id"]
        client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
        assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        with SessionLocal() as db:
            instance = db.get(PluginInstance, instance_id)
            assert instance.applied_moves == {"generation": {"form-entries": ["portrait.json"]},
                                              "tools": {"form-entries": [FULL_TOOL]}}, \
                "新接上的连接第一次刷新就记了账(那时一条引用都没有):按 key 和旧名字记"
            instance.applied_moves = {}
            profile = db.scalar(select(ProviderProfile).where(ProviderProfile.plugin_instance_id == instance_id))
            db.execute(delete(ProviderModel).where(ProviderModel.provider_profile_id == profile.id,
                                                   ProviderModel.model_id == "portrait.json#app"))
            db.execute(delete(PluginCapability).where(PluginCapability.instance_id == instance_id,
                                                      PluginCapability.tool_name == FORM_TOOL))
            db.get(PluginCapability, {"instance_id": instance_id, "tool_name": FULL_TOOL}).exposed = False
            row = db.scalar(select(ProviderModel).where(ProviderModel.provider_profile_id == profile.id,
                                                        ProviderModel.model_id == "portrait.json"))
            provider_defaults.set_default(db, "image", row, owner_user_id=user_id())
            session = GenerationSession(workspace_id=ws, owner_user_id=user_id(), provider_profile_id=profile.id,
                                        model="portrait.json", kind="image")
            db.add(session)
            db.flush()
            db.add(GenerationJob(workspace_id=ws, session_id=session.id, provider_profile_id=profile.id, provider=VENDOR,
                                 model="portrait.json", kind="image", request={"prompt": "柴犬", "parameters": {}}))
            option = f"{profile.id}:image:portrait.json"
            db.add(Board(workspace_id=ws, name="画板", revision=1, canvas={"edges": [], "items": [
                {"id": "mine", "kind": "image", "x": 0, "y": 0, "w": 100, "h": 100,
                 "form": {"provider": VENDOR, "provider_profile_id": profile.id, "model": "portrait.json", "parameters": {}}},
                {"id": "theirs", "kind": "image", "x": 200, "y": 0, "w": 100, "h": 100,
                 "form": {"provider": VENDOR, "provider_profile_id": "another-connection", "model": "portrait.json"}},
            ]}))
            db.commit()
            profile_id, row_id = profile.id, row.id
        workflow_id = _workflow(ws, {"nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "gen", "type": "ai_generate", "config": {"provider_profile_id": profile_id, "provider": VENDOR,
                                                           "model": "portrait.json", "kind": "image", "prompt": "柴犬"}},
            {"id": "tool", "type": f"plugin.{PACKAGE}.{FULL_TOOL}", "config": {"instance_id": "", "prompt": "柴犬"}},
            {"id": "pick", "type": "entity_angles", "config": {"model": option}},
        ], "edges": [{"id": "e1", "source": "start", "target": "gen"}]})
        yield client, comfy, {"instance": instance_id, "profile": profile_id, "row": row_id, "workflow": workflow_id,
                              "ws": ws}


def _refresh(client, instance_id: str) -> None:
    assert client.post(f"/api/plugins/instances/{instance_id}/refresh").status_code == 200


def test_升级后第一次刷新_老引用改到表单入口_只做一次(upgraded) -> None:
    client, _, ids = upgraded
    with SessionLocal() as db:
        db.get(ProviderModel, ids["row"]).enabled = False  # 用户在插件页停用过它(那时它就是表单)
        db.commit()
    _refresh(client, ids["instance"])
    with SessionLocal() as db:
        rows = {row.model_id: row for row in db.scalars(
            select(ProviderModel).where(ProviderModel.provider_profile_id == ids["profile"]))}
        assert rows["portrait.json#app"].id == ids["row"], "模型行原地改名:默认模型、停用跟着表单走"
        assert rows["portrait.json#app"].enabled is False
        assert rows["portrait.json"].id != ids["row"] and rows["portrait.json"].enabled is True, \
            "旧名字那一行是目录重新建出来的完整工作流,默认启用"
        default = provider_defaults.get_row(db, "image", user_id())
        assert default.provider_model_id == ids["row"]
        assert db.scalar(select(GenerationSession.model).where(GenerationSession.workspace_id == ids["ws"])) == \
            "portrait.json#app"
        assert db.scalar(select(GenerationJob.model).where(GenerationJob.workspace_id == ids["ws"])) == "portrait.json#app"
        board = db.scalar(select(Board).where(Board.workspace_id == ids["ws"]))
        forms = {item["id"]: item["form"] for item in board.canvas["items"]}
        assert forms["mine"]["model"] == "portrait.json#app" and board.revision == 2
        assert forms["theirs"]["model"] == "portrait.json", "别的连接上同名的路径不动"
        nodes = {node["id"]: node for node in db.get(Workflow, ids["workflow"]).graph["nodes"]}
        assert nodes["gen"]["config"]["model"] == "portrait.json#app"
        assert nodes["tool"]["type"] == f"plugin.{PACKAGE}.{FORM_TOOL}" and nodes["tool"]["config"] == {
            "prompt": "柴犬"}, "工具名改到表单入口,填的值原样带过去(表单入口的工具就是升级前那个;空着的「用哪个连接」本来就是没选)"
        assert nodes["pick"]["config"]["model"] == f"{ids['profile']}:image:portrait.json#app"
        revisions = db.scalars(select(WorkflowRevision).where(WorkflowRevision.workflow_id == ids["workflow"])
                               .order_by(WorkflowRevision.revision)).all()
        assert [one.source for one in revisions[-2:]] == ["migration", "migration"], "模型、工具各落一版机械修订"
        toggles = {row.tool_name: row.exposed for row in db.scalars(
            select(PluginCapability).where(PluginCapability.instance_id == ids["instance"]))}
        assert toggles[FORM_TOOL] is False and toggles[FULL_TOOL] is False, "用户关掉的那个开关,跟着新名字照旧关着"
        assert db.get(PluginInstance, ids["instance"]).applied_moves == {
            "generation": {"form-entries": ["portrait.json"]}, "tools": {"form-entries": [FULL_TOOL]}}

        # 之后特意选的完整工作流:再刷新也不会被改走
        session = GenerationSession(workspace_id=ids["ws"], owner_user_id=user_id(), provider_profile_id=ids["profile"],
                                    model="portrait.json", kind="image", title="完整的")
        db.add(session)
        db.commit()
        session_id = session.id
    _refresh(client, ids["instance"])
    with SessionLocal() as db:
        assert db.get(GenerationSession, session_id).model == "portrait.json", "改名只做一次"
        assert len(db.scalars(select(WorkflowRevision).where(WorkflowRevision.workflow_id == ids["workflow"])).all()) == \
            len(revisions)


def test_生成选项里两个入口都在_老会话打开的是表单(upgraded) -> None:
    client, _, ids = upgraded
    _refresh(client, ids["instance"])
    options = {one["model"]: one for one in client.get("/api/generation/options?kind=image").json()
               if one["provider"] == VENDOR}
    assert {"portrait.json", "portrait.json#app"} <= set(options)
    assert options["portrait.json#app"]["is_default"] is True, "默认模型跟着表单走"


def test_工具改名有一处没改成_整批撤掉不记账_清单照样存下_下次刷新再做(upgraded, monkeypatch) -> None:
    from app.domain.plugins import moves as plugin_moves

    client, _, ids = upgraded

    def broken(db, instance, renames, **_) -> None:
        raise RuntimeError("画板那一侧炸了")

    monkeypatch.setattr(plugin_moves, "_tool_listeners", [*plugin_moves._tool_listeners, broken])
    _refresh(client, ids["instance"])
    with SessionLocal() as db:
        instance = db.get(PluginInstance, ids["instance"])
        assert FORM_TOOL in {tool["name"] for tool in instance.discovered_tools}, "清单本身照样存下"
        assert "tools" not in instance.applied_moves, "没改成就不记账"
        nodes = {node["id"]: node for node in db.get(Workflow, ids["workflow"]).graph["nodes"]}
        assert nodes["tool"]["type"] == f"plugin.{PACKAGE}.{FULL_TOOL}", "排在前面改好的工作流节点也一起撤掉"

    monkeypatch.undo()
    _refresh(client, ids["instance"])
    with SessionLocal() as db:
        assert db.get(PluginInstance, ids["instance"]).applied_moves["tools"] == {"form-entries": [FULL_TOOL]}
        nodes = {node["id"]: node for node in db.get(Workflow, ids["workflow"]).graph["nodes"]}
        assert nodes["tool"]["type"] == f"plugin.{PACKAGE}.{FORM_TOOL}"


def test_同一批改名分两次报上来_后报的那张照样改_先改过的不再改(upgraded) -> None:
    """PLG-2:从 1.20 之前直接升到 1.21 的人,上一版格式的表单要在工作流库里「查看并升级」之后插件才报那条改名;「查看并升级」时
    一张刚在 ComfyUI 里改过被跳过、下次再升级,它的改名就晚一次才来。账只按 key 记的话,先来的那张做了、记了 key,晚来的那张被当成
    「做过了」—— 它的老引用(那时指的是表单)悄悄变成跑完整工作流。现在按 key 和旧名字记。"""
    client, comfy, ids = upgraded
    # 第二张有表单的工作流先还是上一版格式(这一版不读,不报改名),第一次刷新只改 portrait.json 那张
    later = copy.deepcopy(comfy.state.workflows["portrait.json"])
    later["id"] = "b2f4c3e8-1111-4222-8333-944455556666"
    later_v1 = copy.deepcopy(later)
    later_v1["extra"] = {"mosael": {"version": 1, "app": {"title": "晚升级的", "description": "", "graph_items": {}}}}
    next(one for one in later_v1["nodes"] if one["id"] == 6)["properties"] = {
        "mosael": {"expose": {"text": {"order": 0, "main": True}}}}
    comfy.state.workflows["later.json"] = later_v1
    with SessionLocal() as db:
        db.add(GenerationSession(workspace_id=ids["ws"], owner_user_id=user_id(), provider_profile_id=ids["profile"],
                                 model="later.json", kind="image", title="晚升级那张的老会话"))
        db.commit()
    _refresh(client, ids["instance"])
    with SessionLocal() as db:
        sessions = {one.title: one.model for one in db.scalars(
            select(GenerationSession).where(GenerationSession.workspace_id == ids["ws"]))}
        assert sessions["晚升级那张的老会话"] == "later.json", "还是上一版格式:插件不报它的改名,不动"
        assert db.get(PluginInstance, ids["instance"]).applied_moves["generation"] == {"form-entries": ["portrait.json"]}

    # 后来升级了(改写成第 2 版,id 是 app 的那张照报改名)
    comfy.state.workflows["later.json"] = _formed(later)
    _refresh(client, ids["instance"])
    with SessionLocal() as db:
        sessions = {one.title: one.model for one in db.scalars(
            select(GenerationSession).where(GenerationSession.workspace_id == ids["ws"]))}
        assert sessions["晚升级那张的老会话"] == "later.json#app", "同一个 key 下晚报上来的旧名字照样改一次"
        assert db.scalar(select(GenerationSession.model).where(GenerationSession.workspace_id == ids["ws"],
                                                               GenerationSession.title != "晚升级那张的老会话")) \
            == "portrait.json#app", "先改过的不再改"
        moves = db.get(PluginInstance, ids["instance"]).applied_moves
        assert moves["generation"] == {"form-entries": ["later.json", "portrait.json"]}
        assert sorted(moves["tools"]["form-entries"]) == sorted([FULL_TOOL, "wf_b2f4c3e81111"])


def test_老账只按_key_记的_迁成按旧名字记_那时有的名字都算做过_再跑一次不变(upgraded) -> None:
    """迁移(PLG-2):老账 `{"generation": ["form-entries"]}` 没说做了哪几个名字。那一次是按当时插件报的全部名字做的,所以换成这个
    连接现在有的全部名字(模型行的 id、存着的工具名)—— 之后特意选的完整工作流不会因为换了记账的形状被改走。"""
    from app.db.migrations import _migrate_applied_moves_remember_old_names

    client, _, ids = upgraded
    _refresh(client, ids["instance"])
    with engine.begin() as conn:
        conn.execute(text("UPDATE plugin_instances SET applied_moves = :m WHERE id = :i"),
                     {"m": '{"generation": ["form-entries"], "tools": ["form-entries"]}', "i": ids["instance"]})
    with SessionLocal() as db:
        session = GenerationSession(workspace_id=ids["ws"], owner_user_id=user_id(), provider_profile_id=ids["profile"],
                                    model="portrait.json", kind="image", title="之后特意选的完整工作流")
        db.add(session)
        db.commit()
        session_id = session.id
        models = sorted(db.scalars(select(ProviderModel.model_id).where(ProviderModel.provider_profile_id == ids["profile"])))
        tools = sorted({tool["name"] for tool in db.get(PluginInstance, ids["instance"]).discovered_tools})

    _migrate_applied_moves_remember_old_names()
    with SessionLocal() as db:
        moves = db.get(PluginInstance, ids["instance"]).applied_moves
    assert moves == {"generation": {"form-entries": models}, "tools": {"form-entries": tools}}
    assert "portrait.json" in models and FULL_TOOL in tools

    _refresh(client, ids["instance"])
    with SessionLocal() as db:
        assert db.get(GenerationSession, session_id).model == "portrait.json", "那时有的名字算做过:不再改"
    _migrate_applied_moves_remember_old_names()
    with SessionLocal() as db:
        assert db.get(PluginInstance, ids["instance"]).applied_moves == moves, "已经是新形状:再跑一次不变"
