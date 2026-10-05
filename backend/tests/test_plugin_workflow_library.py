"""工作流库(ADR 0035):认领 `workflow_library` 的连接,宿主替它列工作流、取原文、改那台服务器上的工作流文件。

钉住的是**框架**,不是 ComfyUI(那个在 test_comfyui_plugin_workflow_library.py):

- 目录类能力:认领它的工具不进工具表,能力词表里叫得出名字;
- 列出来的是插件报的那一份,宿主规整字段(路径不对的、坏条目丢掉,图摘要的连线只留指着节点的);
- 宿主补上它在 Mosael 里的样子:是不是这个连接下的生成模型(用它生成要它)、这个工作区里最近一次用它生成的产出、
  这个工作区里哪些工作流节点 / 画板格子选的是它;
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

from app.core.db import SessionLocal
from app.db.models import PluginPackage
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
             "missing_nodes": [{"type": "CR Prompt Text", "count": 2,
                                "packs": [{"id": "ComfyUI_Comfyroll_CustomNodes", "title": "Comfyroll", "installed": False}]}],
             "missing_models": [{"folder": "vae", "name": "ae.safetensors",
                                 "url": "https://huggingface.co/x/y/resolve/main/ae.safetensors"}],
             "app": {"status": "ok", "app": True, "title": " 人像应用 ", "description": "", "fields": 1, "invalid": 1,
                     "items": [{"key": "10.image", "node": "10", "input": "image", "label": "人物", "main": False},
                               {"key": "3.cfg", "node": "3", "input": "cfg", "label": "", "problem": "节点 #3 上没有「cfg」"},
                               {"key": "12:5.text", "node": "12:5", "input": "text"},
                               {"node": "4", "input": ""}],
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
        emit({"ok": True, "output": {"nodes": {"12:5": {"result": True}}, "extra": None}})
    else:
        emit({"ok": True, "output": {"nodes": {"9": {"result": True}, "10": {"expose": {"image": {"order": 0}}}},
                                     "extra": {"version": 1, "app": {"title": "人像应用"}}, "ignored": 1}})
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
             "media": "image", "title": "参考图 · 人物", "node_title": "人物", "class_type": "LoadImage", "common": True},
            {"key": "seed", "node": "", "input": "seed", "kind": "seed", "title": {"zh": "种子", "en": "Seed"},
             "schema": {"type": "integer", "minimum": 0}},
            {"key": "4.ckpt_name", "node": "4", "input": "ckpt_name", "kind": "model", "folder": "checkpoints",
             "title": {"zh": "模型", "en": "Checkpoint"}, "class_type": "CheckpointLoaderSimple",
             "node_label": {"zh": "Checkpoint 加载器", "en": "Load Checkpoint"},
             "hint": {"zh": "要加载的模型", "en": "The name of the checkpoint (model) to load."},
             "schema": {"type": "string", "enum": ["a.safetensors", "b.safetensors"], "x-model-folder": "checkpoints"}},
            {"key": "12:5.steps", "node": "12:5", "input": "steps", "kind": "number", "title": "步数",
             "schema": {"type": "integer", "title": {"zh": "步数", "en": "Steps"}}},
            {"key": "x", "node": "3", "input": "x", "kind": "weird", "title": "?"},
        ],
        "outputs": [{"node": "9", "title": "SaveImage", "class_type": "SaveImage", "media": "image",
                     "label": {"zh": "保存图像", "en": "Save Image"}},
                    {"node": "12", "title": "高清", "class_type": "SaveImage", "media": "image"}],
        "app": {"status": "unsupported", "version": 2, "items": [], "results": []},
    }})
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
    assert portrait["missing_nodes"] == [{"type": "CR Prompt Text", "count": 2, "packs": [
        {"id": "ComfyUI_Comfyroll_CustomNodes", "title": "Comfyroll", "installed": False}]}]
    assert portrait["missing_models"][0]["url"].startswith("https://huggingface.co/")
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


# --- 应用表单(ADR 0038)---------------------------------------------------------------


def test_列出来的每一张带着它的应用表单_宿主规整一遍(library) -> None:
    client, instance_id = library
    body = client.get(f"/api/plugins/instances/{instance_id}/workflow-library").json()
    portrait, sketch = body["workflows"]
    app = portrait["app"]
    assert (app["status"], app["app"], app["title"], app["fields"], app["invalid"]) == ("ok", True, "人像应用", 1, 1)
    assert [one["key"] for one in app["items"]] == ["10.image", "3.cfg"], "子图里的节点、没写是哪一格的丢掉"
    assert app["items"][0]["label"] == "人物" and app["items"][1]["problem"] == "节点 #3 上没有「cfg」"
    assert app["results"] == ["9"], "结果标记只认根图上的节点号"
    assert sketch["app"] is None, "插件没说(转不过来的那张)就没有"


def test_编辑器读一张_名字按语言挑好_片段和生成目录同一套规整(library) -> None:
    client, instance_id = library
    response = client.get(f"/api/plugins/instances/{instance_id}/workflow-library/app", params={"path": "portrait.json"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["path"] == "portrait.json" and body["modified"] == 1776098682.9 and body["editable"] is True
    by_key = {one["key"]: one for one in body["items"]}
    assert list(by_key) == ["6.text", "10.image", "seed", "4.ckpt_name", "12:5.steps"], "认不出种类的那一项丢掉"
    assert by_key["6.text"]["title"] == "提示词" and by_key["6.text"]["role"] == "prompt"
    assert by_key["6.text"]["spec"] == {"type": "string", "x-multiline": True, "default": "a cat"}, "认不得的字段不留"
    assert by_key["10.image"]["spec"] is None and by_key["10.image"]["node_title"] == "人物"
    assert by_key["4.ckpt_name"]["spec"]["x-model-folder"] == "checkpoints" and by_key["4.ckpt_name"]["folder"] == "checkpoints"
    assert by_key["12:5.steps"]["exposable"] is False and by_key["12:5.steps"]["spec"]["title"] == "步数", \
        "子图里面的节点照样列出来,标着这一版不能放进应用表单"
    assert by_key["seed"]["exposable"] is True
    assert by_key["4.ckpt_name"]["node_label"] == "Checkpoint 加载器" and by_key["4.ckpt_name"]["hint"] == "要加载的模型", \
        "节点给人看的名字、ComfyUI 的说明也按语言挑好"
    assert by_key["4.ckpt_name"]["class_type"] == "CheckpointLoaderSimple", "类名留着给悬停说明排错"
    assert by_key["seed"]["node_label"] == "" and by_key["seed"]["hint"] == ""
    assert body["outputs"] == [
        {"node": "9", "title": "SaveImage", "label": "保存图像", "class_type": "SaveImage", "media": "image"},
        {"node": "12", "title": "高清", "label": "高清", "class_type": "SaveImage", "media": "image"},
    ], "输出节点给人看的名字按语言挑好;插件没给就用标题"
    assert body["app"]["status"] == "unsupported" and body["app"]["version"] == "2"
    bad = client.get(f"/api/plugins/instances/{instance_id}/workflow-library/app", params={"path": "../x.json"})
    assert bad.status_code == 422


def test_写应用表单_宿主先查形状_改动时间对不上回409_成了让目录重拉(library) -> None:
    client, instance_id = library
    url = f"/api/plugins/instances/{instance_id}/workflow-library/annotate"
    app = {"title": " 人像应用 ", "description": "", "items": [
        {"node": "10", "input": "image", "label": " 人物 "},
        {"node": "6", "input": "text", "main": True},
        {"input": "seed", "main": True, "choices": ["x"]},
        {"node": "4", "input": "ckpt_name", "choices": ["a.safetensors"]},
    ]}
    for bad in ({"node": "12:5", "input": "text"}, {"input": "steps"}, {"node": "10", "input": "image"}):
        response = client.post(url, json={"path": "portrait.json", "modified": 5, "app": {**app, "items": [*app["items"], bad]}})
        assert response.status_code == 422, (bad, response.text)
    assert client.post(url, json={"path": "portrait.json", "modified": 5, "app": None,
                                  "results": ["12:5"]}).status_code == 422
    assert not [op for op in _ops() if op["op"] == "annotate"], "形状不对的不交给插件"

    stale = client.post(url, json={"path": "portrait.json", "modified": 1.0, "app": app, "results": ["9"]})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale" and stale.json()["detail"]["modified"] == 2.0

    refreshed = len([op for op in _ops() if op["op"] == "models"])
    done = client.post(url, json={"path": "portrait.json", "modified": 1776098682.9, "app": app, "results": ["9"]})
    assert done.status_code == 200, done.text
    assert done.json() == {"path": "portrait.json", "modified": 1776098699.5}
    sent = [op for op in _ops() if op["op"] == "annotate"][-1]
    assert sent["modified"] == 1776098682.9 and sent["results"] == ["9"]
    assert sent["app"] == {"title": "人像应用", "description": "", "items": [
        {"node": "10", "input": "image", "label": "人物"},
        {"node": "6", "input": "text", "label": "", "main": True},
        {"node": "", "input": "seed", "label": ""},
        {"node": "4", "input": "ckpt_name", "label": "", "choices": ["a.safetensors"]},
    ]}, "名字去掉首尾空白;图级的项没有 main / choices"
    assert len([op for op in _ops() if op["op"] == "models"]) > refreshed, "改成了:这个连接的目录马上重拉(生成表单跟着变)"

    removed = client.post(url, json={"path": "portrait.json", "modified": 1776098682.9, "app": None, "results": []})
    assert removed.status_code == 200 and [op for op in _ops() if op["op"] == "annotate"][-1]["app"] is None



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
    assert sent == {"op": "app", "content": CANVAS}, "读的是画布上这张,不带路径"
    calls = len(_ops())
    assert client.post(url, json={"content": {"3": {"class_type": "KSampler"}}}).status_code == 422
    assert len(_ops()) == calls


def test_工作台_写进画布的标记_宿主先查形状_规整插件交回的(library) -> None:
    client, instance_id = library
    url = f"/api/plugins/instances/{instance_id}/workflow-library/app/marks"
    response = client.post(url, json={"content": CANVAS, "app": {"title": " 人像应用 ", "items": [
        {"node": "10", "input": "image", "label": "人物"}]}, "results": ["9"]})
    assert response.status_code == 200, response.text
    assert response.json() == {"nodes": {"9": {"result": True}, "10": {"expose": {"image": {"order": 0}}}},
                               "extra": {"version": 1, "app": {"title": "人像应用"}}}
    sent = [op for op in _ops() if op["op"] == "app_marks"][-1]
    assert sent["app"]["title"] == "人像应用" and sent["results"] == ["9"]
    assert not [op for op in _ops() if op["op"] == "annotate"], "画布开着时不写文件"
    calls = len(_ops())
    assert client.post(url, json={"content": CANVAS, "results": ["12:5"]}).status_code == 422, "子图里的节点不能标"
    assert len(_ops()) == calls, "形状不对的不交给插件"
    evil = client.post(url, json={"content": {**CANVAS, "evil": True}, "results": []})
    assert evil.status_code == 422, "插件交回的节点号不是根图上的:不交给界面去改画布"


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
