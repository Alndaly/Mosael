"""ComfyUI 插件在宿主里:随应用装好,接一台(假的)ComfyUI,它的工作流就是选择器里的模型,
一次带参考图的生成走普通的生成执行器,从头到尾(见 ADR 0020)。

插件自己的行为在 test_comfyui_plugin_run.py;这里钉的是**装配**:随包装好且卸不掉、连接→模型、
模型的参数描述符到了选择器、提交时参考图从素材库拷出去再传给 ComfyUI、产出进素材库、回执落库。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import GeneratedAsset, Job, ProviderProfile
from tests.fake_comfyui import PNG, FakeComfyUI
from tests.util import fresh_client, wait_status

PACKAGE = "dev.mosael.comfyui"
VENDOR = f"plugin:{PACKAGE}"


@pytest.fixture
def connected():
    with FakeComfyUI() as comfy:
        client = fresh_client()
        created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": comfy.url}})
        assert created.status_code == 200, created.text
        instance_id = created.json()["id"]
        client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": {"network:comfyui": True}})
        enabled = client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True})
        assert enabled.status_code == 200, enabled.text
        yield client, comfy, instance_id


def _options(client, kind: str) -> dict[str, dict]:
    return {one["model"]: one for one in client.get(f"/api/generation/options?kind={kind}").json() if one["provider"] == VENDOR}


def test_随应用装好_卸不掉() -> None:
    client = fresh_client()
    package = next(one for one in client.get("/api/plugins").json() if one["id"] == PACKAGE)
    assert package["bundled"] is True and package["provides"] == ["generation"]
    assert package["config_fields"][0]["default"] == "http://127.0.0.1:8188"
    assert package["config_fields"][1]["multiline"] is True
    assert client.delete(f"/api/plugins/{PACKAGE}").status_code == 404


def test_每张保存的工作流都是选择器里的一个模型(connected) -> None:
    client, _, instance_id = connected
    images = _options(client, "image")
    assert set(images) == {"builtin:txt2img", "portrait.json"}
    portrait = images["portrait.json"]
    assert portrait["label"].endswith("· portrait")
    caps = portrait["capabilities"]
    assert caps["sizes"][0] == "832x1216" and caps["default_size"] == "832x1216"
    assert caps["source_limits"] == {"reference_image": 1}
    assert caps["parameter_schema"]["3.steps"]["title"] == "采样 · steps"
    assert caps["prompt_dialect"] == "sd-tags"
    assert set(_options(client, "video")) == {"video/wan.json"}
    status = client.get("/api/plugins").json()
    instance = next(one for one in status if one["id"] == PACKAGE)["instances"][0]
    assert instance["capability_status"]["generation"]["models"] == 3


def test_带参考图的一次生成从头到尾(connected) -> None:
    client, comfy, instance_id = connected
    workspace = client.post("/api/workspaces", json={"name": "ComfyUI"}).json()["id"]
    reference = client.post(
        "/api/assets/import", data={"workspace_id": workspace}, files={"file": ("参考.png", PNG, "image/png")}
    ).json()["id"]
    with SessionLocal() as db:
        profile_id = db.scalar(select(ProviderProfile.id).where(ProviderProfile.plugin_instance_id == instance_id))
    submitted = client.post("/api/generation/jobs", json={
        "workspace_id": workspace, "session_id": None, "project_id": None,
        "provider_profile_id": profile_id, "provider": VENDOR, "model": "portrait.json", "kind": "image",
        "prompt": "海边的柴犬", "negative_prompt": "模糊",
        "parameters": {"seed": 3, "3.steps": 12, "3.sampler_name": "dpmpp_2m"},
        "source_assets": [{"asset_id": reference, "role": "reference_image"}],
    })
    assert submitted.status_code == 200, submitted.text
    job_id = submitted.json()["job"]["id"]
    assert wait_status(client, job_id, timeout=60) == "succeeded"

    [(uploaded, content)] = comfy.state.uploads
    assert content == PNG
    prompt = comfy.posted("/prompt")[0]["prompt"]
    assert prompt["10"]["inputs"]["image"] == f"mosael/{uploaded}"
    assert prompt["3"]["inputs"]["steps"] == 12 and prompt["3"]["inputs"]["sampler_name"] == "dpmpp_2m"
    assert prompt["7"]["inputs"]["text"] == "模糊"
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert json.loads(job.payload["remote_task"]["poll_path"])["prompt_id"] == "p1"
        [asset_id] = job.result["asset_ids"]
        assert db.get(GeneratedAsset, asset_id).provider == VENDOR


def test_换一台服务器_模型跟着换(connected) -> None:
    client, comfy, instance_id = connected
    comfy.state.workflows = {"only.json": comfy.state.workflows["portrait.json"]}
    refreshed = client.post(f"/api/plugins/instances/{instance_id}/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert set(_options(client, "image")) == {"builtin:txt2img", "only.json"}
    assert _options(client, "video") == {}, "ComfyUI 里删掉的工作流不留在选择器里"
