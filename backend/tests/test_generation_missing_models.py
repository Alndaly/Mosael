"""记着的生成模型现在用不了(ADR 0045 修订之一):`GET /api/generation/missing` 说它叫什么、为什么不在、怎么修;生成的漏斗
在点名的那一对解析不出来时报同一句(画板、工作流节点、智能体、定时任务都从这里过)—— 不说笼统的「未启用或不存在」,也不露
`plugin:…`、`#app` 这种编号。

宿主自己说得出的:连接删了 / 停了、模型行删了 / 停了。插件连接问插件(ComfyUI:表单删了、工作流改名挪走删了、表单是旧格式);
插件这会儿问不到就退回宿主那句,名字写「之前选的模型」。
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import ProviderModel, ProviderProfile
from app.domain.providers import models as provider_models
from tests.fake_comfyui import FakeComfyUI, comfyui_grants
from tests.util import fresh_client

PACKAGE = "dev.mosael.comfyui"
VENDOR = f"plugin:{PACKAGE}"


@pytest.fixture(autouse=True)
def _generation_jobs_不外发(monkeypatch: pytest.MonkeyPatch):
    """只看建没建、拦没拦,不真跑(见 test_generation_declaration_paths 同名 fixture)。"""
    from app.domain import jobs as jobs_bus

    monkeypatch.setattr(jobs_bus, "_EXECUTION_MODES", {**jobs_bus._EXECUTION_MODES, "ai_generation": "external"})


def _missing(client, profile_id: str, model: str) -> dict[str, Any]:
    response = client.get("/api/generation/missing", params={"provider_profile_id": profile_id, "model": model, "kind": "image"})
    assert response.status_code == 200, response.text
    return response.json()


def _job(client, ws: str, profile_id: str, model: str, provider: str):
    return client.post("/api/generation/jobs", json={
        "workspace_id": ws, "kind": "image", "provider": provider, "provider_profile_id": profile_id, "model": model,
        "prompt": "柴犬"})


@pytest.fixture
def openai():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    profile_id = client.post("/api/settings/providers", json={
        "vendor": "openai", "name": "演示", "api_key": "sk-test", "base_url": "http://127.0.0.1:1"}).json()["id"]
    client.put(f"/api/settings/providers/{profile_id}/credential", json={"api_key": "sk-test"})
    with SessionLocal() as db:
        provider_models.upsert(db, db.get(ProviderProfile, profile_id), "gpt-image-2", source="manual",
                               capability_ids=["image"])
        db.commit()
    return client, ws, profile_id


def test_模型行删了_说连接上已经没有它_漏斗报同一句(openai) -> None:
    client, ws, profile_id = openai
    with SessionLocal() as db:
        db.delete(db.scalar(select(ProviderModel).where(ProviderModel.model_id == "gpt-image-2")))
        db.commit()
    missing = _missing(client, profile_id, "gpt-image-2")
    assert missing["model_label"] == "gpt-image-2" and missing["profile_name"] == "演示"
    assert "连接「演示」上已经没有它了" in missing["reason"] and missing["upgrade"] is False
    created = _job(client, ws, profile_id, "gpt-image-2", "openai")
    assert created.status_code == 422
    assert "「gpt-image-2」现在用不了" in str(created.json()["detail"]) and "已经没有它了" in str(created.json()["detail"])


def test_模型行停了_连接停了_连接删了_各说各的(openai) -> None:
    client, ws, profile_id = openai
    with SessionLocal() as db:
        db.scalar(select(ProviderModel).where(ProviderModel.model_id == "gpt-image-2")).enabled = False
        db.commit()
    assert "「gpt-image-2」在连接「演示」上停用了" in _missing(client, profile_id, "gpt-image-2")["reason"]
    with SessionLocal() as db:
        db.scalar(select(ProviderModel).where(ProviderModel.model_id == "gpt-image-2")).enabled = True
        db.get(ProviderProfile, profile_id).enabled = False
        db.commit()
    assert "连接「演示」现在用不了" in _missing(client, profile_id, "gpt-image-2")["reason"]
    assert client.delete(f"/api/settings/providers/{profile_id}").status_code in (200, 204)
    gone = _missing(client, profile_id, "gpt-image-2")
    assert gone["model_label"] == "之前选的模型" and gone["profile_name"] == "" and "连接已经删掉了" in gone["reason"]


def test_行在也开着_只是没被认成这种生成_说去标能力(openai) -> None:
    client, ws, profile_id = openai
    with SessionLocal() as db:
        provider_models.upsert(db, db.get(ProviderProfile, profile_id), "gpt-4o", source="manual", capability_ids=["chat"])
        db.commit()
    said = _missing(client, profile_id, "gpt-4o")
    assert said["model_label"] == "gpt-4o" and "没有标上「图像生成」能力" in said["reason"]


def _connect(client, comfy) -> str:
    created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": comfy.url}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    return instance_id


@pytest.fixture
def two_forms():
    """portrait.json 上两张表单(快速出图 = app、精调 = 插件起的 id)。"""
    with FakeComfyUI() as comfy:
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        instance_id = _connect(client, comfy)
        app = client.get(f"/api/plugins/instances/{instance_id}/workflow-library/app", params={"path": "portrait.json"}).json()
        saved = client.post(f"/api/plugins/instances/{instance_id}/workflow-library/annotate", json={
            "path": "portrait.json", "modified": app["modified"], "results": [], "forms": [
                {"id": "app", "title": "快速出图", "items": [{"node": "6", "input": "text", "main": True}]},
                {"title": "精调", "items": [{"node": "6", "input": "text", "main": True}, {"node": "3", "input": "steps"}]},
            ]})
        assert saved.status_code == 200, saved.text
        fine = comfy.state.workflows["portrait.json"]["extra"]["mosael"]["forms"][1]["id"]
        with SessionLocal() as db:
            profile_id = db.scalar(select(ProviderProfile.id).where(ProviderProfile.plugin_instance_id == instance_id))
        yield client, comfy, instance_id, ws, profile_id, fine


def test_删了一张表单_指着它的说表单没了_不顶替_漏斗报同一句(two_forms) -> None:
    client, comfy, instance_id, ws, profile_id, fine = two_forms
    app = client.get(f"/api/plugins/instances/{instance_id}/workflow-library/app", params={"path": "portrait.json"}).json()
    client.post(f"/api/plugins/instances/{instance_id}/workflow-library/annotate", json={
        "path": "portrait.json", "modified": app["modified"], "results": [],
        "forms": [{"id": "app", "title": "快速出图", "items": [{"node": "6", "input": "text", "main": True}]}]})
    assert client.post(f"/api/plugins/instances/{instance_id}/refresh").status_code == 200
    model = f"portrait.json#{fine}"
    missing = _missing(client, profile_id, model)
    assert missing["model_label"] == "portrait 的表单" and missing["group"]["label"] == "portrait"
    assert "已经没有这张表单了" in missing["reason"] and missing["upgrade"] is False
    created = _job(client, ws, profile_id, model, VENDOR)
    assert created.status_code == 422
    said = str(created.json()["detail"])
    assert "portrait 的表单" in said and "已经没有这张表单了" in said and "#" not in said and "plugin:" not in said


def test_工作流改了名_指着旧路径的说工作流不在了(two_forms) -> None:
    client, comfy, instance_id, ws, profile_id, fine = two_forms
    renamed = client.post(f"/api/plugins/instances/{instance_id}/workflow-library/rename",
                          json={"path": "portrait.json", "new_path": "归档/portrait.json"})
    assert renamed.status_code == 200, renamed.text
    assert client.post(f"/api/plugins/instances/{instance_id}/refresh").status_code == 200
    full = _missing(client, profile_id, "portrait.json")
    assert full["model_label"] == "portrait" and "已经没有工作流「portrait」了" in full["reason"]
    assert _missing(client, profile_id, "portrait.json#app")["model_label"] == "portrait 的表单"


def test_插件这会儿问不到_退回宿主那句_名字不露编号(two_forms) -> None:
    client, comfy, instance_id, ws, profile_id, fine = two_forms
    comfy.shutdown()
    comfy.server_close()
    missing = _missing(client, profile_id, "portrait.json#gone12")
    assert missing["model_label"] == "之前选的模型" and "已经没有它了" in missing["reason"]
