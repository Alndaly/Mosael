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
    assert package["bundled"] is True and package["provides"] == ["generation", "tools"]
    assert package["config_fields"][0]["default"] == "http://127.0.0.1:8188"
    template = package["config_fields"][1]
    assert (template["type"], template["language"]) == ("json", "json"), "API 模板是一段 JSON:代码编辑器 + 保存前校验"
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
    assert caps["parameter_schema"]["3.steps"]["title"] == "步数"
    assert caps["max_num_images"] == 4, "工作流的画布有 batch_size:一次最多出 4 张"
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


def test_参数的名字按看的人的语言说(connected) -> None:
    """目录在后台刷新(刷新那一刻的语言不是看的人的),名字存成按语言分的,给人看时再挑。"""
    client, _, _ = connected
    options = client.get("/api/generation/options?kind=image", headers={"Accept-Language": "en-US"}).json()
    portrait = next(one for one in options if one["provider"] == VENDOR and one["model"] == "portrait.json")
    schema = portrait["capabilities"]["parameter_schema"]
    assert schema["3.steps"]["title"] == "Steps" and schema["4.ckpt_name"]["title"] == "Checkpoint"
    assert schema["3.steps"]["description"] == "采样 · steps", "原始的「节点 · 输入名」照旧给排错用"


def test_插件页列出提供的模型(connected) -> None:
    client, _, instance_id = connected
    models = {one["id"]: one for one in client.get(f"/api/plugins/instances/{instance_id}/models").json()}
    assert set(models) == {"builtin:txt2img", "portrait.json", "video/wan.json"}
    portrait = models["portrait.json"]
    assert portrait["kind"] == "image" and portrait["modes"] == ["text-to-image", "image-to-image"]
    assert portrait["inputs"] == [{"role": "reference_image", "max": 1, "required": False}]
    assert "size" in portrait["host_parameters"] and "num_images" in portrait["host_parameters"]
    assert {"key": "3.steps", "title": "步数", "type": "integer", "advanced": False} in portrait["parameters"]
    assert models["video/wan.json"]["inputs"] == [{"role": "first_frame", "max": 1, "required": False}]


def test_工具出现在插件页_智能体和工作流里(connected) -> None:
    """这个插件此前只替宿主做生成,插件页上一个工具都没有。现在工具在勾选表里,按 recommended 预勾。"""
    client, _, instance_id = connected
    package = next(one for one in client.get("/api/plugins").json() if one["id"] == PACKAGE)
    tools = {one["name"]: one for one in package["instances"][0]["tools"]}
    assert "comfyui_generation" not in tools, "认领生成的那个工具只给宿主调"
    fixed = {name for name in tools if not name.startswith("wf_")}
    assert fixed == {"list_workflows", "run_workflow", "import_outputs", "server_status", "list_models",
                     "interrupt", "clear_queue", "free_memory"}
    assert {name for name in fixed if tools[name]["exposed"]} == {
        "list_workflows", "import_outputs", "server_status", "list_models", "interrupt"}, (
        "清队列、释放显存会动到同一台机器上别人的活:默认不开;run_workflow 让位给每张工作流自己的工具"
    )
    assert all(tool["exposed"] for name, tool in tools.items() if name.startswith("wf_"))
    assert tools["list_workflows"]["read_only"] is True and tools["run_workflow"]["read_only"] is False
    exposed = {one["name"] for one in client.get("/api/plugins/tools").json() if one["instance_id"] == instance_id}
    assert "list_workflows" in exposed and "clear_queue" not in exposed


def test_运行工作流_全部产出进素材库(connected) -> None:
    from tests.fake_comfyui import UPSCALE_API

    client, comfy, instance_id = connected
    comfy.state.workflows["upscale.json"] = UPSCALE_API
    comfy.state.outputs = {"4": {"images": [{"filename": "u1.png", "type": "output"}, {"filename": "u2.png", "type": "output"}]}}
    workspace = client.post("/api/workspaces", json={"name": "ComfyUI 工具"}).json()["id"]
    source = client.post(
        "/api/assets/import", data={"workspace_id": workspace}, files={"file": ("原图.png", PNG, "image/png")}
    ).json()["id"]
    invoked = client.post(f"/api/plugins/instances/{instance_id}/tools/run_workflow/invoke", json={
        "workspace_id": workspace, "input": {"workflow": "upscale.json", "image": source},
    })
    assert invoked.status_code == 200, invoked.text
    body = invoked.json()
    assert body["status"] == "succeeded", body
    output = body["output"]
    assert "artifacts" not in output, "交出去的是素材 id,不是一次性的暂存路径"
    assert len(output["asset_ids"]) == 2 and output["asset_id"] == output["asset_ids"][0]
    assert [one["filename"] if "filename" in one else one["asset_name"] for one in output["assets"]] == ["u1.png", "u2.png"]
    assert output["assets"][0]["node"] == "4" and output["assets"][0]["media"] == "image"
    names = {one["id"]: one["name"] for one in client.get(f"/api/assets?workspace_id={workspace}").json()}
    assert {names[one] for one in output["asset_ids"]} == {"u1.png", "u2.png"}
    [(_, uploaded)] = comfy.state.uploads
    assert uploaded == PNG, "输入是素材库里那张图的副本"


def test_目录变了才重新拉_问指纹不留调用记录(connected) -> None:
    from app.db.models import PluginInvocation
    from app.domain.plugins import catalog_watch

    client, comfy, instance_id = connected
    with SessionLocal() as db:
        calls_before = db.query(PluginInvocation).filter_by(instance_id=instance_id).count()
    assert catalog_watch.check_for_changes() == 0, "什么都没变就不重新拉"
    comfy.state.workflows["fresh.json"] = comfy.state.workflows["portrait.json"]
    assert catalog_watch.check_for_changes() == 2, "模型目录和工具清单各刷一次"
    assert "fresh.json" in _options(client, "image"), "ComfyUI 里新存的工作流不用点刷新就出现"
    with SessionLocal() as db:
        rows = db.query(PluginInvocation).filter_by(instance_id=instance_id).all()
    assert len(rows) == calls_before + 2, "只有真的重新拉目录的那两次留记录;问指纹不留"
