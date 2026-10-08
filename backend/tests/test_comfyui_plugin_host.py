"""ComfyUI 插件在宿主里:随应用装好,接一台(假的)ComfyUI,它的工作流就是选择器里的模型,
一次带参考图的生成走普通的生成执行器,从头到尾(见 ADR 0020)。

插件自己的行为在 test_comfyui_plugin_run.py;这里钉的是**装配**:随包装好且卸不掉、连接→模型、
模型的参数描述符到了选择器、提交时参考图从素材库拷出去再传给 ComfyUI、产出进素材库、回执落库。
"""

from __future__ import annotations

import copy
import hashlib
import json
import time

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import GeneratedAsset, GenerationJob, GenerationSession, Job, ProviderProfile
from tests.fake_comfyui import comfyui_grants, PNG, FakeComfyUI
from tests.util import fresh_client, wait_settled, wait_status

PACKAGE = "dev.mosael.comfyui"
VENDOR = f"plugin:{PACKAGE}"


@pytest.fixture
def connected():
    with FakeComfyUI() as comfy:
        client = fresh_client()
        created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": comfy.url}})
        assert created.status_code == 200, created.text
        instance_id = created.json()["id"]
        client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
        enabled = client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True})
        assert enabled.status_code == 200, enabled.text
        yield client, comfy, instance_id


def _options(client, kind: str) -> dict[str, dict]:
    return {one["model"]: one for one in client.get(f"/api/generation/options?kind={kind}").json() if one["provider"] == VENDOR}


def test_随应用装好_卸不掉() -> None:
    client = fresh_client()
    package = next(one for one in client.get("/api/plugins").json() if one["id"] == PACKAGE)
    assert package["bundled"] is True and package["provides"] == ["generation", "tools", "model_library", "workflow_library"]
    # 如实申报(ADR 0034):解析和下载模型会连 HuggingFace / Civitai / ModelScope,ComfyUI 在同一台电脑上时会写它的 models 目录;
    # 让 Mosael 装本机 ComfyUI(ADR 0041 §4)要连 GitHub(源码、pysssss)、PyPI(依赖)、PyTorch 源(CUDA 版 torch)
    assert package["permissions"] == ["network:comfyui", "network:huggingface", "network:civitai", "network:modelscope",
                                      "network:github", "network:pypi", "network:pytorch", "network:comfy-registry",
                                      "filesystem:write"]
    assert package["summary_field"] == "server_url", "收起的连接那一行摆服务器地址"
    assert package["config_fields"][0]["default"] == "http://127.0.0.1:8188"
    assert [one["key"] for one in package["config_fields"]] == ["server_url"], (
        "「API 模板」撤掉了(插件 1.17.0):导出的 API 格式 JSON 直接导进工作流库就转成界面格式")
    assert client.delete(f"/api/plugins/{PACKAGE}").status_code == 404


def test_每张保存的工作流都是选择器里的一个模型(connected) -> None:
    client, _, instance_id = connected
    images = _options(client, "image")
    assert set(images) == {"builtin:txt2img", "portrait.json"}
    portrait = images["portrait.json"]
    assert (portrait["model_label"], portrait["group"]) == ("portrait", {"id": "portrait.json", "label": "portrait", "entry": "full", "order": 0})
    assert "label" not in portrait, "没有拼好的「连接名 · 模型名」(ADR 0045):两层名字由界面拿结构化的几格摆"
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


def test_停下一次生成_ComfyUI上只停这一次的任务_记录说已停止(connected) -> None:
    """AI 工作台的「停止」走任务总线的取消(jobs.cancel_job)。维护者:「发起了怎么就没办法取消/停止了」。

    插件那一侧收到取消文件,把**这一次的** `prompt_id` 从那台 ComfyUI 上停掉:在跑的 `/interrupt` 带着它的任务号,
    排在后面的别人的任务不碰(同一台 ComfyUI 可能好几个人在用)。生成记录说「已停止」(`stopped`),不是一张失败卡。
    """
    client, comfy, instance_id = connected
    comfy.state.outcome = "never"
    comfy.state.pending = ["someone-else"]
    workspace = client.post("/api/workspaces", json={"name": "ComfyUI"}).json()["id"]
    with SessionLocal() as db:
        profile_id = db.scalar(select(ProviderProfile.id).where(ProviderProfile.plugin_instance_id == instance_id))
    submitted = client.post("/api/generation/jobs", json={
        "workspace_id": workspace, "session_id": None, "project_id": None, "provider_profile_id": profile_id,
        "provider": VENDOR, "model": "portrait.json", "kind": "image", "prompt": "海边的柴犬", "parameters": {},
    })
    assert submitted.status_code == 200, submitted.text
    job_id = submitted.json()["job"]["id"]
    session_id = submitted.json()["generation"]["session_id"]
    assert comfy.state.submitted.wait(30), "插件没把图提交上去"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        with SessionLocal() as db:
            if (db.get(Job, job_id).payload or {}).get("remote_task"):
                break
        time.sleep(0.05)

    stopped = client.post(f"/api/jobs/{job_id}/cancel")
    assert stopped.status_code == 200, stopped.text
    from app.domain.jobs import wait_for_idle_jobs

    assert wait_for_idle_jobs(timeout=60)
    assert comfy.posted("/interrupt") == [{"prompt_id": "p1"}], "在跑的是这一次的:按它的任务号中断"
    assert comfy.posted("/queue") == [] and comfy.state.pending == ["someone-else"], "排着的是别人的任务,不碰"
    [record] = client.get(f"/api/generation/jobs?workspace_id={workspace}&session_id={session_id}").json()
    assert record["stopped"] is True and not record["result_asset_ids"]
    assert record["cost_confidence"] in ("not_billed", "free"), record
    with SessionLocal() as db:
        assert not db.scalars(select(GeneratedAsset).where(GeneratedAsset.job_id == job_id)).all()


def test_跑挂了的不是停下的(connected) -> None:
    client, comfy, instance_id = connected
    comfy.state.outcome = "error"
    workspace = client.post("/api/workspaces", json={"name": "ComfyUI"}).json()["id"]
    with SessionLocal() as db:
        profile_id = db.scalar(select(ProviderProfile.id).where(ProviderProfile.plugin_instance_id == instance_id))
    submitted = client.post("/api/generation/jobs", json={
        "workspace_id": workspace, "session_id": None, "project_id": None, "provider_profile_id": profile_id,
        "provider": VENDOR, "model": "portrait.json", "kind": "image", "prompt": "海边的柴犬", "parameters": {},
    }).json()
    #: 失败原因是任务落终态**之后**才抄到生成记录上的(generation.runner.record_failure):等收拾做完再读。
    assert wait_settled(client, submitted["job"]["id"], timeout=60) == "failed"
    [record] = client.get(
        f"/api/generation/jobs?workspace_id={workspace}&session_id={submitted['generation']['session_id']}").json()
    assert record["stopped"] is False and "CUDA out of memory" in record["error"]


def test_精简表单到了选择器_标题说明和表上的每一项_按看的人的语言(connected) -> None:
    """AI 工作台的「引擎参数」照作者那张表摆(维护者:「右侧引擎参数配置明显和实际的精简表单不符」):描述符里带着表的
    标题、说明、按表上顺序的每一项(主提示词是 `prompt`),名字按看的人的语言挑好;提示词可以不写时带着不写用的那一句。"""
    client, comfy, instance_id = connected
    ui = copy.deepcopy(comfy.state.workflows["portrait.json"])
    ui["extra"] = {"mosael": {"version": 2, "forms": [{"id": "app", "title": "快速出图", "description": "只填一句话",
                                                       "graph_items": {}}]}}
    for node in ui["nodes"]:
        if node["id"] == 6:
            node["properties"] = {"mosael": {"forms": {"app": {"text": {"order": 0, "main": True}}}}}
        if node["id"] == 3:
            node["properties"] = {"mosael": {"forms": {"app": {"steps": {"order": 1, "label": "快慢"}}}}}
    comfy.state.workflows["portrait.json"] = ui
    assert client.post(f"/api/plugins/instances/{instance_id}/refresh").status_code == 200
    options = _options(client, "image")
    assert "form" not in options["portrait.json"]["capabilities"], "完整工作流入口没有表(ADR 0045):参数照旧全列"
    caps = options["portrait.json#app"]["capabilities"]
    assert caps["form"] == {"title": "快速出图", "description": "只填一句话",
                            "items": [{"key": "prompt", "label": "提示词"}, {"key": "3.steps", "label": "快慢"}]}
    assert caps["prompt"] == "optional" and caps["prompt_default"] == "a cat"
    english = client.get("/api/generation/options?kind=image", headers={"Accept-Language": "en-US"}).json()
    portrait = next(one for one in english if one["provider"] == VENDOR and one["model"] == "portrait.json#app")
    assert portrait["capabilities"]["form"]["items"][0] == {"key": "prompt", "label": "Prompt"}
    assert "form" not in _options(client, "image")["builtin:txt2img"]["capabilities"], "没有表的照旧按参数分栏"


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
    assert models["video/wan.json"]["inputs"] == [{"role": "first_frame", "max": 1, "required": True}]


def test_工具出现在插件页_智能体和工作流里(connected) -> None:
    """这个插件此前只替宿主做生成,插件页上一个工具都没有。现在工具在勾选表里,按 recommended 预勾。"""
    client, _, instance_id = connected
    package = next(one for one in client.get("/api/plugins").json() if one["id"] == PACKAGE)
    tools = {one["name"]: one for one in package["instances"][0]["tools"]}
    assert "comfyui_generation" not in tools, "认领生成的那个工具只给宿主调"
    fixed = {name for name in tools if not name.startswith("wf_")}
    assert fixed == {"list_workflows", "import_outputs", "server_status", "list_models",
                     "interrupt", "clear_queue", "free_memory"}, (
        "没有通用的 run_workflow:它不知道要跑哪张图,表单却要人填参数 —— 每张图有自己的工具")
    assert {name for name in fixed if tools[name]["exposed"]} == {
        "list_workflows", "import_outputs", "server_status", "list_models", "interrupt"}, (
        "清队列、释放显存会动到同一台机器上别人的活:默认不开"
    )
    assert all(tool["exposed"] for name, tool in tools.items() if name.startswith("wf_"))
    assert tools["list_workflows"]["read_only"] is True and tools["import_outputs"]["read_only"] is False
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
    client.post(f"/api/plugins/instances/{instance_id}/refresh")
    upscale = "wf_" + hashlib.sha1(b"upscale.json").hexdigest()[:12]
    invoked = client.post(f"/api/plugins/instances/{instance_id}/tools/{upscale}/invoke", json={
        "workspace_id": workspace, "input": {"image_1": source},
    })
    assert invoked.status_code == 200, invoked.text
    body = invoked.json()
    assert body["status"] == "succeeded", body
    output = body["output"]
    assert "artifacts" not in output, "交出去的是素材 id,不是一次性的暂存路径"
    assert len(output["asset_ids"]) == 2 and output["asset_id"] == output["asset_ids"][0]
    assert [one["filename"] if "filename" in one else one["asset_name"] for one in output["assets"]] == ["u1.png", "u2.png"]
    assert output["assets"][0]["node"] == "4" and output["assets"][0]["media"] == "image"
    names = {one["id"]: one["name"] for one in client.get(f"/api/assets?workspace_id={workspace}").json()["items"]}
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


def test_工作台跑画布上的图_从头到尾_普通的生成任务_产出标来源节点(connected) -> None:
    """ADR 0038 §6:工作台的「运行」跑画布上现在这张(含没存的改动)。真插件、假 ComfyUI、普通的生成执行器:图在任务载荷里交给
    插件,原样提交(前端的 clientId、界面格式进 extra_pnginfo),不读文件、不填参数,产出进素材库、各带来自哪个节点。"""
    from tests.fake_comfyui import PORTRAIT_UI

    client, comfy, instance_id = connected
    workspace = client.post("/api/workspaces", json={"name": "工作台"}).json()["id"]
    comfy.state.outputs = {"9": {"images": [{"filename": "a.png", "subfolder": "", "type": "output"}]},
                           "12": {"images": [{"filename": "b.png", "subfolder": "", "type": "temp"}]}}
    canvas = json.loads(json.dumps(PORTRAIT_UI))
    prompt = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base.safetensors"}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "canvas", "images": ["4", 0]}},
    }
    response = client.post(f"/api/plugins/instances/{instance_id}/workflow-library/run", json={
        "workspace_id": workspace, "path": "portrait.json", "prompt": prompt, "workflow": canvas,
        "client_id": "4f1c0e2a9b7d4c51a3e8",
    })
    assert response.status_code == 200, response.text
    job_id = response.json()["job"]["id"]
    assert wait_status(client, job_id, timeout=60) == "succeeded"
    body = comfy.posted("/prompt")[0]
    assert body["prompt"] == prompt, "画布上的图原样提交"
    assert body["client_id"] == "4f1c0e2a9b7d4c51a3e8"
    assert body["extra_data"]["extra_pnginfo"]["workflow"] == canvas
    job = client.get(f"/api/jobs/{job_id}").json()
    assert "workbench_graph" not in job["payload"], "任务出口不带那张图"
    [asset_id] = job["result"]["asset_ids"]
    assert job["result"]["output_parameters"] == [{"asset_id": asset_id, "parameters": {"source_node": "9"}}]
    with SessionLocal() as db:
        generated = db.get(GeneratedAsset, asset_id)
        assert generated.parameters == {"source_node": "9"}, "图不进生成参数"
        generation = db.scalar(select(GenerationJob).where(GenerationJob.job_id == job_id))
        assert generation.request["workbench"] is True and "workbench_graph" not in generation.request
        assert db.get(GenerationSession, generation.session_id).title == "portrait", "会话按那张工作流的名字叫"
