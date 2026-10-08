"""一张工作流几张表单(ADR 0045 第二步)在宿主这一侧,对着假 ComfyUI 走真插件:

- 上一版格式的文件:目录里没有它的表单入口;从没有到有的那一次给连接的主人发一条通知(不是每次刷新都发);指着 `#app` 的
  格子跑的时候照插件说的那句说清楚「到工作流库里升级」,不说「模型不存在」;
- 「查看并升级」:宿主交给插件逐张改,改完目录马上重拉 —— 表单入口出来,从 1.20 之前直接升上来的老引用照样改到表单入口
  (这个连接没做过这一批改名就做一次);
- 几张表单:每张一项生成选项、挨在完整工作流后面;删表单前数「这个工作区里有几处在用它」(画板、工作流、AI Studio 会话)。
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import (
    Board, GenerationSession, Notification, PluginInstance, ProviderModel, ProviderProfile, ScheduledTask,
)
from app.domain.providers import defaults as provider_defaults
from tests.fake_comfyui import PORTRAIT_ID, FakeComfyUI, comfyui_grants
from tests.test_plugin_dynamic_tools import _workflow
from tests.util import fresh_client, user_id

PACKAGE = "dev.mosael.comfyui"
VENDOR = f"plugin:{PACKAGE}"
FULL_TOOL = "wf_" + PORTRAIT_ID.replace("-", "")[:12]


def _v1(ui: dict[str, Any]) -> dict[str, Any]:
    """1.20 之前存的样子:图上 `{"version": 1, "app": …}`,节点上 `expose`。"""
    stored = copy.deepcopy(ui)
    stored["extra"] = {"mosael": {"version": 1, "app": {"title": "快速出图", "description": "", "graph_items": {}}}}
    next(one for one in stored["nodes"] if one["id"] == 6)["properties"] = {
        "mosael": {"expose": {"text": {"order": 0, "main": True}}}}
    return stored


def _connect(client, comfy) -> str:
    created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": comfy.url}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    return instance_id


def _options(client) -> dict[str, dict[str, Any]]:
    return {one["model"]: one for one in client.get("/api/generation/options?kind=image").json()
            if one["provider"] == VENDOR}


def _profile_id(instance_id: str) -> str:
    with SessionLocal() as db:
        return db.scalar(select(ProviderProfile.id).where(ProviderProfile.plugin_instance_id == instance_id))


@pytest.fixture
def old_library():
    """一台 ComfyUI 上存着 1.20 之前的文件,一个工作区里有指着它旧名字的生成会话。"""
    with FakeComfyUI() as comfy:
        comfy.state.workflows["portrait.json"] = _v1(comfy.state.workflows["portrait.json"])
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        instance_id = _connect(client, comfy)
        yield client, comfy, instance_id, ws


def test_旧格式_没有表单入口_通知只发一次_指着app的说清楚去升级(old_library) -> None:
    client, comfy, instance_id, ws = old_library
    assert set(_options(client)) == {"builtin:txt2img", "portrait.json"}, "上一版的表单这一版不读:只有完整工作流"
    with SessionLocal() as db:
        status = db.get(PluginInstance, instance_id).capability_status["generation"]
        assert status["library_upgrades"] == 1
        notes = db.scalars(select(Notification).where(Notification.workspace_id == ws)).all()
    assert [(one.type, one.link) for one in notes] == [("system", "#/plugins")], "从没有到有:告诉连接的主人一次"
    assert "1 张工作流" in notes[0].body and "查看并升级" in notes[0].body
    assert client.post(f"/api/plugins/instances/{instance_id}/refresh").status_code == 200
    with SessionLocal() as db:
        assert len(db.scalars(select(Notification).where(Notification.workspace_id == ws)).all()) == 1, "不是每次刷新都发"

    profile_id = _profile_id(instance_id)
    created = client.post("/api/generation/jobs", json={
        "workspace_id": ws, "kind": "image", "provider": VENDOR, "provider_profile_id": profile_id,
        "model": "portrait.json#app", "prompt": "柴犬"})
    assert created.status_code == 422, created.text
    said = str(created.json()["detail"])
    assert "旧格式" in said and "工作流库" in said and "升级" in said, "不说「模型未启用或不存在」"
    assert "portrait 的表单" in said and "#app" not in said, "说的是人话的名字,不是编号"
    missing = client.get("/api/generation/missing", params={
        "provider_profile_id": profile_id, "model": "portrait.json#app", "kind": "image"}).json()
    assert missing["model_label"] == "portrait 的表单" and missing["upgrade"] is True
    assert missing["group"]["label"] == "portrait" and missing["group"]["entry"] == "form"
    assert missing["plugin_instance_id"] == instance_id and "查看并升级" in missing["reason"]

    listed = client.get(f"/api/plugins/instances/{instance_id}/workflow-library").json()
    flow = next(one for one in listed["workflows"] if one["path"] == "portrait.json")
    assert flow["app"]["status"] == "unsupported" and flow["app"]["upgradable"] is True


def test_查看并升级_改完表单入口出来_老引用改到表单入口(old_library) -> None:
    client, comfy, instance_id, ws = old_library
    profile_id = _profile_id(instance_id)
    with SessionLocal() as db:
        db.add(GenerationSession(workspace_id=ws, owner_user_id=user_id(), provider_profile_id=profile_id,
                                 model="portrait.json", kind="image", title="升级前就在用的"))
        db.commit()
    listed = client.get(f"/api/plugins/instances/{instance_id}/workflow-library").json()
    paths = [{"path": one["path"], "modified": one["modified"]} for one in listed["workflows"] if one["app"]
             and one["app"]["upgradable"]]
    done = client.post(f"/api/plugins/instances/{instance_id}/workflow-library/upgrade-marks", json={"paths": paths})
    assert done.status_code == 200, done.text
    assert done.json()["upgraded"] == ["portrait.json"]
    stored = comfy.state.workflows["portrait.json"]
    assert stored["extra"]["mosael"]["version"] == 2 and stored["extra"]["mosael"]["forms"][0]["id"] == "app"
    options = _options(client)
    assert {"portrait.json", "portrait.json#app"} <= set(options)
    with SessionLocal() as db:
        assert db.scalar(select(GenerationSession.model).where(GenerationSession.workspace_id == ws)) == \
            "portrait.json#app", "从 1.20 之前直接升上来的:改写之后照样做一次改名"
        instance = db.get(PluginInstance, instance_id)
        assert instance.applied_moves == {"generation": {"form-entries": ["portrait.json"]},
                                          "tools": {"form-entries": [FULL_TOOL]}}, "按 key 和旧名字记账(PLG-2)"
        assert instance.capability_status["generation"]["library_upgrades"] == 0


@pytest.fixture
def formed():
    with FakeComfyUI() as comfy:
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        instance_id = _connect(client, comfy)
        app = client.get(f"/api/plugins/instances/{instance_id}/workflow-library/app",
                         params={"path": "portrait.json"}).json()
        saved = client.post(f"/api/plugins/instances/{instance_id}/workflow-library/annotate", json={
            "path": "portrait.json", "modified": app["modified"], "results": [], "forms": [
                {"title": "快速出图", "items": [{"node": "6", "input": "text", "main": True}]},
                {"title": "精调", "items": [{"node": "6", "input": "text", "main": True}, {"node": "3", "input": "steps"}]},
            ]})
        assert saved.status_code == 200, saved.text
        yield client, comfy, instance_id, ws


def test_几张表单各是一项_挨在完整工作流后面(formed) -> None:
    client, comfy, instance_id, _ = formed
    ids = [one["id"] for one in comfy.state.workflows["portrait.json"]["extra"]["mosael"]["forms"]]
    options = client.get("/api/generation/options?kind=image").json()
    mine = [one["model"] for one in options if one["provider"] == VENDOR]
    assert mine == ["builtin:txt2img", "portrait.json", *(f"portrait.json#{one}" for one in ids)]
    by_model = {one["model"]: one for one in options}
    assert [by_model[f"portrait.json#{one}"]["model_label"] for one in ids] == ["快速出图", "精调"]
    assert all(by_model[f"portrait.json#{one}"]["group"]["entry"] == "form" for one in ids)


def test_删表单之前_数这个工作区里有几处在用它(formed) -> None:
    client, _, instance_id, ws = formed
    app = client.get(f"/api/plugins/instances/{instance_id}/workflow-library/app", params={"path": "portrait.json"}).json()
    fine = app["app"]["forms"][1]
    assert fine["model"].startswith("portrait.json#") and fine["tool"] == f"{FULL_TOOL}_{fine['id']}"
    profile_id = _profile_id(instance_id)
    with SessionLocal() as db:
        db.add(Board(workspace_id=ws, name="海报", revision=1, canvas={"edges": [], "items": [
            {"id": "a", "kind": "image", "x": 0, "y": 0, "w": 1, "h": 1,
             "form": {"provider": VENDOR, "provider_profile_id": profile_id, "model": fine["model"]}},
            {"id": "b", "kind": "image", "x": 0, "y": 0, "w": 1, "h": 1,
             "form": {"provider": VENDOR, "provider_profile_id": profile_id, "model": fine["model"]}},
            {"id": "c", "kind": "image", "x": 0, "y": 0, "w": 1, "h": 1,
             "form": {"provider": VENDOR, "provider_profile_id": profile_id, "model": "portrait.json"}},
        ]}))
        db.add(GenerationSession(workspace_id=ws, owner_user_id=user_id(), provider_profile_id=profile_id,
                                 model=fine["model"], kind="image", title="调步数"))
        # PLG-6:定时任务、设置里的默认模型也存着这个 id —— 此前删之前不数它们,删了才到点失败
        db.add(ScheduledTask(workspace_id=ws, owner_user_id=user_id(), name="每天一张", kind="generation",
                             trigger_type="cron", payload={"provider_profile_id": profile_id, "model": fine["model"],
                                                           "prompt": "柴犬"}))
        db.add(ScheduledTask(workspace_id=ws, owner_user_id=user_id(), name="选完整工作流的", kind="generation",
                             trigger_type="cron", payload={"provider_profile_id": profile_id, "model": "portrait.json"}))
        row = db.scalar(select(ProviderModel).where(ProviderModel.provider_profile_id == profile_id,
                                                    ProviderModel.model_id == fine["model"]))
        provider_defaults.set_default(db, "image", row, owner_user_id=user_id())
        db.commit()
    _workflow(ws, {"nodes": [
        {"id": "start", "type": "start", "config": {}},
        {"id": "tool", "type": f"plugin.{PACKAGE}.{fine['tool']}", "config": {"instance_id": "", "prompt": "柴犬"}},
        {"id": "other", "type": f"plugin.{PACKAGE}.{FULL_TOOL}", "config": {"instance_id": "", "prompt": "柴犬"}},
    ], "edges": []})
    used = client.get(f"/api/plugins/instances/{instance_id}/workflow-library/form-usages",
                      params={"workspace_id": ws, "model": fine["model"], "tool": fine["tool"]})
    assert used.status_code == 200, used.text
    assert [(one["kind"], one["name"], one["count"]) for one in used.json()["uses"]] == [
        ("board", "海报", 2), ("workflow", "老节点", 1), ("session", "调步数", 1), ("task", "每天一张", 1),
        ("default", "image", 1)], "完整工作流的那几处不算"
    other = client.get(f"/api/plugins/instances/{instance_id}/workflow-library/form-usages",
                       params={"workspace_id": "nope", "model": fine["model"], "tool": fine["tool"]})
    assert other.status_code in (403, 404), "别的工作区不让查"
