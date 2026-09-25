"""`migrate-comfyui-connections-become-plugin-instances`:内核里的 ComfyUI 连接搬成 ComfyUI 插件的连接(ADR 0020)。

喂它一份升级前的样子 —— 两台 ComfyUI(一台粘过 API 模板,一台没有),假模型 `workflow` 当默认模型,
指向旧目录档案的参数声明,选过保存的工作流的生成任务、画板格子、工作流节点(连同循环体)、
定时任务、生成会话、产出记录与用量 —— 看它搬成新写法,再跑一次什么都不动。
"""

from __future__ import annotations

import json

from sqlalchemy import select, text

from app.core.db import SessionLocal, engine
from app.db.migrations import _migrate_comfyui_connections_become_plugin_instances as migrate
from app.db.models import (
    Board,
    GeneratedAsset,
    GenerationCapabilityDeclaration,
    GenerationJob,
    GenerationSession,
    Job,
    PluginInstance,
    PluginPermissionGrant,
    ProviderDefault,
    ProviderModel,
    ProviderProfile,
    ProviderUsageEvent,
    ScheduledTask,
    Workflow,
    WorkflowRevision,
    WorkflowRevisionAttestation,
)
from app.domain.workflows.revisions import current_workflow_revision
from tests.fake_comfyui import PNG
from tests.util import fresh_client, second_client, user_id

VENDOR = "plugin:dev.mosael.comfyui"
TEMPLATE = json.dumps({"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "{{prompt}}"}}})


def _ai_generate(profile_id: str, **config) -> dict:
    return {"id": "gen", "type": "ai_generate", "position": {"x": 0, "y": 0},
            "config": {"provider": "comfyui", "provider_profile_id": profile_id, "kind": "image", **config}}


def _legacy(client) -> dict:
    """升级前的库。返回测试要用的 id。"""
    me, mate = user_id("tester"), user_id("mate")
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    asset_id = client.post("/api/assets/import", data={"workspace_id": workspace},
                           files={"file": ("x.png", PNG, "image/png")}).json()["id"]
    board_id = client.post("/api/boards", json={"workspace_id": workspace, "name": "B"}).json()["id"]
    workflow_id = client.post("/api/workflows", json={"workspace_id": workspace, "name": "WF"}).json()["id"]
    with SessionLocal() as db:
        plain = ProviderProfile(owner_user_id=me, name="本机 ComfyUI", vendor="comfyui",
                                base_url="http://127.0.0.1:8188", auth_type="api_key", extra={}, enabled=True)
        templated = ProviderProfile(owner_user_id=mate, name="GPU 机", vendor="comfyui", base_url="",
                                    auth_type="api_key", extra={"workflow_template": TEMPLATE}, enabled=False)
        db.add_all([plain, templated])
        db.flush()
        workflow_row = ProviderModel(provider_profile_id=plain.id, model_id="workflow", capability_ids=["image"],
                                     source="catalog", generation_capability_ref="profile:comfyui-image")
        video_row = ProviderModel(provider_profile_id=plain.id, model_id="video-flow", capability_ids=["video"],
                                  source="manual")
        mate_row = ProviderModel(provider_profile_id=templated.id, model_id="workflow", capability_ids=["image"])
        db.add_all([workflow_row, video_row, mate_row])
        db.flush()
        db.add(GenerationCapabilityDeclaration(provider_model_id=video_row.id, kind="video",
                                               catalog_ref="profile:comfyui-video"))
        db.add(ProviderDefault(capability="image", owner_user_id=me, provider_model_id=workflow_row.id))
        request = {"prompt": "猫", "parameters": {"workflow": "portrait.json", "workflow_params": {"3": {"steps": 30}},
                                                  "seed": 7}}
        job = Job(workspace_id=workspace, kind="ai_generation", status="succeeded", created_by=me,
                  payload={"provider": "comfyui", "provider_profile_id": plain.id, "model": "workflow",
                           "kind": "image", "request": request})
        db.add(job)
        db.flush()
        db.add(GenerationJob(workspace_id=workspace, job_id=job.id, provider_profile_id=plain.id, provider="comfyui",
                             model="workflow", kind="image", request=request))
        db.add(GeneratedAsset(asset_id=asset_id, provider="comfyui", model="workflow", prompt="猫", parameters={}))
        db.add(ProviderUsageEvent(workspace_id=workspace, provider_profile_id=plain.id, provider="comfyui",
                                  model="workflow", capability="image", operation="generation_job", units={},
                                  idempotency_key="generation:legacy"))
        db.add(GenerationSession(workspace_id=workspace, title="会话", provider_profile_id=templated.id,
                                 model="workflow", kind="image", owner_user_id=mate))
        db.add(ScheduledTask(workspace_id=workspace, owner_user_id=me, name="每天一张", kind="generation",
                             trigger_type="interval", payload={"provider": "comfyui", "provider_profile_id": plain.id,
                                                               "model": "workflow", "kind": "image", "prompt": "猫"}))
        board = db.get(Board, board_id)
        board.canvas = {"items": [
            {"id": "i1", "kind": "image", "x": 0, "y": 0,
             "form": {"prompt": "猫", "provider": "comfyui", "provider_profile_id": plain.id, "model": "workflow",
                      "parameters": {"workflow": "portrait.json"}}},
            {"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "不相干"},
        ]}
        db.commit()
        ids = {"plain": plain.id, "templated": templated.id, "workflow_row": workflow_row.id,
               "video_row": video_row.id, "job": job.id, "board": board_id, "workflow": workflow_id,
               "workspace": workspace, "board_revision": board.revision}
    graph = {"nodes": [
        _ai_generate(ids["plain"], model="workflow", parameters={"workflow": "flows/a.json",
                                                                  "workflow_params": {"5": {"cfg": 6.5}}}),
        {"id": "loop", "type": "loop", "position": {"x": 0, "y": 0}, "config": {"body": {"nodes": [
            _ai_generate(ids["templated"], model="workflow", parameters={}),
        ], "edges": []}}},
    ], "edges": []}
    # 老版本存下的图(界面那条路今天存不进 provider=comfyui 了):直接落库,再让修订对上,作者是我。
    from app.db.migrations import _migrate_workflow_revisions

    with engine.begin() as conn:
        conn.execute(text("UPDATE workflows SET graph = :g WHERE id = :id"),
                     {"g": json.dumps(graph, ensure_ascii=False), "id": workflow_id})
    _migrate_workflow_revisions()
    with SessionLocal() as db:
        latest = current_workflow_revision(db, db.get(Workflow, workflow_id))
        latest.created_by = me
        db.add(WorkflowRevisionAttestation(revision_id=latest.id, user_id=mate))
        db.commit()
        ids["revisions"] = db.query(WorkflowRevision).filter_by(workflow_id=workflow_id).count()
    return ids


def test_ComfyUI连接搬成插件连接_引用改成新写法_再跑一次什么都不动() -> None:
    client = fresh_client()
    second_client("mate")
    ids = _legacy(client)

    migrate()

    with SessionLocal() as db:
        plain = db.get(ProviderProfile, ids["plain"])
        templated = db.get(ProviderProfile, ids["templated"])
        # 连接 id 不变,原地改成插件连接;实例归同一个人,地址和模板搬进配置,权限直接授予
        for profile, owner in ((plain, user_id("tester")), (templated, user_id("mate"))):
            assert profile.vendor == VENDOR and profile.plugin_instance_id and profile.base_url == ""
            instance = db.get(PluginInstance, profile.plugin_instance_id)
            assert instance.owner_user_id == owner and instance.package_id == "dev.mosael.comfyui"
            assert db.get(PluginPermissionGrant, {"instance_id": instance.id, "permission": "network:comfyui"}).granted
        assert db.get(PluginInstance, plain.plugin_instance_id).config == {
            "server_url": "http://127.0.0.1:8188", "api_workflow": ""}
        mate_instance = db.get(PluginInstance, templated.plugin_instance_id)
        assert mate_instance.config == {"server_url": "http://127.0.0.1:8188", "api_workflow": TEMPLATE}
        assert mate_instance.enabled is False, "停用的连接搬过去还是停用的"

        # 假模型 workflow:没模板的图像 → 内置文生图(行 id 不变,默认模型跟着);有模板的 → API 模板
        assert db.get(ProviderModel, ids["workflow_row"]).model_id == "builtin:txt2img"
        assert db.get(ProviderModel, ids["workflow_row"]).generation_capability_ref is None
        assert db.get(ProviderDefault, {"capability": "image", "owner_user_id": user_id("tester")}).provider_model_id == ids["workflow_row"]
        models = {row.model_id for row in db.scalars(select(ProviderModel).where(ProviderModel.provider_profile_id == templated.id))}
        assert "api-workflow" in models
        # 指向旧档案的声明删掉了;引用到的工作流补了模型行,插件目录刷新时再对齐
        assert db.scalars(select(GenerationCapabilityDeclaration)).all() == []
        plain_models = {row.model_id: row for row in db.scalars(select(ProviderModel).where(ProviderModel.provider_profile_id == plain.id))}
        assert {"portrait.json", "flows/a.json", "video-flow"} <= set(plain_models)
        assert plain_models["portrait.json"].source == "plugin" and plain_models["portrait.json"].capability_ids == ["image"]

        # 生成任务、回执:保存的工作流就是模型,动态参数拍平成 <节点>.<输入>
        generation = db.scalars(select(GenerationJob)).one()
        assert (generation.provider, generation.model) == (VENDOR, "portrait.json")
        assert generation.request["parameters"] == {"seed": 7, "3.steps": 30}
        payload = db.get(Job, ids["job"]).payload
        assert (payload["provider"], payload["model"]) == (VENDOR, "portrait.json")
        assert payload["request"]["parameters"] == {"seed": 7, "3.steps": 30}
        assert db.scalars(select(GeneratedAsset)).one().provider == VENDOR
        assert db.scalars(select(ProviderUsageEvent)).one().provider == VENDOR
        assert db.scalars(select(GenerationSession)).one().model == "api-workflow"
        task = db.scalars(select(ScheduledTask)).one().payload
        assert (task["provider"], task["model"]) == (VENDOR, "builtin:txt2img")

        # 画板:生成格改了、别的格不动,revision 往前走(开着的页面下一次保存会先拿到新的)
        board = db.get(Board, ids["board"])
        item = board.canvas["items"][0]["form"]
        assert (item["provider"], item["model"], item["parameters"]) == (VENDOR, "portrait.json", {})
        assert board.canvas["items"][1] == {"id": "n1", "kind": "note", "x": 0, "y": 0, "text": "不相干"}
        assert board.revision == ids["board_revision"] + 1

        # 工作流:连循环体一起改;追加一版修订,作者与认可人沿用上一版(机械改写不换担保人)
        workflow = db.get(Workflow, ids["workflow"])
        top = workflow.graph["nodes"][0]["config"]
        assert (top["provider"], top["model"], top["parameters"]) == (VENDOR, "flows/a.json", {"5.cfg": 6.5})
        inner = workflow.graph["nodes"][1]["config"]["body"]["nodes"][0]["config"]
        assert (inner["provider"], inner["model"]) == (VENDOR, "api-workflow")
        latest = current_workflow_revision(db, workflow)
        assert latest.graph == workflow.graph and latest.source == "migration"
        assert latest.created_by == user_id("tester")
        attesters = {row.user_id for row in db.scalars(select(WorkflowRevisionAttestation).where(
            WorkflowRevisionAttestation.revision_id == latest.id))}
        assert attesters == {user_id("mate")}
        revisions = db.query(WorkflowRevision).filter_by(workflow_id=ids["workflow"]).count()
        assert revisions == ids["revisions"] + 1
        instances = db.query(PluginInstance).count()

    # 再跑一次:没有 comfyui 连接、也没有 comfyui 的引用了 —— 什么都不动
    migrate()
    with SessionLocal() as db:
        assert db.query(PluginInstance).count() == instances
        assert db.query(WorkflowRevision).filter_by(workflow_id=ids["workflow"]).count() == revisions
        assert db.get(Board, ids["board"]).revision == ids["board_revision"] + 1


def test_没有模板的视频工作流保持原样_运行时说清楚() -> None:
    """没粘模板的视频原来就跑不了(没有内置视频图):不编一个去处,留给运行时报「这个模型不可用」。"""
    client = fresh_client()
    with SessionLocal() as db:
        profile = ProviderProfile(owner_user_id=user_id("tester"), name="C", vendor="comfyui", base_url="",
                                  auth_type="api_key", extra={}, enabled=True)
        db.add(profile)
        db.flush()
        db.add(ProviderModel(provider_profile_id=profile.id, model_id="workflow", capability_ids=["video"]))
        db.commit()
        profile_id = profile.id
    migrate()
    with SessionLocal() as db:
        assert [row.model_id for row in db.scalars(select(ProviderModel).where(
            ProviderModel.provider_profile_id == profile_id))] == ["workflow"]
    assert client  # 只为初始化


def test_没有ComfyUI连接的库什么都不动() -> None:
    fresh_client()
    with engine.begin() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM plugin_instances")).scalar()
    migrate()
    with engine.begin() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM plugin_instances")).scalar() == before
