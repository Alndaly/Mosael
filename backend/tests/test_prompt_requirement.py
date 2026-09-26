"""提示词要不要写,由模型的描述符说(`prompt`: required / optional / none),一套规矩判到底。

此前图像 / 视频「必须有提示词」写死在契约层,音频另有两个布尔 —— 于是 ComfyUI 里一张放大工作流当成
生成模型用时,也逼着人先敲一句没用的话。钉住的是:

- 描述符:取值只有那三个、没写就是 required;内置目录里没有老的两个布尔;
- 漏斗(validate_text_inputs):none 不收提示词、带着就拒;optional 空着放行;required 空着拒,
  会唱歌词的模型只给歌词也行;描述符查不到的模型照旧放行歌词;
- 用户写的参数组:`prompt` 是一格三选一,老的两个布尔不再认;表单结构里带着可选值;
- 插件:模型可以声明 `prompt`,宿主只收认得的值;一次生成从接口走到插件,none 的模型空着提示词跑得通;
- 智能体开卡:按选中模型的描述符判,不再写死「必须有提示词」。
"""

from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.core.db import SessionLocal
from app.db.models import PluginPackage
from app.domain.generation import catalog as C
from app.domain.generation.custom_profiles import CapabilityProfileError, profile_form_schema, validate_capabilities
from app.domain.generation.operations import GenerationDomainError, check_text_inputs, validate_text_inputs
from app.domain.generation.plugin_connections import descriptor
from app.domain.plugins import generation as plugin_generation
from app.domain.plugins import runtime
from tests.test_plugin_generation_providers import PACKAGE_ID, PLUGIN, PNG, VENDOR, _connect, _manifest, _profile_id
from tests.util import fresh_client, user_id, wait_status


def _text(prompt: str, parameters: dict[str, Any], capabilities: dict[str, Any] | None, kind: str = "image") -> None:
    validate_text_inputs("p", "m", kind, prompt, parameters, capabilities=capabilities)


# --- 描述符 -----------------------------------------------------------------------


def test_没写就是必须写_认不出的值也按必须写() -> None:
    assert C.PROMPT_MODES == ("required", "optional", "none")
    assert C.prompt_mode(None) == "required"
    assert C.prompt_mode({}) == "required"
    assert C.prompt_mode({"prompt": "maybe"}) == "required", "认不出的值走保守的那一边"
    assert C.prompt_mode({"prompt": "none"}) == "none"


def test_内置目录只用这一格_老的两个布尔不再出现() -> None:
    for item in C.BUILTIN_MODELS:
        caps = item["capabilities"]
        assert not {"requires_prompt", "prompt_optional"} & set(caps), item["id"]
        assert caps.get("prompt", "required") in C.PROMPT_MODES, item["id"]


# --- 漏斗 -------------------------------------------------------------------------


def test_不收提示词的模型_空着放行_带着当场拒() -> None:
    caps = {"parameter_keys": ["reference_image"], "prompt": "none"}
    _text("", {}, caps)
    with pytest.raises(GenerationDomainError, match="不收提示词"):
        _text("放大一点", {}, caps)


def test_可以不写的模型_空着和写了都行() -> None:
    caps = {"parameter_keys": ["reference_image"], "prompt": "optional"}
    _text("", {}, caps)
    _text("更清楚一点", {}, caps)


def test_要写的模型_空着拒_不按种类分() -> None:
    for kind in ("image", "video", "audio"):
        with pytest.raises(GenerationDomainError, match="要写一段描述"):
            _text("  ", {}, {"parameter_keys": ["seed"]}, kind)
        _text("一只猫", {}, {"parameter_keys": ["seed"]}, kind)


def test_会唱歌词的模型只给歌词也算写了() -> None:
    caps = {"parameter_keys": ["lyrics"]}
    _text("", {"lyrics": "[Verse] 啦"}, caps, "audio")
    with pytest.raises(GenerationDomainError, match="至少要给一段"):
        _text("", {}, caps, "audio")


def test_描述符查不到的模型_照旧要描述_给了歌词放行() -> None:
    with pytest.raises(GenerationDomainError, match="要写一段描述"):
        _text("", {}, None)
    _text("", {"lyrics": "啦啦"}, None, "audio")


def test_纯音乐要描述只对要写的模型成立() -> None:
    with pytest.raises(GenerationDomainError, match="纯音乐要写一段描述"):
        _text("", {"instrumental": True}, {"parameter_keys": ["instrumental"]}, "audio")
    _text("", {"instrumental": True}, {"parameter_keys": ["instrumental"], "prompt": "optional"}, "audio")


# --- 用户写的参数组 ---------------------------------------------------------------


def test_参数组里提示词是一格三选一() -> None:
    clean = validate_capabilities({"parameter_keys": ["seed"], "prompt": "none"}, "image")
    assert clean["prompt"] == "none"
    with pytest.raises(CapabilityProfileError) as err:
        validate_capabilities({"parameter_keys": ["seed"], "prompt": "sometimes"}, "image")
    assert err.value.key == "genErr_profileChoice"
    for old in ("requires_prompt", "prompt_optional"):
        with pytest.raises(CapabilityProfileError) as err:
            validate_capabilities({"parameter_keys": ["seed"], old: True}, "image")
        assert err.value.key == "genErr_profileUnknownFields"


def test_表单结构里带着可选值_前端不再抄一份() -> None:
    fields = {field["key"]: field for field in profile_form_schema("image")["fields"]}
    assert fields["prompt"]["shape"] == "choice"
    assert fields["prompt"]["choices"] == ["required", "optional", "none"]
    assert "choices" not in fields["parameter_keys"]


# --- 插件 -------------------------------------------------------------------------


def _plugin_model(**entry: Any) -> plugin_generation.PluginModel:
    model = plugin_generation._model({"id": "m", "kind": "image", **entry}, lambda value: str(value or ""))
    assert model is not None
    return model


def test_插件说的提示词要求进描述符_认不出的值不写() -> None:
    assert descriptor(_plugin_model(prompt="none"))["prompt"] == "none"
    assert descriptor(_plugin_model(prompt="Optional"))["prompt"] == "optional"
    assert "prompt" not in descriptor(_plugin_model(prompt="whatever"))
    assert "prompt" not in descriptor(_plugin_model()), "插件没说就不伪造一格(= required)"
    assert "prompt" not in descriptor(_plugin_model(prompt=["none"]))


MODELS: list[dict[str, Any]] = [
    {"id": "upscale.json", "label": "放大", "kind": "image", "modes": ["image-to-image"],
     "inputs": [{"role": "reference_image", "max": 1, "required": True}], "prompt": "none"},
    {"id": "refine.json", "label": "精修", "kind": "image", "prompt": "optional"},
    {"id": "portrait.json", "label": "人像", "kind": "image"},
]


@pytest.fixture
def plugged(tmp_path: Path):
    shutil.rmtree(runtime.data_dir_for(PACKAGE_ID), ignore_errors=True)
    client = fresh_client()
    path = tmp_path / "plugin"
    path.mkdir(parents=True)
    source = PLUGIN.replace("__PNG__", base64.b64encode(PNG).decode()).replace("__MODELS__", repr(json.dumps(MODELS)))
    (path / "main.py").write_text(source, encoding="utf-8")
    with SessionLocal() as db:
        db.add(PluginPackage(id=PACKAGE_ID, name="测试生成", version="1.0.0", manifest=_manifest(path)))
        db.commit()
    yield client, _connect(client)
    shutil.rmtree(runtime.data_dir_for(PACKAGE_ID), ignore_errors=True)


def _submit(client, workspace: str, instance_id: str, model: str, prompt: str, **extra: Any):
    return client.post("/api/generation/jobs", json={
        "workspace_id": workspace, "provider_profile_id": _profile_id(instance_id), "provider": VENDOR,
        "model": model, "kind": "image", "prompt": prompt, **extra,
    })


def test_插件的放大工作流_不写提示词就能跑_写了当场说(plugged) -> None:
    client, instance_id = plugged
    options = {one["model"]: one for one in client.get("/api/generation/options?kind=image").json()
               if one["provider"] == VENDOR}
    assert options["upscale.json"]["capabilities"]["prompt"] == "none"
    assert options["refine.json"]["capabilities"]["prompt"] == "optional"
    assert "prompt" not in options["portrait.json"]["capabilities"]

    workspace = client.post("/api/workspaces", json={"name": "放大"}).json()["id"]
    asset = client.post("/api/assets/import", data={"workspace_id": workspace},
                        files={"file": ("原图.png", PNG, "image/png")}).json()["id"]
    source = [{"asset_id": asset, "role": "reference_image"}]

    rejected = _submit(client, workspace, instance_id, "upscale.json", "放大两倍", source_assets=source)
    assert rejected.status_code == 422 and "不收提示词" in rejected.json()["detail"]
    accepted = _submit(client, workspace, instance_id, "upscale.json", "", source_assets=source)
    assert accepted.status_code == 200, accepted.text
    assert wait_status(client, accepted.json()["job"]["id"], timeout=30) == "succeeded"

    optional = _submit(client, workspace, instance_id, "refine.json", "")
    assert optional.status_code == 200, optional.text
    assert wait_status(client, optional.json()["job"]["id"], timeout=30) == "succeeded"

    required = _submit(client, workspace, instance_id, "portrait.json", "")
    assert required.status_code == 422 and "要写一段描述" in required.json()["detail"]


def test_智能体开卡按选中模型判提示词(plugged) -> None:
    client, instance_id = plugged
    with SessionLocal() as db:
        base = {"db": db, "user_id": user_id("tester"), "kind": "image", "provider": VENDOR,
                "provider_profile_id": _profile_id(instance_id), "parameters": {}}
        check_text_inputs(model="upscale.json", prompt="", **base)
        with pytest.raises(GenerationDomainError, match="不收提示词"):
            check_text_inputs(model="upscale.json", prompt="放大", **base)
        with pytest.raises(GenerationDomainError, match="要写一段描述"):
            check_text_inputs(model="portrait.json", prompt="", **base)

    workspace = client.post("/api/workspaces", json={"name": "卡"}).json()["id"]
    card = {"workspace_id": workspace, "tool": "generate_image", "requested_by": "agent",
            "payload": {"provider": VENDOR, "provider_profile_id": _profile_id(instance_id), "model": "upscale.json",
                        "prompt": "", "parameters": {}, "source_assets": []}}
    opened = client.post("/api/confirmations", json=card)
    assert opened.status_code == 200, opened.text
    card["payload"] = {**card["payload"], "model": "portrait.json"}
    refused = client.post("/api/confirmations", json=card)
    assert refused.status_code in (400, 422) and "要写一段描述" in refused.text


# --- 工作流:运行前就按模型判,不等前面的付费节点跑完 ------------------------------


def _generate_node(node_id: str, instance_id: str, model: str, prompt: str, **extra: Any) -> dict[str, Any]:
    return {"id": node_id, "type": "ai_generate", "name": f"生成 {node_id}", "config": {
        "provider": VENDOR, "provider_profile_id": _profile_id(instance_id), "model": model, "kind": "image",
        "prompt": prompt, **extra,
    }}


def _workflow(client, workspace: str, nodes: list[dict[str, Any]]) -> str:
    edges = [{"id": f"e{index}", "source": source["id"], "target": target["id"]}
             for index, (source, target) in enumerate(zip(nodes, nodes[1:]))]
    created = client.post("/api/workflows", json={"workspace_id": workspace, "name": "流", "graph": {
        "nodes": nodes, "edges": edges}})
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _job_count() -> int:
    from app.db.models import Job

    with SessionLocal() as db:
        return db.query(Job).count()


def test_要提示词却空着的生成节点_运行前就拒_一个任务都不建(plugged) -> None:
    """前面是一个花钱的生成节点,后面那个的模型要提示词却空着:点运行当场拒,点名是哪个节点 ——
    而不是等前面那次付费生成跑完、轮到它时才说。循环体里的一样。"""
    client, instance_id = plugged
    workspace = client.post("/api/workspaces", json={"name": "流"}).json()["id"]
    start = {"id": "start", "type": "start", "config": {"params": {}}}
    paid = _generate_node("paid", instance_id, "refine.json", "先出一张")
    missing = _generate_node("later", instance_id, "portrait.json", "")
    top = _workflow(client, workspace, [start, paid, missing])
    loop = {"id": "loop", "type": "loop_foreach", "config": {
        "items": "[1, 2]", "body": {"nodes": [_generate_node("inner", instance_id, "portrait.json", "  ")], "edges": []}}}
    nested = _workflow(client, workspace, [start, paid, loop])

    before = _job_count()
    for workflow_id, node in ((top, "生成 later"), (nested, "生成 inner")):
        refused = client.post(f"/api/workflows/{workflow_id}/run", json={"params": {}})
        assert refused.status_code == 422, refused.text
        assert node in refused.text and "要写一段描述" in refused.text
    assert _job_count() == before, "拒在建任务之前:前面那个付费节点一次都没跑"
    assert not (runtime.data_dir_for(PACKAGE_ID) / "requests.jsonl").exists()

    # 英文界面说英文(原因跟着读的人的语言翻)
    english = client.post(f"/api/workflows/{top}/run", json={"params": {}}, headers={"Accept-Language": "en"})
    assert english.status_code == 422 and "can't run yet" in english.text and "needs a description" in english.text


def test_不收或可以不写提示词的模型_空着照常跑_引用算给了(plugged) -> None:
    client, instance_id = plugged
    workspace = client.post("/api/workspaces", json={"name": "流"}).json()["id"]
    asset = client.post("/api/assets/import", data={"workspace_id": workspace},
                        files={"file": ("原图.png", PNG, "image/png")}).json()["id"]
    start = {"id": "start", "type": "start", "config": {"params": {"topic": "一只猫"}}}
    nodes = [
        start,
        _generate_node("up", instance_id, "upscale.json", "", source_assets=f"{asset}:reference_image"),
        _generate_node("refine", instance_id, "refine.json", ""),
        # 要提示词的模型,提示词是引用:值要到运行时才知道,运行前不拦
        _generate_node("portrait", instance_id, "portrait.json", "{{start.topic}}"),
    ]
    workflow_id = _workflow(client, workspace, nodes)
    started = client.post(f"/api/workflows/{workflow_id}/run", json={"params": {}})
    assert started.status_code == 200, started.text
    assert wait_status(client, started.json()["id"], timeout=60) == "succeeded"
