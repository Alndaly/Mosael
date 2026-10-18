"""工作流库(ADR 0035):认领 `workflow_library` 的连接,宿主替它列工作流、取原文、改那台服务器上的工作流文件。

钉住的是**框架**,不是 ComfyUI(那个在 test_comfyui_plugin_workflow_library.py):

- 目录类能力:认领它的工具不进工具表,能力词表里叫得出名字;
- 列出来的是插件报的那一份,宿主规整字段(路径不对的、坏条目丢掉,图摘要的连线只留指着节点的);
- 宿主补上它在 Mosael 里的样子:是不是这个连接下的生成模型(用它生成要它)、这个工作区里它最近的产出(生成的、当工具
  跑的,一批的每一张,带 NSFW 的判断,能手动标)、这个工作区里哪些工作流节点 / 画板格子选的是它;
- 写操作(复制、改名、挪进 / 挪出回收目录):路径先在宿主这里过一遍(不合格的不交给插件);撞名回 409 带建议名、
  不覆盖;改成了让这个连接的目录马上重拉一遍;
- 导入:要导入的东西(一段文字 / 一个文件 / 一个链接,只给一样,太大的不交)先让插件认一遍,宿主规整预览;存进去和别的
  写操作同一套(不覆盖、撞名 409、改完重拉),原文以 JSON 字符串交给插件(调用记录里只留截断的一段);
- 装缺的节点包:一个后台任务(`node_install`),进度照插件说的,装完说要重启;包名先在宿主这里过一遍;工作流库列着这个
  连接最近的几次;重启经插件,回来以后让这个连接的目录重拉一遍;
- 应用表单(ADR 0038):列出来的每一张带着它的应用表单(规整过);编辑器读一张全部能填的项(名字按语言挑好、JSON Schema
  片段和生成目录同一套规整、子图里的节点标着不能放);写之前宿主先查形状(根图上的节点、几项、可选值几个),插件说那张在
  这之间被改过就回 409 `stale`,写成了让这个连接的目录马上重拉;
- 工作台(ADR 0038 §3、§6):画布上现在这张的应用表单(没有路径和改动时间)、写进画布的标记(宿主规整插件交回的)、选中节点
  那一格是哪个模型目录(见 test_plugin_model_library.py)、跑画布上的图(普通的生成任务,图在任务载荷里、不进生成参数、任务出口不带它;还不是生成模型的不跑)。
  这几样都不写那台机器上的文件。
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import PluginPackage, ProviderModel, ProviderProfile
from app.domain.plugins import runtime
from tests.util import fresh_client, wait_status

PACKAGE_ID = "test.workflows"

PLUGIN = r'''
import json, os, sys
from pathlib import Path

request = json.loads(sys.stdin.read())
payload = request["input"]
data = Path(os.environ["MOSAEL_PLUGIN_DATA_DIR"])
data.mkdir(parents=True, exist_ok=True)


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


op = payload.get("op")
with (data / "ops.jsonl").open("a", encoding="utf-8") as log:
    log.write(json.dumps(payload, ensure_ascii=False) + "\n")
if op == "models":
    emit({"ok": True, "output": {"models": [{"id": "portrait.json", "label": "portrait", "kind": "image"}]}})
elif op == "workflows":
    emit({"ok": True, "output": {
        "workflows": [
            {"path": "portrait.json", "size": 19334, "modified": 1776098682.9, "kind": "image", "node_count": 3,
             "graph": {"nodes": [{"x": 0, "y": 0, "w": 300, "h": 120, "role": "model", "title": "Load Checkpoint"},
                                 {"x": 400, "y": 0, "w": 200, "h": 80, "role": "sampler", "muted": True},
                                 {"x": "bad"},
                                 {"x": 700, "y": 40, "w": 0, "h": 0, "role": "weird"}],
                       "links": [[0, 1], [1, 2], [0, 9], ["a", 1]],
                       "groups": [{"x": -20, "y": -40, "w": 680, "h": 200, "title": "生成", "color": "#3f789e"},
                                  {"x": 1, "y": 1, "w": 1, "h": 1, "color": "red;background:url(x)"}]},
             "inputs": [{"node": "10", "title": "参考图", "media": "image", "role": "reference_image"}],
             "parameters": [{"key": "3.steps", "title": "步数", "type": "integer"}],
             "outputs": [{"node": "9", "title": "SaveImage", "label": {"zh": "保存图像", "en": "Save Image"}, "media": "image"},
                         {"node": "12", "title": "高清", "media": "image"}],
             "models": [{"folder": "checkpoints", "name": "sdxl.safetensors", "present": True},
                        {"folder": "vae", "name": "ae.safetensors", "present": False}, {"folder": ""}],
             "missing_nodes": [{"type": "CR Prompt Text", "count": 2, "core": False,
                                "packs": [{"id": "ComfyUI_Comfyroll_CustomNodes", "title": "Comfyroll", "installed": True,
                                           "enabled": False, "installed_version": "1.2.0", "wanted_version": "1.3.0",
                                           "wanted_is_commit": False, "source": "registry",
                                           "page": "https://registry.comfy.org/nodes/ComfyUI_Comfyroll_CustomNodes",
                                           "repository": "", "state": "installed"}]},
                               {"type": "LoadAudioMP3", "count": 1, "core": True, "packs": []}],
             "missing_models": [{"folder": "vae", "name": "ae.safetensors",
                                 "url": "https://huggingface.co/x/y/resolve/main/ae.safetensors"},
                                {"folder": "", "name": "mystery.safetensors",
                                 "url": "https://huggingface.co/a/b/resolve/main/mystery.safetensors"}],
             "app": {"status": "ok", "upgradable": False, "invalid": 1, "stray": 2, "forms": [
                         {"id": "app", "title": " 人像应用 ", "description": "", "fields": 1, "invalid": 1,
                          "model": "portrait.json#app", "tool": "wf_0123456789ab_app",
                          "items": [{"key": "10.image", "node": "10", "input": "image", "label": "人物", "main": False},
                                    {"key": "3.cfg", "node": "3", "input": "cfg", "label": "",
                                     "problem": "节点 #3 上没有「cfg」"},
                                    {"key": "12:5.text", "node": "12:5", "input": "text"},
                                    {"node": "4", "input": ""}]},
                         {"id": "Bad-Id", "title": "不合规的 id"},
                         {"id": "app", "title": "重复的"},
                         {"id": "k3x9a2", "title": "精调", "items": []}],
                     "results": ["9", "12:5", 7]}},
            {"path": "sub/sketch.json", "problem": "缺节点:CR Prompt Text"},
            {"path": "../outside.json"},
            {"path": "sub/.hidden.json"},
            "not a dict",
        ],
        "folders": ["空的/更深", "../evil", ".hidden", "x.json", 3, "a\\b"],
        "others": [{"path": "pack.zip", "reason": "这是一个压缩包"}],
        "trash": [{"path": ".mosael-trash/workflows/20261005-101500/old/one.json", "deleted_at": 1791000000.0},
                  {"path": ".mosael-trash/elsewhere/x.json"}],
        "manager": {"version": "V4.2.1"},
        "editor": json.loads((data / "editor.json").read_text()) if (data / "editor.json").exists()
        else {"kind": "comfyui", "url": "http://127.0.0.1:8188"},
    }})
elif op == "workflow":
    emit({"ok": True, "output": {"content": {"nodes": [], "links": [], "path_seen": payload["path"]}}})
elif op in ("copy_workflow", "rename_workflow", "restore_workflow"):
    if payload["new_path"] == "taken.json":
        emit({"ok": True, "output": {"conflict": True, "suggestion": "taken (1).json"}})
    else:
        emit({"ok": True, "output": {"path": payload["new_path"]}})
elif op == "inspect_import":
    if payload.get("url") == "https://example.com/flow.json":
        emit({"ok": False, "error": "example.com 上的东西 Mosael 不替你去取"})
    else:
        emit({"ok": True, "output": {
            "format": "api", "source": "png" if payload.get("data") else "json",
            "workflow": {"id": "new-id", "nodes": [{"id": 3, "type": "KSampler"}], "links": []},
            "suggested_path": "../出去.json" if payload.get("filename") == "evil.png" else "人像.json",
            "notes": ["这份是 API 格式,没有布局", "", 3],
            "graph": {"nodes": [{"x": 0, "y": 0, "w": 320, "h": 200, "role": "sampler", "title": "KSampler"}],
                      "links": [], "groups": [], "auto_layout": True},
            "node_count": 1, "kind": "image", "parameters": [{"key": "3.steps", "title": "步数", "type": "integer"}],
            "missing_nodes": [{"type": "CR Prompt Text", "count": 1,
                               "packs": [{"id": "ComfyUI_Comfyroll_CustomNodes", "title": "Comfyroll", "installed": False}]}],
            "missing_models": [{"folder": "loras", "name": "x.safetensors", "url": "https://huggingface.co/a/b/resolve/main/x.safetensors"}],
        }})
elif op == "save_workflow":
    if payload["path"] == "taken.json":
        emit({"ok": True, "output": {"conflict": True, "suggestion": "taken (1).json"}})
    else:
        emit({"ok": True, "output": {"path": payload["path"]}})
elif op == "install_nodes":
    emit({"event": "progress", "progress": 0.4, "message": "ComfyUI-Manager 正在装 " + payload["packs"][0] + "(1/1)"})
    if "refused" in payload["packs"]:
        emit({"ok": False, "error": "这台 ComfyUI 的 ComfyUI-Manager 不让经网络装节点包:把 network_mode 改成 personal_cloud"})
    else:
        emit({"ok": True, "output": {"installed": payload["packs"], "restart": True}})
elif op == "reboot":
    emit({"ok": True, "output": {"back": True}})
elif op == "app_marks":
    if payload["content"].get("evil"):
        emit({"ok": True, "output": {"nodes": {"../evil": {"result": True}}, "extra": None}})
    elif payload["content"].get("keys"):
        #: 交回**它拿到的那几个键**:宿主规整插件交回的那一份,节点号的形状只按一套判据查
        emit({"ok": True, "output": {"nodes": {one: {"result": True} for one in payload["content"]["keys"]}, "extra": None}})
    elif payload["content"].get("inside"):
        emit({"ok": True, "output": {"nodes": {"12:5": {"forms": {"app": {"steps": {"order": 0}}}}}, "extra": None}})
    else:
        emit({"ok": True, "output": {"nodes": {"9": {"result": True}, "10": {"forms": {"app": {"image": {"order": 0}}}}},
                                     "extra": {"version": 2, "forms": [{"id": "app", "title": "人像应用"}]}, "ignored": 1}})
elif op == "generate":
    emit({"ok": False, "error": "测试插件不真的跑:收到了" + ("画布上的图" if payload.get("graph") else "存着的那张")})
elif op == "app":
    emit({"ok": True, "output": {
        "path": payload.get("path", ""), "modified": 1776098682.9, "kind": "image", "editable": True,
        "items": [
            {"key": "6.text", "node": "6", "input": "text", "kind": "text", "role": "prompt",
             "title": {"zh": "提示词", "en": "Prompt"}, "common": True,
             "schema": {"type": "string", "x-multiline": True, "default": "a cat", "onclick": "x"}},
            {"key": "10.image", "node": "10", "input": "image", "kind": "media", "role": "reference_image",
             "media": "image", "title": "参考图 · 人物", "node_title": "人物", "class_type": "LoadImage",
             "node_label": {"zh": "加载图像", "en": "LoadImage"}, "common": True,
             "mask_property": 1},
            {"key": "seed", "node": "", "input": "seed", "kind": "seed", "title": {"zh": "种子", "en": "Seed"},
             "schema": {"type": "integer", "minimum": 0},
             "mask_property": True},
            {"key": "4.ckpt_name", "node": "4", "input": "ckpt_name", "kind": "model", "folder": "checkpoints",
             "title": {"zh": "模型", "en": "Checkpoint"}, "class_type": "CheckpointLoaderSimple",
             "node_label": {"zh": "Checkpoint 加载器", "en": "Load Checkpoint"},
             "hint": {"zh": "要加载的模型", "en": "The name of the checkpoint (model) to load."},
             "schema": {"type": "string", "enum": ["a.safetensors", "b.safetensors"], "x-model-folder": "checkpoints"}},
            {"key": "12:5.steps", "node": "12:5", "input": "steps", "kind": "number", "title": "步数",
             "node_label": {"zh": "K 采样器", "en": "KSampler"},
             "schema": {"type": "integer", "title": {"zh": "步数", "en": "Steps"}}},
            {"key": "x", "node": "3", "input": "x", "kind": "weird", "title": "?"},
        ],
        "outputs": [{"node": "9", "title": "SaveImage", "class_type": "SaveImage", "media": "image",
                     "label": {"zh": "保存图像", "en": "Save Image"}},
                    {"node": "12", "title": "高清", "class_type": "SaveImage", "media": "image"}],
        "names": {"9": {"zh": "保存图像", "en": "Save Image"}, "12:5": {"zh": "K采样器", "en": "KSampler"}, "3": "",
                  "": {"zh": "无名", "en": "Nameless"}},
        "app": {"status": "unsupported", "version": 1, "upgradable": True, "forms": [], "results": []},
    }})
elif op == "upgrade_marks":
    emit({"ok": True, "output": {"upgraded": ["portrait.json", "not-asked.json"], "stale": ["busy.json"], "skipped": [],
                                 "gone": [], "failed": [{"path": "broken.json", "reason": "拉不下来"}, "junk"]}})
elif op == "annotate":
    if payload["modified"] == 1.0:
        emit({"ok": True, "output": {"stale": True, "modified": 2.0}})
    else:
        emit({"ok": True, "output": {"path": payload["path"], "modified": 1776098699.5}})
elif op == "trash_workflow":
    emit({"ok": True, "output": {"path": ".mosael-trash/workflows/20261005-101500/" + payload["path"]}})
elif op == "make_folder":
    if payload["path"] == "taken":
        emit({"ok": True, "output": {"conflict": True, "suggestion": "taken (1)"}})
    elif payload["path"] == "odd":
        emit({"ok": True, "output": {"conflict": True, "suggestion": "../odd"}})
    else:
        emit({"ok": True, "output": {"path": payload["path"]}})
elif op == "rename_folder":
    if payload["new_path"] == "taken":
        emit({"ok": True, "output": {"conflict": True, "suggestion": "taken (1)"}})
    else:
        emit({"ok": True, "output": {"path": payload["new_path"]}})
elif op == "trash_folder":
    if payload["path"] == "full":
        emit({"ok": True, "output": {"not_empty": True, "count": 3}})
    else:
        emit({"ok": True, "output": {"path": ".mosael-trash/workflows/20261005-101500/" + payload["path"]}})
else:
    emit({"ok": False, "error": f"unknown op {op}"})
'''


def _manifest(path: Path) -> dict[str, Any]:
    return {
        "id": PACKAGE_ID,
        "name": "测试工作流库",
        "version": "1.0.0",
        "manifest_version": 1,
        "runtime": {"kind": "process", "entry": "main.py"},
        "provides": ["generation", "workflow_library"],
        "permissions": ["network:test"],
        "instance": {
            "multiple": True,
            "name_template": "测试工作流库 · {SERVER}",
            "config": [{"key": "SERVER", "label": "服务器", "type": "string", "required": True}],
        },
        "tools": {
            "declare": [
                {"name": "host", "provides": ["generation", "workflow_library"], "timeout_seconds": 60,
                 "input_schema": {"type": "object"}},
                {"name": "ping", "description": "普通工具", "input_schema": {"type": "object"}},
            ]
        },
        "_path": str(path),
    }


@pytest.fixture
def library(tmp_path: Path):
    shutil.rmtree(runtime.data_dir_for(PACKAGE_ID), ignore_errors=True)
    client = fresh_client()
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "main.py").write_text(PLUGIN, encoding="utf-8")
    with SessionLocal() as db:
        db.add(PluginPackage(id=PACKAGE_ID, name="测试工作流库", version="1.0.0", manifest=_manifest(plugin)))
        db.commit()
    created = client.post(f"/api/plugins/{PACKAGE_ID}/instances", json={"config": {"SERVER": "s1"}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    assert client.patch(f"/api/plugins/instances/{instance_id}/permissions",
                        json={"grants": {"network:test": True}}).status_code == 200
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    yield client, instance_id
    shutil.rmtree(runtime.data_dir_for(PACKAGE_ID), ignore_errors=True)


def _ops() -> list[dict[str, Any]]:
    log = runtime.data_dir_for(PACKAGE_ID) / "ops.jsonl"
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []


def test_工作流库是目录类能力_认领它的工具不进工具表(library) -> None:
    client, instance_id = library
    from app.db.models import PluginInstance
    from app.domain.plugins import tools

    with SessionLocal() as db:
        by_name = {tool["name"]: tool for tool in tools.all_tools(db, db.get(PluginInstance, instance_id))}
        assert by_name["host"]["internal"] is True
        assert by_name["ping"]["internal"] is False
    terms = {one["name"]: one for one in client.get("/api/plugins/capabilities").json()}
    assert terms["workflow_library"]["label"] and terms["workflow_library"]["label"] != "workflow_library"


def test_列出插件报的工作流_宿主规整字段_补上它在Mosael里是哪个生成模型(library) -> None:
    client, instance_id = library
    response = client.get(f"/api/plugins/instances/{instance_id}/workflow-library")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [one["path"] for one in body["workflows"]] == ["portrait.json", "sub/sketch.json"], \
        "跳出 workflows/ 的、隐藏的、坏的条目丢掉"
    portrait, sketch = body["workflows"]
    assert portrait["label"] == "portrait" and portrait["folder"] == ""
    assert sketch["label"] == "sketch" and sketch["folder"] == "sub" and sketch["problem"] == "缺节点:CR Prompt Text"
    graph = portrait["graph"]
    assert [node["role"] for node in graph["nodes"]] == ["model", "sampler", "other"], "坏节点丢掉,认不出的种类算 other"
    assert graph["nodes"][1]["muted"] is True
    assert graph["nodes"][2]["w"] >= 20 and graph["nodes"][2]["h"] >= 20, "没有大小的节点也画得出来"
    assert graph["links"] == [[0, 1], [1, 2]], "连线只留指着节点的"
    assert [group["color"] for group in graph["groups"]] == ["#3f789e", ""], "颜色只认 #RGB,不让别的东西进样式"
    assert portrait["outputs"] == [{"node": "9", "title": "保存图像", "media": "image"},
                                   {"node": "12", "title": "高清", "media": "image"}], \
        "交出什么:节点给人看的名字按语言挑好,不是类名;插件没给就用标题"
    assert portrait["models"] == [{"folder": "checkpoints", "name": "sdxl.safetensors", "present": True},
                                  {"folder": "vae", "name": "ae.safetensors", "present": False}]
    assert portrait["missing_nodes"] == [
        {"type": "CR Prompt Text", "count": 2, "core": False, "packs": [{
            "id": "ComfyUI_Comfyroll_CustomNodes", "title": "Comfyroll", "installed": True, "enabled": False,
            "installed_version": "1.2.0", "wanted_version": "1.3.0", "wanted_is_commit": False, "source": "registry",
            "page": "https://registry.comfy.org/nodes/ComfyUI_Comfyroll_CustomNodes", "repository": "",
            "state": "installed"}]},
        {"type": "LoadAudioMP3", "count": 1, "core": True, "packs": []}], \
        "图上写的出处 / 版本 / 装没装 / 启没启用 / 核心节点:宿主这一跳一项都不许丢"
    assert [one["url"] for one in portrait["missing_models"]] == [
        "https://huggingface.co/x/y/resolve/main/ae.safetensors",
        "https://huggingface.co/a/b/resolve/main/mystery.safetensors"]
    assert portrait["missing_models"][1]["folder"] == "", \
        "没写目录的声明也留着(folder 空着):界面据此说「不知道放哪个目录」"
    assert portrait["generation"]["model"] == "portrait.json" and portrait["generation"]["kind"] == "image"
    assert sketch["generation"] is None, "不是这个连接下的生成模型(转不过来)就不能「用它生成」"
    assert body["others"] == [{"path": "pack.zip", "reason": "这是一个压缩包"}]
    assert body["trash"] == [{"path": ".mosael-trash/workflows/20261005-101500/old/one.json", "original": "old/one.json",
                              "label": "one", "deleted_at": 1791000000.0}], "不是回收目录形状的不认"
    assert body["manager"] == {"version": "V4.2.1"}
    assert body["editor"] == {"kind": "comfyui", "url": "http://127.0.0.1:8188"}


@pytest.mark.parametrize("editor", [{"kind": "comfyui", "url": "javascript:alert(1)"},
                                    {"kind": "comfyui", "url": "http://user:pw@127.0.0.1:8188"},
                                    {"kind": "Comfy UI!", "url": "http://127.0.0.1:8188"},
                                    "http://127.0.0.1:8188"])
def test_编辑器只认_http地址和简单的种类名_不对就当没有(library, editor) -> None:
    client, instance_id = library
    runtime.data_dir_for(PACKAGE_ID).mkdir(parents=True, exist_ok=True)
    (runtime.data_dir_for(PACKAGE_ID) / "editor.json").write_text(json.dumps(editor), encoding="utf-8")
    body = client.get(f"/api/plugins/instances/{instance_id}/workflow-library").json()
    assert body["editor"] is None


def test_最近一次的产出_只看这个工作区里用它生成的(library) -> None:
    client, instance_id = library
    workspace = client.post("/api/workspaces", json={"name": "工作流"}).json()["id"]
    other = client.post("/api/workspaces", json={"name": "别的"}).json()["id"]
    body = client.get(f"/api/plugins/instances/{instance_id}/workflow-library").json()
    profile_id = body["workflows"][0]["generation"]["provider_profile_id"]
    from app.db.models import Asset, GenerationJob

    with SessionLocal() as db:
        for ws, name in ((workspace, "这里的.png"), (other, "别处的.png")):
            asset = Asset(workspace_id=ws, name=name, original_filename=name, kind="image")
            db.add(asset)
            db.flush()
            db.add(GenerationJob(workspace_id=ws, provider="plugin:test.workflows", provider_profile_id=profile_id,
                                 model="portrait.json", kind="image", request={}, result_asset_id=asset.id,
                                 created_at=datetime(2026, 10, 5, tzinfo=UTC).replace(tzinfo=None)))
        db.commit()
        here = db.query(Asset).filter_by(name="这里的.png").one().id
    scoped = client.get(f"/api/plugins/instances/{instance_id}/workflow-library", params={"workspace_id": workspace}).json()
    assert scoped["workflows"][0]["last_output"]["asset_id"] == here
    assert body["workflows"][0]["last_output"] is None, "没说是哪个工作区就不去翻生成记录"


def test_最近的产出_一批的每一张都在_新的在前_生成的和当工具跑的都算_带NSFW判断_能手动标(library) -> None:
    """维护者:「工作流产出这里应该是个图片集 然后要支持nsfw过滤」。此前详情只摆最近一次生成的封面那一张。现在是这张工作流在
    这个工作区里最近的产出:用它生成的(每一份 GeneratedAsset,一批两张两张都在)、和它是同一件事的工具在工作流 / 智能体里
    跑出来的(调用交出的 asset_ids),新的在前;别的工作区的不算。每份带着 NSFW 的判断,和模型预览图同一套:手动标的压过一切。"""
    client, instance_id = library
    workspace = client.post("/api/workspaces", json={"name": "工作流"}).json()["id"]
    other = client.post("/api/workspaces", json={"name": "别的"}).json()["id"]
    profile_id = client.get(f"/api/plugins/instances/{instance_id}/workflow-library").json()["workflows"][0]["generation"][
        "provider_profile_id"]
    from app.db.models import Asset, GeneratedAsset, GenerationJob, Job, PluginInstance, PluginInvocation

    def at(minute: int) -> datetime:
        return datetime(2026, 10, 5, 10, minute)

    ids: dict[str, str] = {}
    with SessionLocal() as db:
        instance = db.get(PluginInstance, instance_id)
        #: 和生成模型 portrait.json 是同一件事的那个工具(插件报的 mirrors)
        instance.discovered_tools = [{"name": "wf_portrait", "mirrors": {"generation_model": "portrait.json", "kind": "image"}}]

        def asset(name: str, minute: int, ws: str = workspace, kind: str = "image") -> str:
            row = Asset(workspace_id=ws, name=name, original_filename=name, kind=kind, created_at=at(minute))
            db.add(row)
            db.flush()
            ids[name] = row.id
            return row.id

        def generated(minute: int, names: list[str], ws: str = workspace) -> None:
            job = Job(workspace_id=ws, kind="generation", status="succeeded", created_at=at(minute))
            db.add(job)
            db.flush()
            made = [asset(name, minute, ws) for name in names]
            for one in made:
                db.add(GeneratedAsset(asset_id=one, provider="plugin:test.workflows", model="portrait.json", job_id=job.id))
            db.add(GenerationJob(workspace_id=ws, job_id=job.id, provider="plugin:test.workflows", provider_profile_id=profile_id,
                                 model="portrait.json", kind="image", request={}, result_asset_id=made[0], created_at=at(minute)))

        generated(1, ["一批-1.png", "一批-2.png"])
        generated(3, ["别处.png"], other)
        generated(5, ["单张.png"])
        tool_out = [asset("工具-1.png", 7), asset("工具-2.png", 7)]
        db.add(PluginInvocation(instance_id=instance_id, tool_name="wf_portrait", status="succeeded",
                                output={"asset_ids": tool_out}, created_at=at(7)))
        db.add(PluginInvocation(instance_id=instance_id, tool_name="wf_portrait", status="failed",
                                output={"asset_ids": [asset("失败的.png", 9)]}, created_at=at(9)))
        db.commit()

    url = f"/api/plugins/instances/{instance_id}/workflow-library/outputs"
    body = client.get(url, params={"workspace_id": workspace, "path": "portrait.json"}).json()
    names = {value: key for key, value in ids.items()}
    assert [names[one["asset_id"]] for one in body["outputs"]] == ["工具-1.png", "工具-2.png", "单张.png", "一批-1.png", "一批-2.png"], (
        "新的运行在前,一批两张两张都在;别的工作区的、失败的调用不算")
    assert body["more"] is False
    assert all(one["kind"] == "image" and one["nsfw"] == {"flagged": False, "manual": None, "reasons": []} for one in body["outputs"])
    listed = client.get(f"/api/plugins/instances/{instance_id}/workflow-library", params={"workspace_id": workspace}).json()
    assert listed["workflows"][0]["last_output"]["asset_id"] == ids["工具-1.png"], "卡片上那一张是最新的那一份"

    mark = f"{url}/nsfw"
    marked = client.put(mark, json={"workspace_id": workspace, "asset_id": ids["单张.png"], "nsfw": True})
    assert marked.status_code == 200 and marked.json() == {"flagged": True, "manual": True, "reasons": []}
    again = client.get(url, params={"workspace_id": workspace, "path": "portrait.json"}).json()["outputs"]
    assert next(one for one in again if one["asset_id"] == ids["单张.png"])["nsfw"]["flagged"] is True
    cleared = client.put(mark, json={"workspace_id": workspace, "asset_id": ids["单张.png"], "nsfw": None}).json()
    assert cleared == {"flagged": False, "manual": None, "reasons": []}, "去掉标记:回到本机识别(这里没有依据)"
    assert client.put(mark, json={"workspace_id": workspace, "asset_id": ids["别处.png"], "nsfw": True}).status_code == 422, (
        "别的工作区的素材标不了")


def _declare_entries(db, instance_id: str, extra: list[tuple[str, str, str]]) -> str:
    """把这个连接的模型目录写成:完整入口 portrait.json,加 `extra` 里的几个入口(元组是「模型 id, 组号, 入口格子」)。

    目录是插件刷新时写的(见 plugin_connections 的 `DeclaredModel` / `declared_group`,ADR 0045):同一张工作流的完整入口
    和它的表单入口共用一个组号(那张图的路径)。这里照着写一遍,不去跑一次真刷新。
    """
    from app.domain.providers import models as provider_models

    profile = db.scalar(select(ProviderProfile).where(ProviderProfile.plugin_instance_id == instance_id))
    entries = [provider_models.DeclaredModel(
        model_id="portrait.json", display_name="portrait", capability_ids=["image"], capabilities={"image": {}},
        group={"id": "portrait.json", "label": "portrait", "entry": "full", "order": 0})]
    for model_id, group_id, entry in extra:
        entries.append(provider_models.DeclaredModel(
            model_id=model_id, display_name=model_id, capability_ids=["image"], capabilities={"image": {}},
            group={"id": group_id, "label": group_id, "entry": entry, "order": 1}))
    provider_models.replace_declared_catalog(db, profile, entries)
    db.commit()
    return profile.id


def _made(db, workspace: str, names: list[str]) -> dict[str, str]:
    """一次生成交出来的那几张素材(名 → id)。"""
    from app.db.models import Asset

    out: dict[str, str] = {}
    for name in names:
        row = Asset(workspace_id=workspace, name=name, original_filename=name, kind="image")
        db.add(row)
        db.flush()
        out[name] = row.id
    return out


def test_表单入口跑出来的也算这张工作流的产出(library) -> None:
    """维护者:「ComfyUI 工作流的精简表单的输入结果没被同步到最近的产出」。同一张工作流的完整工作流入口和它上面的表单入口
    是**一回事**(ADR 0045 §1):从精简表单跑出来的那些是**这张工作流**的产出,不是别人的。此前生成任务只按
    `GenerationJob.model == <完整工作流路径>` 精确等值收,表单入口(`<路径>#<表单 id>`)跑的全都漏了 —— 而实测里表单入口
    才是主要跑法。"""
    from app.db.models import GenerationJob

    client, instance_id = library
    workspace = client.post("/api/workspaces", json={"name": "工作流"}).json()["id"]
    with SessionLocal() as db:
        profile_id = _declare_entries(db, instance_id, [("portrait.json#app", "portrait.json", "form")])
        ids = _made(db, workspace, ["表单-1.png", "完整-1.png", "别的工作流的.png", "表单-2.png"])
        for minute, name, model in ((1, "表单-1.png", "portrait.json#app"), (2, "完整-1.png", "portrait.json"),
                                    (3, "别的工作流的.png", "sub/sketch.json#app"), (4, "表单-2.png", "portrait.json#app")):
            db.add(GenerationJob(workspace_id=workspace, provider=f"plugin:{PACKAGE_ID}", provider_profile_id=profile_id,
                                 model=model, kind="image", request={}, result_asset_id=ids[name],
                                 created_at=datetime(2026, 10, 5, 10, minute)))
        db.commit()

    url = f"/api/plugins/instances/{instance_id}/workflow-library/outputs"
    body = client.get(url, params={"workspace_id": workspace, "path": "portrait.json"}).json()
    assert [one["asset_id"] for one in body["outputs"]] == [ids["表单-2.png"], ids["完整-1.png"], ids["表单-1.png"]], \
        "表单入口跑的是这张工作流的产出;别的工作流的表单入口不是"
    listed = client.get(f"/api/plugins/instances/{instance_id}/workflow-library", params={"workspace_id": workspace}).json()
    assert listed["workflows"][0]["last_output"]["asset_id"] == ids["表单-2.png"], "卡片上那一张也是全部入口里最新的那一份"


def test_只跑过表单入口时那一栏照样画得出(library) -> None:
    """最严重的那条:一张工作流**只在表单里**跑过(实测 `video_minimax_h3_i2v.json` 完整入口 0 次成功、表单入口成功 1 次),
    此前卡片上的 `last_output` 是 NULL,而界面是「`last_output` 非空才画这一栏」—— 整栏「最近的产出」都不出现。"""
    from app.db.models import GenerationJob

    client, instance_id = library
    workspace = client.post("/api/workspaces", json={"name": "工作流"}).json()["id"]
    with SessionLocal() as db:
        profile_id = _declare_entries(db, instance_id, [("portrait.json#k0a1nq", "portrait.json", "form")])
        ids = _made(db, workspace, ["表单跑出来的.png"])
        db.add(GenerationJob(workspace_id=workspace, provider=f"plugin:{PACKAGE_ID}", provider_profile_id=profile_id,
                             model="portrait.json#k0a1nq", kind="image", request={}, result_asset_id=ids["表单跑出来的.png"],
                             created_at=datetime(2026, 10, 5, 10, 3)))
        db.commit()

    listed = client.get(f"/api/plugins/instances/{instance_id}/workflow-library", params={"workspace_id": workspace}).json()
    card = listed["workflows"][0]
    assert card["last_output"] is not None and card["last_output"]["asset_id"] == ids["表单跑出来的.png"], \
        "只在表单里跑过:这一栏照样画得出,不是空的"
    assert card["generation"]["model"] == "portrait.json", "「用它生成」还是那个完整工作流入口,没被表单入口顶掉"
    url = f"/api/plugins/instances/{instance_id}/workflow-library/outputs"
    body = client.get(url, params={"workspace_id": workspace, "path": "portrait.json"}).json()
    assert [one["asset_id"] for one in body["outputs"]] == [ids["表单跑出来的.png"]]


def test_路径里带井号的另一张工作流不是这张的表单入口(library) -> None:
    """插件的 `models.split_id` 说得很清楚:路径本身可以带 `#`,所以先看 `.json` 结尾 —— 一张叫
    `portrait.json#copy.json` 的工作流,它的**完整入口**和工作流 `portrait.json` 的一张表单长得一模一样。拿
    `path + "#"` 去前缀匹配就会把这张拷贝跑出来的算到原版头上。认的是组号(那张图的路径),不是字符串前缀。"""
    from app.db.models import GenerationJob

    client, instance_id = library
    workspace = client.post("/api/workspaces", json={"name": "工作流"}).json()["id"]
    with SessionLocal() as db:
        profile_id = _declare_entries(db, instance_id, [
            ("portrait.json#app", "portrait.json", "form"),
            ("portrait.json#copy.json", "portrait.json#copy.json", "full"),
        ])
        ids = _made(db, workspace, ["原版的表单.png", "拷贝的.png"])
        for minute, name, model in ((3, "原版的表单.png", "portrait.json#app"),
                                    (5, "拷贝的.png", "portrait.json#copy.json")):
            db.add(GenerationJob(workspace_id=workspace, provider=f"plugin:{PACKAGE_ID}", provider_profile_id=profile_id,
                                 model=model, kind="image", request={}, result_asset_id=ids[name],
                                 created_at=datetime(2026, 10, 5, 10, minute)))
        db.commit()

    url = f"/api/plugins/instances/{instance_id}/workflow-library/outputs"
    body = client.get(url, params={"workspace_id": workspace, "path": "portrait.json"}).json()
    assert [one["asset_id"] for one in body["outputs"]] == [ids["原版的表单.png"]], "拷贝那张是它自己，不是原版的表单入口"
    listed = client.get(f"/api/plugins/instances/{instance_id}/workflow-library", params={"workspace_id": workspace}).json()
    assert listed["workflows"][0]["last_output"]["asset_id"] == ids["原版的表单.png"]
    own = client.get(url, params={"workspace_id": workspace, "path": "portrait.json#copy.json"}).json()
    assert [one["asset_id"] for one in own["outputs"]] == [ids["拷贝的.png"]], "带井号的路径自己那一张照样查得到"


def test_表单入口的工具调用也算这张工作流的产出(library) -> None:
    """同一张工作流在智能体 / 工作流节点里是当工具跑的,每个入口一个工具(表单入口的工具 `mirrors` 指的是**那个**表单入口)。
    只看生成任务的话,维护者用表单工具跑出来的那几张在这里看不见。入口清单也认插件报的 `group`(目录还没刷到时)。"""
    from app.db.models import GenerationJob, PluginInstance, PluginInvocation

    client, instance_id = library
    workspace = client.post("/api/workspaces", json={"name": "工作流"}).json()["id"]
    form_group = {"id": "portrait.json", "label": "portrait", "entry": "form", "order": 1}
    with SessionLocal() as db:
        instance = db.get(PluginInstance, instance_id)
        instance.discovered_tools = [
            {"name": "wf_portrait_app", "mirrors": {"generation_model": "portrait.json#app", "kind": "image"},
             "group": form_group},
            #: 这一张表单只在工具清单里(模型行还没刷出来):入口清单也认插件报的组
            {"name": "wf_portrait_k3x9a2", "mirrors": {"generation_model": "portrait.json#k3x9a2", "kind": "image"},
             "group": form_group},
            {"name": "wf_elsewhere", "mirrors": {"generation_model": "elsewhere.json", "kind": "image"},
             "group": {"id": "elsewhere.json", "label": "elsewhere", "entry": "full", "order": 0}},
        ]
        profile_id = _declare_entries(db, instance_id, [("portrait.json#app", "portrait.json", "form")])
        ids = _made(db, workspace, ["表单工具跑的.png", "别的工具跑的.png", "表单工具-2.png"])
        for minute, name, model in ((2, "表单工具跑的.png", "portrait.json#app"),
                                    (5, "别的工具跑的.png", "elsewhere.json"),
                                    (6, "表单工具-2.png", "portrait.json#k3x9a2")):
            db.add(GenerationJob(workspace_id=workspace, provider=f"plugin:{PACKAGE_ID}", provider_profile_id=profile_id,
                                 model=model, kind="image", request={}, result_asset_id=ids[name],
                                 created_at=datetime(2026, 10, 5, 10, minute)))
        db.add(PluginInvocation(instance_id=instance_id, tool_name="wf_portrait_app", status="succeeded",
                                output={"asset_ids": [ids["表单工具跑的.png"]]}, created_at=datetime(2026, 10, 5, 10, 3)))
        db.add(PluginInvocation(instance_id=instance_id, tool_name="wf_elsewhere", status="succeeded",
                                output={"asset_ids": [ids["别的工具跑的.png"]]}, created_at=datetime(2026, 10, 5, 10, 4)))
        db.add(PluginInvocation(instance_id=instance_id, tool_name="wf_portrait_k3x9a2", status="succeeded",
                                output={"asset_ids": [ids["表单工具-2.png"]]}, created_at=datetime(2026, 10, 5, 10, 7)))
        db.commit()

    url = f"/api/plugins/instances/{instance_id}/workflow-library/outputs"
    body = client.get(url, params={"workspace_id": workspace, "path": "portrait.json"}).json()
    assert [one["asset_id"] for one in body["outputs"]] == [ids["表单工具-2.png"], ids["表单工具跑的.png"]], \
        "表单入口的工具调用算这张的;别的入口的工具不算"
    listed = client.get(f"/api/plugins/instances/{instance_id}/workflow-library", params={"workspace_id": workspace}).json()
    assert listed["workflows"][0]["last_output"]["asset_id"] == ids["表单工具-2.png"]


def test_谁在用它_这个工作区里选了它的工作流和画板(library) -> None:
    client, instance_id = library
    workspace = client.post("/api/workspaces", json={"name": "工作流"}).json()["id"]
    other = client.post("/api/workspaces", json={"name": "别的"}).json()["id"]
    profile_id = client.get(f"/api/plugins/instances/{instance_id}/workflow-library").json()["workflows"][0]["generation"][
        "provider_profile_id"]
    choice = {"provider_profile_id": profile_id, "model": "portrait.json"}
    for ws, name in ((workspace, "分镜板"), (other, "别处的板")):
        board = client.post("/api/boards", json={"workspace_id": ws, "name": name}).json()
        saved = client.patch(f"/api/boards/{board['id']}", json={
            "workspace_id": ws, "base_revision": board.get("revision", 0),
            "canvas": {"items": [{"id": "i1", "kind": "image", "x": 0, "y": 0, "width": 320, "height": 180,
                                  "form": dict(choice)}]},
        })
        assert saved.status_code == 200, saved.text
    from app.db.models import Workflow

    with SessionLocal() as db:
        db.add(Workflow(workspace_id=workspace, name="出图流程", graph={"nodes": [
            {"id": "n1", "type": "generate", "config": {**choice, "kind": "image"}}], "edges": []}))
        db.commit()
    body = client.get(f"/api/plugins/instances/{instance_id}/workflow-library", params={"workspace_id": workspace}).json()
    portrait = body["workflows"][0]
    assert sorted((one["kind"], one["name"]) for one in portrait["used_by"]) == [("board", "分镜板"), ("workflow", "出图流程")], \
        "只列这个工作区里的"
    assert body["workflows"][1]["used_by"] == []


def test_取一张的原文(library) -> None:
    client, instance_id = library
    response = client.get(f"/api/plugins/instances/{instance_id}/workflow-library/content", params={"path": "sub/sketch.json"})
    assert response.status_code == 200, response.text
    assert response.json() == {"path": "sub/sketch.json", "content": {"nodes": [], "links": [], "path_seen": "sub/sketch.json"}}


@pytest.mark.parametrize("bad", ["../x.json", "/abs.json", "a\\b.json", "noext", "sub/.hidden.json", "a:b.json", "sub/ x.json"])
def test_路径不对的宿主当场拒绝_不交给插件(library, bad: str) -> None:
    client, instance_id = library
    response = client.post(f"/api/plugins/instances/{instance_id}/workflow-library/rename", json={"path": "portrait.json",
                                                                                                    "new_path": bad})
    assert response.status_code == 422, response.text
    assert not [one for one in _ops() if one.get("op") == "rename_workflow"]


def test_复制_改名_撞名回409带建议名_不覆盖(library) -> None:
    client, instance_id = library
    base = f"/api/plugins/instances/{instance_id}/workflow-library"
    clash = client.post(f"{base}/copy", json={"path": "portrait.json", "new_path": "taken.json"})
    assert clash.status_code == 409, clash.text
    assert clash.json()["detail"]["suggestion"] == "taken (1).json"
    assert "taken.json" in clash.json()["detail"]["message"]
    done = client.post(f"{base}/copy", json={"path": "portrait.json", "new_path": "portrait (1).json"})
    assert done.status_code == 200 and done.json() == {"path": "portrait (1).json"}
    moved = client.post(f"{base}/rename", json={"path": "portrait.json", "new_path": "sub/portrait.json"})
    assert moved.json() == {"path": "sub/portrait.json"}
    same = client.post(f"{base}/rename", json={"path": "portrait.json", "new_path": "portrait.json"})
    assert same.json() == {"path": "portrait.json"}
    assert [one["op"] for one in _ops() if one["op"].endswith("_workflow")] == ["copy_workflow", "copy_workflow",
                                                                                 "rename_workflow"], "改成原名不去插件"


def test_导入前先让插件认一遍_宿主规整预览(library) -> None:
    client, instance_id = library
    response = client.post(f"/api/plugins/instances/{instance_id}/workflow-library/inspect",
                           json={"text": '{"3": {"class_type": "KSampler", "inputs": {}}}', "filename": "人像.json"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["format"] == "api" and body["source"] == "json"
    assert body["workflow"]["nodes"] == [{"id": 3, "type": "KSampler"}]
    assert body["suggested_path"] == "人像.json"
    assert body["notes"] == ["这份是 API 格式,没有布局"], "空的、不是字的说明丢掉"
    assert body["graph"]["nodes"][0]["role"] == "sampler" and body["graph"]["auto_layout"] is True
    assert body["kind"] == "image" and body["parameters"][0]["key"] == "3.steps"
    assert body["missing_nodes"][0]["packs"][0]["id"] == "ComfyUI_Comfyroll_CustomNodes"
    assert body["missing_models"][0]["url"].startswith("https://huggingface.co/")
    sent = [one for one in _ops() if one["op"] == "inspect_import"][-1]
    assert sent == {"op": "inspect_import", "text": '{"3": {"class_type": "KSampler", "inputs": {}}}', "filename": "人像.json"}


def test_导入_插件建议的路径不像样就不给_插件说认不出照原话(library) -> None:
    client, instance_id = library
    base = f"/api/plugins/instances/{instance_id}/workflow-library"
    body = client.post(f"{base}/inspect", json={"data": "iVBORw0KGgo=", "filename": "evil.png"}).json()
    assert body["source"] == "png" and body["suggested_path"] == ""
    refused = client.post(f"{base}/inspect", json={"url": "https://example.com/flow.json"})
    assert refused.status_code == 422 and "不替你去取" in refused.text


@pytest.mark.parametrize("body", [{}, {"text": "{}", "url": "https://huggingface.co/a/b/resolve/main/x.json"},
                                  {"url": "ftp://example.com/x.json"}, {"text": "x" * 200}])
def test_导入_只给一样_链接要http_太大的不交给插件(library, monkeypatch, body) -> None:
    from app.domain import workflow_library

    monkeypatch.setattr(workflow_library, "MAX_IMPORT_CHARS", 100)
    client, instance_id = library
    response = client.post(f"/api/plugins/instances/{instance_id}/workflow-library/inspect", json=body)
    assert response.status_code == 422, response.text
    assert not [one for one in _ops() if one.get("op") == "inspect_import"]


def test_导入的存进去_不覆盖_撞名回409_原文以JSON字符串交给插件_存好重拉目录(library) -> None:
    client, instance_id = library
    base = f"/api/plugins/instances/{instance_id}/workflow-library"
    flow = {"id": "new-id", "nodes": [{"id": 3, "type": "KSampler"}], "links": []}
    clash = client.post(f"{base}/save", json={"path": "taken.json", "content": flow})
    assert clash.status_code == 409 and clash.json()["detail"]["suggestion"] == "taken (1).json"
    before = len([one for one in _ops() if one["op"] == "models"])
    done = client.post(f"{base}/save", json={"path": "导入/人像.json", "content": flow})
    assert done.status_code == 200 and done.json() == {"path": "导入/人像.json"}
    sent = [one for one in _ops() if one["op"] == "save_workflow"][-1]
    assert isinstance(sent["content"], str) and json.loads(sent["content"]) == flow
    assert len([one for one in _ops() if one["op"] == "models"]) > before
    for bad in ({"path": "x.json", "content": {"3": {"class_type": "KSampler"}}}, {"path": "../x.json", "content": flow}):
        assert client.post(f"{base}/save", json=bad).status_code == 422
    assert len([one for one in _ops() if one["op"] == "save_workflow"]) == 2, "不像样的不交给插件"


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "工作流库"}).json()["id"]


def test_装节点包是一个后台任务_进度照插件说的_装完说要重启_库里列着(library) -> None:
    client, instance_id = library
    workspace = _workspace(client)
    base = f"/api/plugins/instances/{instance_id}/workflow-library"
    response = client.post(f"{base}/install-nodes", json={"workspace_id": workspace,
                                                          "packs": ["ComfyUI_Comfyroll_CustomNodes"]})
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["kind"] == "node_install"
    assert wait_status(client, job["id"]) == "succeeded"
    done = client.get(f"/api/jobs/{job['id']}").json()
    assert done["result"] == {"installed": ["ComfyUI_Comfyroll_CustomNodes"], "restart": True}
    assert "重启" in done["message"]
    sent = [one for one in _ops() if one["op"] == "install_nodes"][-1]
    assert sent == {"op": "install_nodes", "packs": ["ComfyUI_Comfyroll_CustomNodes"]}
    listed = client.get(base, params={"workspace_id": workspace}).json()
    assert [(one["id"], one["status"]) for one in listed["installs"]] == [(job["id"], "succeeded")]


def test_装节点包_Manager拒绝时任务失败_原话留着(library) -> None:
    client, instance_id = library
    job = client.post(f"/api/plugins/instances/{instance_id}/workflow-library/install-nodes",
                      json={"workspace_id": _workspace(client), "packs": ["refused"]}).json()
    assert wait_status(client, job["id"]) == "failed"
    assert "personal_cloud" in client.get(f"/api/jobs/{job['id']}").json()["error"]


@pytest.mark.parametrize("packs", [[], ["a"] * 11, ["bad\nname"], [""], ["x" * 400]])
def test_装节点包_包名先过一遍(library, packs) -> None:
    client, instance_id = library
    response = client.post(f"/api/plugins/instances/{instance_id}/workflow-library/install-nodes",
                           json={"workspace_id": _workspace(client), "packs": packs})
    assert response.status_code == 422, response.text
    assert not [one for one in _ops() if one.get("op") == "install_nodes"]


def test_重启_经插件_回来以后重拉这个连接的目录(library) -> None:
    client, instance_id = library
    before = len([one for one in _ops() if one["op"] == "models"])
    response = client.post(f"/api/plugins/instances/{instance_id}/workflow-library/reboot")
    assert response.status_code == 200, response.text
    assert response.json() == {"back": True}
    assert len([one for one in _ops() if one["op"] == "models"]) > before, "重启后新装的节点包才加载:模型、工具清单跟着变"


def test_删除是挪进回收目录_能恢复_改完马上重拉目录(library) -> None:
    client, instance_id = library
    base = f"/api/plugins/instances/{instance_id}/workflow-library"
    before = len([one for one in _ops() if one["op"] == "models"])
    trashed = client.post(f"{base}/trash", json={"path": "sub/sketch.json"})
    assert trashed.status_code == 200, trashed.text
    assert trashed.json() == {"path": ".mosael-trash/workflows/20261005-101500/sub/sketch.json"}
    assert len([one for one in _ops() if one["op"] == "models"]) > before, "删了之后生成目录马上重拉,不等指纹"
    back = client.post(f"{base}/restore", json={"path": trashed.json()["path"]})
    assert back.json() == {"path": "sub/sketch.json"}, "不给新名字就回原处"
    clash = client.post(f"{base}/restore", json={"path": trashed.json()["path"], "new_path": "taken.json"})
    assert clash.status_code == 409
    bad = client.post(f"{base}/restore", json={"path": ".mosael-trash/elsewhere/x.json"})
    assert bad.status_code == 422, "不是回收目录里的东西不让「恢复」"


# --- 文件夹 ----------------------------------------------------------------------------


def test_列出来带着文件夹树_空的也在_工作流所在的补上_名字不像样的丢掉(library) -> None:
    client, instance_id = library
    body = client.get(f"/api/plugins/instances/{instance_id}/workflow-library").json()
    assert body["folders"] == ["sub", "空的", "空的/更深"], "插件报的空文件夹连同上级;sub 是 sketch 所在的;跳出去的、隐藏的、像工作流的丢掉"


def test_新建文件夹_名字先过一遍_撞名409带建议名_不重拉目录(library) -> None:
    client, instance_id = library
    base = f"/api/plugins/instances/{instance_id}/workflow-library"
    before = len([one for one in _ops() if one["op"] == "models"])
    made = client.post(f"{base}/folders", json={"path": "人像/草稿"})
    assert made.status_code == 200, made.text
    assert made.json() == {"path": "人像/草稿"}
    assert len([one for one in _ops() if one["op"] == "models"]) == before, "空文件夹什么模型都没变:不重拉"
    clash = client.post(f"{base}/folders", json={"path": "taken"})
    assert clash.status_code == 409 and clash.json()["detail"]["code"] == "exists"
    assert clash.json()["detail"]["suggestion"] == "taken (1)"
    odd = client.post(f"{base}/folders", json={"path": "odd"})
    assert odd.status_code == 409 and odd.json()["detail"]["suggestion"] == "", "插件给的建议名不像样就不给"
    for bad in ("../x", "a\\b", ".hidden", "a/.b", "a.json", "a//b", "a:b"):
        response = client.post(f"{base}/folders", json={"path": bad})
        assert response.status_code == 422, (bad, response.text)
    assert [one["path"] for one in _ops() if one["op"] == "make_folder"] == ["人像/草稿", "taken", "odd"], \
        "不合格的名字不交给插件"


def test_文件夹改名_里面的工作流换了路径_重拉目录_不能挪进自己里面(library) -> None:
    client, instance_id = library
    base = f"/api/plugins/instances/{instance_id}/workflow-library"
    before = len([one for one in _ops() if one["op"] == "models"])
    moved = client.post(f"{base}/folders/rename", json={"path": "sub", "new_path": "片子/草图"})
    assert moved.status_code == 200 and moved.json() == {"path": "片子/草图"}
    assert len([one for one in _ops() if one["op"] == "models"]) > before, "里面的工作流换了路径:生成目录马上重拉"
    clash = client.post(f"{base}/folders/rename", json={"path": "sub", "new_path": "taken"})
    assert clash.status_code == 409 and clash.json()["detail"]["suggestion"] == "taken (1)"
    inside = client.post(f"{base}/folders/rename", json={"path": "sub", "new_path": "SUB/inner"})
    assert inside.status_code == 422, "挪进它自己里面(不分大小写)"
    same = client.post(f"{base}/folders/rename", json={"path": "sub", "new_path": "sub"})
    assert same.json() == {"path": "sub"}
    assert [(one["path"], one["new_path"]) for one in _ops() if one["op"] == "rename_folder"] == [
        ("sub", "片子/草图"), ("sub", "taken")], "挪进自己里面、改成原名的不去插件"


def test_删除文件夹_只删空的_不空回409带个数_空的挪进回收目录(library) -> None:
    client, instance_id = library
    base = f"/api/plugins/instances/{instance_id}/workflow-library"
    full = client.post(f"{base}/folders/trash", json={"path": "full"})
    assert full.status_code == 409, full.text
    detail = full.json()["detail"]
    assert detail["code"] == "not_empty" and detail["count"] == 3 and "full" in detail["message"]
    empty = client.post(f"{base}/folders/trash", json={"path": "空的"})
    assert empty.status_code == 200 and empty.json() == {"path": ".mosael-trash/workflows/20261005-101500/空的"}
    assert client.post(f"{base}/folders/trash", json={"path": "../x"}).status_code == 422


def test_改名_挪文件夹_删除再恢复_在那张里开的对话家跟着挪_只挪那一张和那个文件夹里的(library) -> None:
    """ADR 0044 §9:在 Mosael 工作流库里改的,后端那个用例在同一个事务里挪家。挪不碰 updated_at;撞名没改成的不挪。"""
    client, instance_id = library
    base = f"/api/plugins/instances/{instance_id}/workflow-library"
    workspace = _workspace(client)

    def session(place_id: str) -> dict:
        created = client.post("/api/agent/sessions", json={"workspace_id": workspace,
                                                           "home": {"kind": "comfyui", "id": f"{instance_id}{place_id}"}})
        assert created.status_code == 200, created.text
        return created.json()

    def home(created: dict) -> str:
        return client.get(f"/api/agent/sessions/{created['id']}").json()["home_id"].removeprefix(instance_id)

    portrait = session("/portrait.json")
    sketch = session("/sub/deeper/sketch.json")
    lookalike = session("/subway/x.json")
    other_case = session("/SUB/x.json")
    unsaved = session("#workflows/portrait.json")

    assert client.post(f"{base}/rename", json={"path": "portrait.json", "new_path": "taken.json"}).status_code == 409
    assert home(portrait) == "/portrait.json", "撞名没改成:不挪"
    assert client.post(f"{base}/rename", json={"path": "portrait.json", "new_path": "sub/portrait.json"}).status_code == 200
    assert home(portrait) == "/sub/portrait.json"
    assert home(unsaved) == "#workflows/portrait.json", "同名的没存过那张是另一处"

    assert client.post(f"{base}/folders/rename", json={"path": "sub", "new_path": "片子/草图"}).status_code == 200
    assert (home(portrait), home(sketch)) == ("/片子/草图/portrait.json", "/片子/草图/deeper/sketch.json"), "文件夹里任意深的都跟着"
    assert (home(lookalike), home(other_case)) == ("/subway/x.json", "/SUB/x.json"), "前缀像的、大小写不同的是别的文件夹"

    trashed = client.post(f"{base}/trash", json={"path": "片子/草图/deeper/sketch.json"}).json()["path"]
    assert home(sketch) == f"/{trashed}", "进回收目录也跟着,恢复时才回得来"
    assert client.post(f"{base}/restore", json={"path": trashed, "new_path": "回来了.json"}).status_code == 200
    assert home(sketch) == "/回来了.json"
    after = client.get(f"/api/agent/sessions/{portrait['id']}").json()
    assert after["updated_at"] == portrait["updated_at"], "挪家不算对话里有动静"


# --- 应用表单(ADR 0038)---------------------------------------------------------------


def test_列出来的每一张带着它的应用表单_宿主规整一遍(library) -> None:
    client, instance_id = library
    body = client.get(f"/api/plugins/instances/{instance_id}/workflow-library").json()
    portrait, sketch = body["workflows"]
    app = portrait["app"]
    assert (app["status"], app["upgradable"], app["invalid"], app["stray"]) == ("ok", False, 1, 2)
    assert [(one["id"], one["title"]) for one in app["forms"]] == [("app", "人像应用"), ("k3x9a2", "精调")], \
        "id 不合规、重复的表单不要(插件那一侧本来就不报,这里再挡一道)"
    form = app["forms"][0]
    assert (form["fields"], form["invalid"], form["model"], form["tool"]) == (1, 1, "portrait.json#app", "wf_0123456789ab_app")
    assert [one["key"] for one in form["items"]] == ["10.image", "3.cfg", "12:5.text"], \
        "子图里面的节点(12:5)也在,没写是哪一格的丢掉"
    assert form["items"][0]["label"] == "人物" and form["items"][1]["problem"] == "节点 #3 上没有「cfg」"
    assert app["results"] == ["9", "12:5"], \
        "结果标记收根图上的节点号,也收子图里面的(`12:5` —— 它说的是执行节点号);不是节点号的(7)丢掉"
    assert sketch["app"] is None, "插件没说(转不过来的那张)就没有"


def test_编辑器读一张_名字按语言挑好_片段和生成目录同一套规整(library) -> None:
    """插件交回的是一对 `{"zh", "en"}`,**宿主在边界上按读的人的语言挑成一句**再给界面(和 `hint` 走同一条路,
    见 `_picked`)—— 「名字带着语言表透到前端去挑」那一套维护者撤掉了:「为了 ComfyUI 和 Mosael 的语言不匹配问题
    特地兼容做一套方案是不合理的」。挑好的那一句也是搜索、撞名、显示都读的那一句。
    """
    client, instance_id = library
    response = client.get(f"/api/plugins/instances/{instance_id}/workflow-library/app", params={"path": "portrait.json"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["path"] == "portrait.json" and body["modified"] == 1776098682.9 and body["editable"] is True
    by_key = {one["key"]: one for one in body["items"]}
    assert list(by_key) == ["6.text", "10.image", "seed", "4.ckpt_name", "12:5.steps"], "认不出种类的那一项丢掉"
    assert by_key["6.text"]["title"] == "提示词", "一对里挑好的那一句(这个请求是中文界面)"
    assert by_key["6.text"]["role"] == "prompt"
    assert by_key["6.text"]["spec"] == {"type": "string", "x-multiline": True, "default": "a cat"}, "认不得的字段不留"
    assert by_key["10.image"]["spec"] is None and by_key["10.image"]["node_title"] == "人物"
    assert by_key["4.ckpt_name"]["spec"]["x-model-folder"] == "checkpoints" and by_key["4.ckpt_name"]["folder"] == "checkpoints"
    assert by_key["12:5.steps"]["exposable"] is True and by_key["12:5.steps"]["unexposable_reason"] == "" and \
        by_key["12:5.steps"]["spec"]["title"] == "步数", "子图里面的节点和根图上的一样能放进应用表单"
    assert by_key["seed"]["exposable"] is True
    assert by_key["4.ckpt_name"]["node_label"] == "Checkpoint 加载器", "节点给人看的名字也按同一种语言挑好"
    assert by_key["10.image"]["node_label"] == "加载图像"
    assert by_key["12:5.steps"]["node_label"] == "K 采样器", "子图里的节点也带着"
    assert by_key["seed"]["node_label"] == "", "图级的项没有节点"
    assert by_key["4.ckpt_name"]["hint"] == "要加载的模型", "ComfyUI 给这一格的说明也按同一种语言挑好"
    assert by_key["4.ckpt_name"]["class_type"] == "CheckpointLoaderSimple", "类名留着给悬停说明排错"
    assert all("node_label_en" not in one for one in body["items"]), \
        "那条「英文名另走一路」的设计被否掉了,不留兼容分支(ADR 0006)"
    assert by_key["seed"]["hint"] == ""
    # 这里喂的是**打桩的插件回答**(上面那份 body),所以这一段只验宿主自己那一半:位置怎么规整。
    # 插件那边算没算出来、有没有被 `workflow_library.app` 的 `_item_out` 滤掉,由
    # tests/test_comfyui_plugin_workflow_library.py(`test_应用表单_蒙版属性穿过_item_out到得了宿主`)真的走一遍插件 ——
    # 两边各测一半正是当初漏掉那一跳的形状。
    assert by_key["10.image"]["mask_property"] == 1, \
        "「蒙版属性」排第几位从插件原样透出(ADR 0056 第一步):沿 MASK 走出来的位置,界面那一组照它摆"
    assert by_key["seed"]["mask_property"] == 0, \
        "只认一种形状(ADR 0006):位置是一个 1 起数的整数 —— 插件写 `true` 那种不当成第 1 位,当不在这一路上"
    assert body["outputs"] == [
        {"node": "9", "title": "SaveImage", "label": "保存图像", "class_type": "SaveImage", "media": "image"},
        {"node": "12", "title": "高清", "label": "高清", "class_type": "SaveImage", "media": "image"},
    ], "输出节点给人看的名字按语言挑好;插件没给就用标题"
    assert (body["app"]["status"], body["app"]["version"], body["app"]["upgradable"]) == ("unsupported", "1", True)
    bad = client.get(f"/api/plugins/instances/{instance_id}/workflow-library/app", params={"path": "../x.json"})
    assert bad.status_code == 422


def test_编辑器读一张_插件只给一句时原样就是那一句(library) -> None:
    """插件只交回一个字符串的名字(不是一对)时,那一句原样透出 —— 不硬凑成一张表,也不动它一个字。"""
    client, instance_id = library
    body = client.get(f"/api/plugins/instances/{instance_id}/workflow-library/app", params={"path": "portrait.json"}).json()
    by_key = {one["key"]: one for one in body["items"]}
    assert by_key["10.image"]["title"] == "参考图 · 人物", "插件只给了一句:接口给的就是那一句"
    assert by_key["12:5.steps"]["title"] == "步数"
    assert isinstance(by_key["10.image"]["title"], str) and isinstance(by_key["12:5.steps"]["title"], str), \
        "不是一张表(不硬凑成 `{\"zh\": …}`)"


def test_写表单_宿主先查形状_改动时间对不上回409_成了让目录重拉(library) -> None:
    client, instance_id = library
    url = f"/api/plugins/instances/{instance_id}/workflow-library/annotate"
    app = {"id": "app", "title": " 人像应用 ", "description": "", "items": [
        {"node": "10", "input": "image", "label": " 人物 "},
        {"node": "6", "input": "text", "main": True},
        {"input": "seed", "main": True, "choices": ["x"]},
        {"node": "4", "input": "ckpt_name", "choices": ["a.safetensors"]},
    ]}
    for bad in ({"node": "12-5", "input": "text"}, {"node": "12:", "input": "text"}, {"input": "steps"},
                {"node": "10", "input": "image"}):
        response = client.post(url, json={"path": "portrait.json", "modified": 5,
                                          "forms": [{**app, "items": [*app["items"], bad]}]})
        assert response.status_code == 422, (bad, response.text)
    for forms in ([app, app], [{**app, "id": "Bad-Id"}], [{"title": str(n)} for n in range(21)]):
        assert client.post(url, json={"path": "portrait.json", "modified": 5, "forms": forms}).status_code == 422, \
            "id 重复、不合规、超过 20 张"
    assert not [op for op in _ops() if op["op"] == "annotate"], "形状不对的不交给插件"

    #: 子图里面的节点(`12:5`)和根图上的节点一样能写进表单,也一样能标成结果;两层的(`12:5:3`)也一样
    inside = client.post(url, json={"path": "portrait.json", "modified": 1776098682.9, "results": ["9", "12:5"],
                                    "forms": [{**app, "items": [*app["items"], {"node": "12:5", "input": "steps"},
                                                                {"node": "12:5:3", "input": "denoise"}]}]})
    assert inside.status_code == 200, inside.text
    assert [op for op in _ops() if op["op"] == "annotate"][-1]["forms"][0]["items"][-2:] == \
        [{"node": "12:5", "input": "steps", "label": ""}, {"node": "12:5:3", "input": "denoise", "label": ""}], \
        "子图里面的节点照样交给插件写(写法原样带过去)"
    assert [op for op in _ops() if op["op"] == "annotate"][-1]["results"] == ["9", "12:5"], \
        "「结果取自」里子图里面的输出节点(`12:5`)照样交给插件写 —— 从前这里 422,而界面上那一栏明明列着它"

    stale = client.post(url, json={"path": "portrait.json", "modified": 1.0, "forms": [app], "results": ["9"]})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale" and stale.json()["detail"]["modified"] == 2.0

    refreshed = len([op for op in _ops() if op["op"] == "models"])
    done = client.post(url, json={"path": "portrait.json", "modified": 1776098682.9,
                                  "forms": [app, {"title": "精调", "items": [{"node": "4", "input": "ckpt_name"}]}],
                                  "results": ["9"]})
    assert done.status_code == 200, done.text
    assert done.json() == {"path": "portrait.json", "modified": 1776098699.5}
    sent = [op for op in _ops() if op["op"] == "annotate"][-1]
    assert sent["modified"] == 1776098682.9 and sent["results"] == ["9"]
    assert sent["forms"] == [{"id": "app", "title": "人像应用", "description": "", "items": [
        {"node": "10", "input": "image", "label": "人物"},
        {"node": "6", "input": "text", "label": "", "main": True},
        {"node": "", "input": "seed", "label": ""},
        {"node": "4", "input": "ckpt_name", "label": "", "choices": ["a.safetensors"]},
    ]}, {"title": "精调", "description": "", "items": [{"node": "4", "input": "ckpt_name", "label": ""}]}], \
        "名字去掉首尾空白;图级的项没有 main / choices;新表单不带 id(插件起)"
    assert len([op for op in _ops() if op["op"] == "models"]) > refreshed, "改成了:这个连接的目录马上重拉(生成表单跟着变)"

    removed = client.post(url, json={"path": "portrait.json", "modified": 1776098682.9, "forms": [], "results": []})
    assert removed.status_code == 200 and [op for op in _ops() if op["op"] == "annotate"][-1]["forms"] == []


def test_升级旧格式的表单标记_交给插件逐张改_只报问过的那几张_改成了让目录重拉(library) -> None:
    client, instance_id = library
    url = f"/api/plugins/instances/{instance_id}/workflow-library/upgrade-marks"
    assert client.post(url, json={"paths": [{"path": "../x.json", "modified": 1}]}).status_code == 422
    assert not [op for op in _ops() if op["op"] == "upgrade_marks"]
    refreshed = len([op for op in _ops() if op["op"] == "models"])
    response = client.post(url, json={"paths": [{"path": "portrait.json", "modified": 1776098682.9},
                                                {"path": "busy.json", "modified": 3}, {"path": "broken.json"}]})
    assert response.status_code == 200, response.text
    assert response.json() == {"upgraded": ["portrait.json"], "stale": ["busy.json"], "skipped": [], "gone": [],
                               "failed": [{"path": "broken.json", "reason": "拉不下来"}]}, "没问过的那张不认"
    sent = [op for op in _ops() if op["op"] == "upgrade_marks"][-1]
    assert sent["paths"] == [{"path": "portrait.json", "modified": 1776098682.9}, {"path": "busy.json", "modified": 3},
                             {"path": "broken.json", "modified": None}]
    assert len([op for op in _ops() if op["op"] == "models"]) > refreshed, "改成了:表单入口要出来,目录马上重拉"



#: 工作台画布上的一张(界面格式)和它导出的 API 图。
CANVAS = {"nodes": [{"id": 9, "type": "SaveImage"}, {"id": 10, "type": "LoadImage"}], "links": []}
CANVAS_PROMPT = {"9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0]}}}


def test_工作台_画布上这张的应用表单_没有路径和改动时间_不是界面格式的不交给插件(library) -> None:
    client, instance_id = library
    url = f"/api/plugins/instances/{instance_id}/workflow-library/app/live"
    response = client.post(url, json={"content": CANVAS})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["path"] == "" and body["modified"] is None, "改的是画布,不是文件"
    assert [one["key"] for one in body["items"]][:2] == ["6.text", "10.image"]
    sent = [op for op in _ops() if op["op"] == "app"][-1]
    assert sent == {"op": "app", "content": CANVAS}, "读的是画布上这张;画布没说开的是哪张就不带路径"
    named = client.post(url, json={"content": CANVAS, "path": "portrait.json"})
    assert named.json()["path"] == "portrait.json" and named.json()["modified"] is None
    assert [op for op in _ops() if op["op"] == "app"][-1] == {"op": "app", "content": CANVAS, "path": "portrait.json"}, \
        "带着路径:插件说得出每张表单的模型 id 和工具名(只用来起名字,不读文件)"
    #: 工作台「运行与结果」说节点用它:和表单项、「结果取自」同一种叫法,按看的人的语言挑好;没名字、没节点号的不要
    assert body["names"] == {"9": "保存图像", "12:5": "K采样器"}
    calls = len(_ops())
    assert client.post(url, json={"content": {"3": {"class_type": "KSampler"}}}).status_code == 422
    assert len(_ops()) == calls


#: 一个节点号的形状(`12` 是根图上的、`12:5` 是根图 12 号那个子图里面的 5 号、`12:5:3` 再往里一层,ADR 0042 §6)。
#: 用例**不在这里抄**:它住在 `contracts/node-shapes.json` 的 `any_node`,宿主 `_ANY_NODE`
#: (`backend/app/domain/workflow_library.py`)和桥的 `ANY_NODE`(`electron/ipc-contract.cjs`)说的都是它,
#: 而两侧的跑手读的是同一份文件(这边 + `electron/ipc-contract.test.ts`)。
#:
#: **抄一份的代价是「改判据」变成两处编辑,而两边都能各自变绿** —— 这正是桥曾经只认顶层节点号、而宿主
#: 早就在收子图节点号的那次。跨语言共用不了一份正则,就共用同一份用例。
_NODE_SHAPES = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "node-shapes.json").read_text(encoding="utf-8"))
NODE_KEYS_OK = next(one for one in _NODE_SHAPES["shapes"] if one["name"] == "any_node")["cases"]["ok"]
NODE_KEYS_BAD = next(one for one in _NODE_SHAPES["shapes"] if one["name"] == "any_node")["cases"]["bad"]


def test_工作台_同步标记的节点号_子图里的和根图上的一样收_不成样子的两头都拒(library) -> None:
    """「同步到画布」这条链上节点号只有**一套形状判据**:宿主 `_ANY_NODE`(表单里那一项的 `node`、「结果取自」的每一项、
    插件交回的 `marks.nodes` 的键)和桥的 `ANY_NODE`(同一个键过桥时再查一遍)。表单里有**子图项**时两头都必须放行 ——
    桥那一侧曾经只认顶层节点号,整条链就断在它那一句话上(维护者截图:`marks.nodes keys must be top-level node ids`,
    表单里 18 项有子图里的那几项)。**「结果取自」曾经另有一份只认根图的正则**(`_ROOT_NODE`):那一栏里看得见子图里的
    保存节点,选它却 422 —— 现在三处共用这一套。用例与 TS 那边同一份(见 `NODE_KEYS_OK`)。
    """
    client, instance_id = library
    url = f"/api/plugins/instances/{instance_id}/workflow-library/app/marks"
    for key in NODE_KEYS_OK:
        response = client.post(url, json={"content": CANVAS, "forms": [{"items": [{"node": key, "input": "steps"}]}]})
        assert response.status_code == 200, f"{key} 是一个节点号(子图里的照样放行):{response.text}"
        back = client.post(url, json={"content": {**CANVAS, "keys": [key]}})
        assert back.status_code == 200 and list(back.json()["nodes"]) == [key], back.text
        marked = client.post(url, json={"content": CANVAS, "results": [key]})
        assert marked.status_code == 200, f"{key} 标得成结果(「结果取自」说的是执行节点号):{marked.text}"
        assert [op for op in _ops() if op["op"] == "app_marks"][-1]["results"] == [key]
    for key in NODE_KEYS_BAD:
        assert client.post(url, json={"content": CANVAS,
                                      "forms": [{"items": [{"node": key, "input": "steps"}]}]}).status_code == 422, \
            f"{key} 不是一个节点号:别放水成什么都收"
        assert client.post(url, json={"content": {**CANVAS, "keys": [key]}}).status_code == 422, \
            f"插件交回 {key} 这种键:不交给界面去改画布"
        bad = client.post(url, json={"content": CANVAS, "results": [key]})
        assert bad.status_code == 422, f"「结果取自」收到 {key}:拒掉,别放水"
        assert "12:5" in bad.json()["detail"], "说清它真正收的是什么(根图上的节点号、子图里面的 `12:5`)"


def test_工作台_写进画布的标记_宿主先查形状_规整插件交回的(library) -> None:
    client, instance_id = library
    url = f"/api/plugins/instances/{instance_id}/workflow-library/app/marks"
    response = client.post(url, json={"content": CANVAS, "forms": [{"id": "app", "title": " 人像应用 ", "items": [
        {"node": "10", "input": "image", "label": "人物"}]}], "results": ["9"]})
    assert response.status_code == 200, response.text
    assert response.json() == {"nodes": {"9": {"result": True}, "10": {"forms": {"app": {"image": {"order": 0}}}}},
                               "extra": {"version": 2, "forms": [{"id": "app", "title": "人像应用"}]}}
    sent = [op for op in _ops() if op["op"] == "app_marks"][-1]
    assert sent["forms"][0]["title"] == "人像应用" and sent["results"] == ["9"]
    assert not [op for op in _ops() if op["op"] == "annotate"], "画布开着时不写文件"
    calls = len(_ops())
    marks = client.post(url, json={"content": CANVAS, "results": ["12:5"]})
    assert marks.status_code == 200, marks.text
    assert [op for op in _ops() if op["op"] == "app_marks"][-1]["results"] == ["12:5"], \
        "「结果取自」里的子图输出节点(`12:5`)照样交给插件去改画布 —— 从前这里 422"
    assert client.post(url, json={"content": CANVAS, "forms": [{"items": [{"node": "12:5:3", "input": "x"}]}]}
                       ).status_code == 200, "子图里面(套两层)的节点:表单拿它,桥按路径改画布上那一个"
    assert client.post(url, json={"content": CANVAS, "results": ["abc"]}).status_code == 422
    assert len(_ops()) == calls + 2, "形状不对的不交给插件"
    inside = client.post(url, json={"content": {**CANVAS, "inside": True}, "results": []})
    assert inside.status_code == 200 and inside.json()["nodes"] == {"12:5": {"forms": {"app": {"steps": {"order": 0}}}}}, \
        "插件交回子图里面的节点(`12:5`):原样交给界面去改画布"
    evil = client.post(url, json={"content": {**CANVAS, "evil": True}, "results": []})
    assert evil.status_code == 422, "插件交回的写法不成样子:不交给界面去改画布"


def test_工作台_跑画布上的图_普通的生成任务_图在任务载荷里_出口不带(library) -> None:
    client, instance_id = library
    workspace_id = client.post("/api/workspaces", json={"name": "工作台"}).json()["id"]
    url = f"/api/plugins/instances/{instance_id}/workflow-library/run"
    not_model = client.post(url, json={"workspace_id": workspace_id, "path": "新的.json", "prompt": CANVAS_PROMPT})
    assert not_model.status_code == 422 and "还不是" in not_model.json()["detail"], "新建的要先存一次、刷新出来"
    bad = client.post(url, json={"workspace_id": workspace_id, "path": "portrait.json", "prompt": {"9": "SaveImage"}})
    assert bad.status_code == 422
    response = client.post(url, json={"workspace_id": workspace_id, "path": "portrait.json", "prompt": CANVAS_PROMPT,
                                      "workflow": CANVAS, "client_id": "4f1c0e2a9b7d4c51a3e8"})
    assert response.status_code == 200, response.text
    body = response.json()
    generation, job = body["generation"], body["job"]
    assert generation["model"] == "portrait.json" and generation["kind"] == "image"
    assert generation["request"]["parameters"] == {} and generation["request"]["workbench"] is True, \
        "图不进生成参数、不进生成记录的请求"
    assert "workbench_graph" not in job["payload"], "任务出口不带那张图"
    assert wait_status(client, job["id"]) == "failed"
    sent = [op for op in _ops() if op["op"] == "generate"][-1]
    assert sent["graph"] == {"prompt": CANVAS_PROMPT, "workflow": CANVAS, "client_id": "4f1c0e2a9b7d4c51a3e8"}
    assert sent["parameters"] == {} and sent["prompt"] == ""
    assert "画布上的图" in client.get(f"/api/jobs/{job['id']}").json()["error"]


def test_工作台运行前主动对账连接目录_不把已保存工作流误报成非模型(library) -> None:
    client, instance_id = library
    workspace_id = client.post("/api/workspaces", json={"name": "工作台"}).json()["id"]
    with SessionLocal() as db:
        profile = db.scalar(select(ProviderProfile).where(ProviderProfile.plugin_instance_id == instance_id))
        row = db.scalar(select(ProviderModel).where(
            ProviderModel.provider_profile_id == profile.id,
            ProviderModel.model_id == "portrait.json",
        ))
        db.delete(row)
        db.commit()
    before = len([one for one in _ops() if one["op"] == "models"])
    response = client.post(
        f"/api/plugins/instances/{instance_id}/workflow-library/run",
        json={"workspace_id": workspace_id, "path": "portrait.json", "prompt": CANVAS_PROMPT},
    )
    assert response.status_code == 200, response.text
    assert len([one for one in _ops() if one["op"] == "models"]) > before, "运行命令自己对账这一台连接的目录"


def test_装节点包_图上写的版本交给插件_不属于这一批的键丢掉(library) -> None:
    """图上写着 `ver` 时,宿主把「包 → 版本」一起交给插件(插件再交给 Manager);不属于这一批包的键不收。"""
    client, instance_id = library
    workspace = _workspace(client)
    response = client.post(f"/api/plugins/instances/{instance_id}/workflow-library/install-nodes", json={
        "workspace_id": workspace, "packs": ["ComfyUI_Comfyroll_CustomNodes"],
        "versions": {"ComfyUI_Comfyroll_CustomNodes": "1.2.3", "someone-else": "9.9.9"}})
    assert response.status_code == 200, response.text
    assert wait_status(client, response.json()["id"]) == "succeeded"
    sent = [one for one in _ops() if one["op"] == "install_nodes"][-1]
    assert sent == {"op": "install_nodes", "packs": ["ComfyUI_Comfyroll_CustomNodes"],
                    "versions": {"ComfyUI_Comfyroll_CustomNodes": "1.2.3"}}, "不认识的键不交给那台机器"
